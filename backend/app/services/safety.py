"""Keyword screening for medical and emergency language. Errs toward escalation.

This is a demo safety net, not a clinical triage tool. A real deployment needs clinical review.
"""

from dataclasses import dataclass
from typing import Literal

EMERGENCY_TERMS = (
    "chest pain",
    "can't breathe",
    "cannot breathe",
    "trouble breathing",
    "difficulty breathing",
    "severe bleeding",
    "heavy bleeding",
    "unconscious",
    "overdose",
    "suicid",
    "choking",
    "stroke",
    "swallowed",
    "throat is swelling",
    "face is swelling",
)

MEDICAL_TERMS = (
    "diagnos",
    "symptom",
    "infection",
    "swollen",
    "swelling",
    "bleeding",
    "pain",
    "hurts",
    "medication",
    "medicine",
    "dose",
    "dosage",
    "prescription",
    "antibiotic",
    "allerg",
    "pregnan",
    "side effect",
    "is it normal",
    "should i take",
    "what should i do",
    "best treatment",
    "which treatment",
    "treatment for my",
)

HUMAN_REQUEST_TERMS = (
    "human",
    "real person",
    "staff member",
    "representative",
    "talk to someone",
    "speak to someone",
    "transfer me",
    "operator",
)


@dataclass(frozen=True)
class Screen:
    kind: Literal["emergency", "medical", "human_request", "none"]


def screen(text: str) -> Screen:
    lowered = " ".join(text.lower().split())
    if any(term in lowered for term in EMERGENCY_TERMS):
        return Screen("emergency")
    if any(term in lowered for term in MEDICAL_TERMS):
        return Screen("medical")
    if any(term in lowered for term in HUMAN_REQUEST_TERMS):
        return Screen("human_request")
    return Screen("none")
