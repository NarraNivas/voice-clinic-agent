"""Rebuild a demo database that this project created. Refuses anything else.

    cd backend && .venv/bin/python -m demo_data.reset                 # data/demo/clinic-demo.db
    cd backend && .venv/bin/python -m demo_data.reset --db PATH       # PATH must be a marked file

A file is only removed when it sits inside data/demo/ and carries the demo marker. Your own
databases, such as data/clinic.db, cannot be reset by this command.
"""

import argparse
from pathlib import Path

from demo_data.seed import DEFAULT_DB, DEMO_ROOT, check_location, is_marked, seed


def reset(path: Path = DEFAULT_DB, *, root: Path = DEMO_ROOT) -> dict[str, int]:
    target = check_location(path, root)
    if target.exists():
        if not is_marked(target):
            raise PermissionError(f"refusing to reset {target}: it is not a marked demo database")
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(f"{target}{suffix}").unlink(missing_ok=True)
    return seed(target, root=root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    counts = reset(args.db)
    print(f"reset {check_location(args.db)}")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
