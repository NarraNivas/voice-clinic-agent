"""Run the CRM sandbox on localhost.

    cd backend && .venv/bin/python -m crm_sandbox --db data/demo/crm-demo.db --port 8011 [--faults]

It is a simulator with its own database. Fault injection is available only with --faults.
"""

import argparse
from pathlib import Path

import uvicorn

from crm_sandbox.app import create_crm_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Local CRM sandbox (simulator).")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--faults", action="store_true", help="enable fault injection endpoints")
    args = parser.parse_args()
    app = create_crm_app(args.db, faults_enabled=args.faults)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
