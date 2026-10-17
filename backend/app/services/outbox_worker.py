"""Command-line worker: delivers queued staff handoffs to a CRM sandbox once per run.

    cd backend && .venv/bin/python -m app.services.outbox_worker --db PATH --crm http://127.0.0.1:8100

Run it again to try the queued handoffs that are due. It prints one line per handoff and never
prints request content.
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

from app.db import connect
from app.services.clinic_rules import clinic_now
from app.services.outbox import HttpCrmClient, deliver_due

log = logging.getLogger("clinic.outbox")


def run_once(db: Path, crm_url: str, *, now: datetime | None = None) -> list[str]:
    conn = connect(db)
    try:
        results = deliver_due(conn, HttpCrmClient(crm_url), now=now or clinic_now())
    finally:
        conn.close()
    lines = [
        f"{result.request_id[:8]}  {result.outcome:<9}  attempts={result.attempts}"
        + (f"  error={result.error}" if result.error else "")
        for result in results
    ]
    for line in lines:
        log.info(line)
    return lines


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument(
        "--crm",
        required=True,
        help="base URL of the CRM sandbox, for example http://127.0.0.1:8100",
    )
    parser.add_argument(
        "--at",
        type=datetime.fromisoformat,
        help="run as if it were this time, e.g. 2026-10-19T08:00",
    )
    args = parser.parse_args()
    lines = run_once(args.db, args.crm, now=args.at)
    if not lines:
        print("nothing due")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
