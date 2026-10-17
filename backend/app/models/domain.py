"""Domain objects used by services and repositories. No HTTP concerns here."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Appointment:
    id: int
    confirmation_code: str
    patient_name: str
    appointment_type: str
    starts_at: datetime
    duration_minutes: int
    status: str
    idempotency_key: str | None

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_minutes)
