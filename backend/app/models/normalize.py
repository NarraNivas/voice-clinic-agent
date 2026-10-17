"""Input normalization for the HTTP boundary.

Voice agents and people write dates and times in many ways. These functions turn common forms
into the strict values the API stores: YYYY-MM-DD, 24-hour HH:MM, and one of three appointment
types.

The time rules are deliberately conservative:

- Canonical 24-hour text (`03:30`, `15:30`) is returned exactly as written.
- Text that contains more than one time expression ("three thirty five") is ambiguous and is
  returned unchanged.
- Text that corrects itself ("not 3:30, make it 4:00 PM") is returned unchanged.
- Anything else is read as a single time, with an explicit AM or PM marker or afternoon wording
  taken into account.

Anything that cannot be read safely is returned unchanged, so Pydantic validation rejects it and
names the field. The functions never raise and never log the input.
"""

import re
from datetime import date as Date
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import DEFAULT_TIMEZONE

_TYPE_ALIASES = {
    "check up": "checkup",
    "consult": "consultation",
    "dental cleaning": "cleaning",
    "teeth cleaning": "cleaning",
}


def normalize_appointment_type(value: Any) -> Any:
    """Accept 'Consultation', ' CHECKUP ', and 'check-up'. Unknown types still fail validation."""
    if not isinstance(value, str):
        return value
    cleaned = " ".join(value.lower().replace("-", " ").split())
    return _TYPE_ALIASES.get(cleaned, cleaned)


# --- times ---------------------------------------------------------------------------------

_CANONICAL_TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
_CORRECTION = re.compile(
    r"(?<![a-z])(not|no|instead|actually|rather|correction|change|wait|or)(?![a-z])"
)
_PM = re.compile(r"(?<![a-z])(p\.?\s?m\.?|afternoon|evening|tonight)(?![a-z])")
_AM = re.compile(r"(?<![a-z])(a\.?\s?m\.?|morning)(?![a-z])")

_HOUR_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_HOUR_WORD = "|".join(sorted(_HOUR_WORDS, key=len, reverse=True))
_MINUTE_WORDS = {
    "thirty": 30,
    "fifteen": 15,
    "forty five": 45,
    "forty-five": 45,
    "fortyfive": 45,
    "twenty": 20,
    "oclock": 0,
    "o'clock": 0,
}
_MINUTE_WORD = "|".join(sorted(_MINUTE_WORDS, key=len, reverse=True))

# Each pattern describes one way a time can be written. Every match is a candidate. Overlapping
# candidates are resolved by keeping the earliest, then the longest.
_CANDIDATES: list[tuple[str, re.Pattern[str]]] = [
    ("half_past", re.compile(rf"\bhalf past (?P<h>{_HOUR_WORD})\b")),
    ("quarter", re.compile(rf"\bquarter (?P<dir>past|to) (?P<h>{_HOUR_WORD})\b")),
    ("word", re.compile(rf"\b(?P<h>{_HOUR_WORD})(?:[\s-]+(?P<m>{_MINUTE_WORD}))?\b")),
    ("clock", re.compile(r"(?<!\d)(?P<h>\d{1,2})[:.](?P<m>\d{2})(?::\d{2})?(?!\d)")),
    ("spaced", re.compile(r"(?<!\d)(?P<h>\d{1,2})\s(?P<m>\d{2})(?!\d)")),
    ("military", re.compile(r"(?<!\d)(?P<mil>(?:[01]\d|2[0-3])[0-5]\d)(?!\d)")),
    ("marked_hour", re.compile(r"(?<!\d)(?P<h>\d{1,2})\s?(?:a\.?m\.?|p\.?m\.?)(?![a-z])")),
    ("bare_hour", re.compile(r"(?<!\d)(?P<h>\d{1,2})(?:\s?o'?clock)?(?!\d)")),
    ("stray_minute", re.compile(rf"\b(?P<w>{_MINUTE_WORD})\b")),
]


def _resolve(text: str) -> list[tuple[str, re.Match[str]]]:
    found: list[tuple[int, int, str, re.Match[str]]] = []
    for kind, pattern in _CANDIDATES:
        for match in pattern.finditer(text):
            found.append((match.start(), match.end(), kind, match))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    chosen: list[tuple[str, re.Match[str]]] = []
    end_of_last = -1
    for start, end, kind, match in found:
        if start >= end_of_last:
            chosen.append((kind, match))
            end_of_last = end
    return chosen


def _hour_minute(kind: str, match: re.Match[str]) -> tuple[int, int] | None:
    if kind == "half_past":
        return _HOUR_WORDS[match.group("h")], 30
    if kind == "quarter":
        hour = _HOUR_WORDS[match.group("h")]
        if match.group("dir") == "past":
            return hour, 15
        return (hour - 1 or 12), 45
    if kind == "word":
        minute = _MINUTE_WORDS.get(match.group("m") or "", 0)
        return _HOUR_WORDS[match.group("h")], minute
    if kind in {"clock", "spaced"}:
        return int(match.group("h")), int(match.group("m"))
    if kind == "military":
        mil = match.group("mil")
        return int(mil[:2]), int(mil[2:])
    if kind in ("marked_hour", "bare_hour"):
        return int(match.group("h")), 0
    return None  # a stray minute word on its own is not a time


def normalize_time(value: Any) -> Any:
    """Turn one spoken or typed time into HH:MM.

    Handles 14:30, 03:30, 2:30 PM, 2:30pm, 3.30, 3 30, 1530, 'three thirty', 'half past three',
    'quarter to four', and 'three-thirty in the afternoon'. Returns the value unchanged when the
    text holds more than one time, corrects itself, or cannot be read.

    An explicit PM or afternoon marker adds 12 hours to hours below 12. A bare hour from 1 to 6
    with no marker means afternoon, because the clinic opens at 9.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if _CANONICAL_TIME.fullmatch(stripped):
        return stripped  # canonical 24-hour text is never reinterpreted
    text = " ".join(stripped.lower().replace(",", " ").split())
    if _CORRECTION.search(text):
        return value
    candidates = _resolve(text)
    if len(candidates) != 1:
        return value  # no time, or several: ambiguous, so do not guess
    parsed = _hour_minute(*candidates[0])
    if parsed is None:
        return value
    hour, minute = parsed
    if not (0 <= minute <= 59):
        return value
    pm = _PM.search(text) is not None
    am = _AM.search(text) is not None
    if pm and am:
        return value
    if pm and hour < 12:
        hour += 12
    elif am and hour == 12:
        hour = 0
    elif not pm and not am and 1 <= hour <= 6:
        hour += 12
    if not (0 <= hour <= 23):
        return value
    return f"{hour:02d}:{minute:02d}"


# --- dates ---------------------------------------------------------------------------------

_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ]
    )
    for m in names
}
_DATE_MONTH_FIRST = re.compile(r"^([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?$")
_DATE_DAY_FIRST = re.compile(
    r"^(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]+)\.?(?:,?\s+(\d{4}))?$"
)
_DATE_NUMERIC = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{4}))?$")


def _clinic_today() -> Date:
    return datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date()


def normalize_date(value: Any) -> Any:
    """Accept YYYY-MM-DD, 'October 23rd', '23 October 2026', and 10/23.

    A date with no year means the next time that day occurs in the clinic's timezone, so
    'October 23rd' in late October means this year.
    """
    if not isinstance(value, str):
        return value
    text = " ".join(value.strip().lower().split())
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text
    month = day = year = None
    if match := _DATE_MONTH_FIRST.match(text):
        month, day, year = _MONTHS.get(match.group(1)), int(match.group(2)), match.group(3)
    elif match := _DATE_DAY_FIRST.match(text):
        month, day, year = _MONTHS.get(match.group(2)), int(match.group(1)), match.group(3)
    elif match := _DATE_NUMERIC.match(text):
        month, day, year = int(match.group(1)), int(match.group(2)), match.group(3)
    if month is None:
        return value
    today = _clinic_today()
    try:
        candidate = Date(int(year), month, day) if year else Date(today.year, month, day)
    except ValueError:
        return value
    if not year and candidate < today:
        try:
            candidate = Date(today.year + 1, month, day)
        except ValueError:
            return value
    return candidate.isoformat()
