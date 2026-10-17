"""Run the checks and write a report from what actually happened.

    backend/.venv/bin/python scripts/generate_report.py

It runs pytest, ruff lint, and ruff format, then writes docs/reports/latest.md. The numbers come
from the run itself: nothing is copied from an earlier report. Commands and their exit codes are
listed so the report can be checked by hand.
"""

import datetime as dt
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
PYTHON = str(BACKEND / ".venv" / "bin" / "python")
REPORT = REPO / "docs" / "reports" / "latest.md"


def run(args: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def git_revision() -> str:
    code, out = run(["git", "rev-parse", "--short", "HEAD"], REPO)
    return out if code == 0 else "not a git checkout"


def pytest_summary(junit: Path) -> dict[str, object]:
    root = ET.parse(junit).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    failures: list[str] = []
    slowest: list[tuple[float, str]] = []
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, 0))
    for case in root.iter("testcase"):
        name = f"{case.get('classname')}::{case.get('name')}"
        slowest.append((float(case.get("time", 0)), name))
        for problem in list(case):
            if problem.tag in ("failure", "error"):
                failures.append(name)
    slowest.sort(reverse=True)
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    return {
        **totals,
        "passed": passed,
        "failed_names": failures,
        "slowest": slowest[:5],
    }


def main() -> int:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    with tempfile.TemporaryDirectory() as scratch:
        junit = Path(scratch) / "junit.xml"
        pytest_cmd = [PYTHON, "-m", "pytest", "-q", f"--junitxml={junit}"]
        commands = [
            ("pytest", pytest_cmd),
            (
                "ruff check",
                [
                    PYTHON,
                    "-m",
                    "ruff",
                    "check",
                    ".",
                    "../scripts",
                    "--config",
                    "pyproject.toml",
                ],
            ),
            (
                "ruff format --check",
                [
                    PYTHON,
                    "-m",
                    "ruff",
                    "format",
                    "--check",
                    ".",
                    "../scripts",
                    "--config",
                    "pyproject.toml",
                ],
            ),
        ]
        results = []
        for label, command in commands:
            code, output = run(command, BACKEND)
            results.append((label, code, output))
        summary = pytest_summary(junit) if junit.exists() else None

    lines = [
        "# Test report",
        "",
        f"Generated {stamp} from revision `{git_revision()}`.",
        "",
        "## Results",
        "",
        "| Check | Exit code | Outcome |",
        "|---|---|---|",
    ]
    for label, code, output in results:
        outcome = output.splitlines()[-1] if output else ""
        lines.append(f"| `{label}` | {code} | {outcome} |")
    if summary:
        lines += [
            "",
            f"pytest: {summary['passed']} passed, {summary['failures']} failed, "
            f"{summary['errors']} errors, {summary['skipped']} skipped, "
            f"of {summary['tests']} collected.",
            "",
            "Five slowest tests:",
            "",
        ]
        lines += [f"- {seconds:.3f}s `{name}`" for seconds, name in summary["slowest"]]
        if summary["failed_names"]:
            lines += ["", "Failed:", ""] + [f"- `{name}`" for name in summary["failed_names"]]
    lines += [
        "",
        "## Scope",
        "",
        "Deterministic contract checks, the curated workflow fixtures in `evals/workflows.json`, "
        "and the offline recovery journey. Workflow fixtures are synthetic regression cases. "
        "No live voice call is part of this report, and no speech or model quality is measured.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT.relative_to(REPO)}")
    for label, code, _ in results:
        print(f"  {label}: exit {code}")
    return 0 if all(code == 0 for _, code, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
