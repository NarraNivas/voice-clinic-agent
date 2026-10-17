"""Input normalization for the HTTP boundary.

Voice agents and people write dates and times in many ways. These functions turn common forms
into the strict values the API stores: YYYY-MM-DD, 24-hour HH:MM, and one of three appointment
types. Anything that cannot be read is returned unchanged, so Pydantic validation can reject it
and name the field. The functions never raise and never log the input.
"""

import re
from datetime import date as Date
from typing import Any

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
_MINUTE_WORDS = {
    "thirty": 30,
    "fifteen": 15,
    "forty five": 45,
    "forty-five": 45,
    "twenty": 20,
    "ten": 10,
    "five": 5,
}
_PM_MARKERS = re.compile(r"\b(p\.?\s?m\.?|afternoon|evening|tonight)\b")
_AM_MARKERS = re.compile(r"\b(a\.?\s?m\.?|morning)\b")


def _extract_hour_minute(text: str) -> tuple[int, int] | None:
    """Find an hour and minute in free text: digits, military time, or spoken number words."""
    if match := re.search(r"(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)", text):
        return int(match.group(1)), int(match.group(2))
    if match := re.search(r"(?<!\d)(\d{1,2})\s+(\d{2})(?!\d)", text):
        return int(match.group(1)), int(match.group(2))
    military = re.search(r"(?<!\d)([01]?\d|2[0-3])([0-5]\d)(?!\d)", text)
    if military and len(military.group(0)) == 4:
        return int(military.group(1)), int(military.group(2))
    words = "|".join(sorted(_HOUR_WORDS, key=len, reverse=True))
    minutes = "|".join(sorted(_MINUTE_WORDS, key=len, reverse=True))
    if match := re.search(rf"\bhalf past ({words})\b", text):
        return _HOUR_WORDS[match.group(1)], 30
    if match := re.search(rf"\bquarter past ({words})\b", text):
        return _HOUR_WORDS[match.group(1)], 15
    if match := re.search(rf"\bquarter to ({words})\b", text):
        return _HOUR_WORDS[match.group(1)] - 1 or 12, 45
    if match := re.search(rf"\b({words})(?:[\s-]+({minutes}))?\b", text):
        minute = _MINUTE_WORDS.get(match.group(2) or "", 0)
        return _HOUR_WORDS[match.group(1)], minute
    if match := re.search(r"(?<!\d)(\d{1,2})(?!\d)", text):
        return int(match.group(1)), 0
    return None


def normalize_time(value: Any) -> Any:
    """Turn a spoken or typed time into HH:MM. Handles 14:30, 2:30 PM, 3.30, 3 30, 1530,
    'three thirty', 'half past three', 'three-thirty in the afternoon', and 'PM EST'.

    Rules: an explicit PM or afternoon marker adds 12 hours to hours below 12. A bare hour
    from 1 to 6 with no marker means afternoon, since the clinic opens at 9. Anything that
    cannot be read is returned unchanged so validation can name the field.
    """
    if not isinstance(value, str):
        return value
    text = " ".join(value.lower().replace(",", " ").split())
    found = _extract_hour_minute(text)
    if found is None:
        return value
    hour, minute = found
    if not (0 <= minute <= 59):
        return value
    if _PM_MARKERS.search(text) and hour < 12:
        hour += 12
    elif _AM_MARKERS.search(text):
        if hour == 12:
            hour = 0
    elif 1 <= hour <= 6:
        hour += 12
    if not (0 <= hour <= 23):
        return value
    return f"{hour:02d}:{minute:02d}"


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


def normalize_date(value: Any) -> Any:
    """Accept YYYY-MM-DD, 'October 23rd', '23 October 2026', and 10/23. A date with no year
    means the next time that day occurs, so 'October 23rd' in late October means this year."""
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
    today = Date.today()
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
