"""FAQ matching over a small fictional knowledge base. Keyword phrases only."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FAQ_PATH = Path(__file__).resolve().parents[1] / "data" / "faq.json"


@dataclass(frozen=True)
class FaqEntry:
    topic: str
    keywords: tuple[str, ...]
    answer: str


@dataclass(frozen=True)
class FaqMatch:
    topic: str
    answer: str


@lru_cache(maxsize=1)
def load_entries(path: Path = FAQ_PATH) -> tuple[FaqEntry, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        FaqEntry(
            topic=item["topic"],
            keywords=tuple(keyword.lower() for keyword in item["keywords"]),
            answer=item["answer"],
        )
        for item in data["entries"]
    )


def match_faq(question: str) -> FaqMatch | None:
    """Return the entry with the most keyword phrases found in the question, or None.

    Ties go to the entry listed first. Zero matches returns None, so callers can ask a
    clarifying question instead of guessing.
    """
    text = " ".join(question.lower().split())
    best: FaqEntry | None = None
    best_score = 0
    for entry in load_entries():
        score = sum(1 for keyword in entry.keywords if keyword in text)
        if score > best_score:
            best, best_score = entry, score
    if best is None:
        return None
    return FaqMatch(topic=best.topic, answer=best.answer)
