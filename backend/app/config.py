"""Runtime configuration, read from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "clinic.db"
FRONTEND_DIR = REPO_DIR / "frontend"


DEFAULT_TIMEZONE = "America/Chicago"


@dataclass(frozen=True)
class Settings:
    database_path: Path
    tool_shared_secret: str | None
    elevenlabs_agent_id: str | None
    frontend_dir: Path = FRONTEND_DIR
    clinic_timezone: str = DEFAULT_TIMEZONE


def load_settings() -> Settings:
    return Settings(
        database_path=Path(os.getenv("CLINIC_DB_PATH") or DEFAULT_DB_PATH),
        tool_shared_secret=os.getenv("TOOL_SHARED_SECRET") or None,
        elevenlabs_agent_id=os.getenv("ELEVENLABS_AGENT_ID") or None,
        clinic_timezone=os.getenv("CLINIC_TIMEZONE") or DEFAULT_TIMEZONE,
    )
