"""Run the checks and write a report from what actually happened.

    backend/.venv/bin/python scripts/generate_report.py

It runs pytest, ruff lint, and ruff format, then writes docs/reports/latest.md. The numbers come
from the run itself: nothing is copied from an earlier report. Commands and their exit codes are
listed so the report can be checked by hand.
"""

import datetime as dt
import html
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
PYTHON = str(BACKEND / ".venv" / "bin" / "python")
REPORT = REPO / "docs" / "reports" / "latest.md"
REPORT_HTML = REPO / "docs" / "reports" / "latest.html"


def run(args: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def git_revision() -> str:
    code, out = run(["git", "rev-parse", "--short", "HEAD"], REPO)
    return out if code == 0 else "not a git checkout"


CATEGORIES = [
    (
        "Unit and API tests",
        lambda name: not name.startswith(("test_evals", "test_workflows")),
    ),
    ("Evaluation scenarios", lambda name: name.startswith("test_evals")),
    ("Workflow fixtures", lambda name: name.startswith("test_workflows")),
]


def pytest_summary(junit: Path) -> dict[str, object]:
    root = ET.parse(junit).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, 0))
    cases = []
    for case in root.iter("testcase"):
        module = (case.get("classname") or "").split(".")[-1]
        status = "passed"
        for problem in case:
            if problem.tag == "failure":
                status = "failed"
            elif problem.tag == "error":
                status = "error"
            elif problem.tag == "skipped":
                status = "skipped"
        cases.append(
            {
                "module": module,
                "name": case.get("name") or "",
                "seconds": float(case.get("time", 0)),
                "status": status,
            }
        )
    categories = []
    for label, belongs in CATEGORIES:
        members = [c for c in cases if belongs(c["module"])]
        categories.append(
            {
                "label": label,
                "total": len(members),
                "passed": sum(1 for c in members if c["status"] == "passed"),
            }
        )
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    return {
        **totals,
        "passed": passed,
        "cases": cases,
        "categories": categories,
        "failed_names": [
            f"{c['module']}::{c['name']}" for c in cases if c["status"] in ("failed", "error")
        ],
        "slowest": sorted(
            ((c["seconds"], f"{c['module']}::{c['name']}") for c in cases), reverse=True
        )[:8],
    }


TEMPLATE = REPO / "scripts" / "report_template.html"


def _tile(label: str, value: object) -> str:
    value_text, label_text = html.escape(str(value)), html.escape(label)
    return f'<div class="tile"><b>{value_text}</b><span>{label_text}</span></div>'


def build_html(
    stamp: str,
    revision: str,
    results: list[tuple[str, int, str]],
    summary: dict[str, object] | None,
) -> str:
    esc = html.escape
    checks = "".join(
        f'<tr><td>{esc(label)}</td><td class="{"ok" if code == 0 else "bad"}">'
        f"{'pass' if code == 0 else 'fail'}</td><td>{last_line}</td></tr>"
        for label, code, output in results
        for last_line in [esc(output.splitlines()[-1] if output else "")]
    )
    if summary:
        tiles = "".join(
            _tile(label, value)
            for label, value in [
                ("Passed", summary["passed"]),
                (
                    "Failed or errored",
                    int(summary["failures"]) + int(summary["errors"]),
                ),
                ("Skipped", summary["skipped"]),
                ("Collected", summary["tests"]),
            ]
        )
        categories = "".join(
            f'<tr><td>{esc(c["label"])}</td><td class="num">{c["passed"]} / {c["total"]}</td></tr>'
            for c in summary["categories"]
        )
        longest = max((seconds for seconds, _ in summary["slowest"]), default=1.0) or 1.0
        slowest = "".join(
            f'<li><span class="bar" style="width:{100 * seconds / longest:.0f}%"></span>'
            f'<code>{esc(name)}</code><span class="secs">{seconds:.2f}s</span></li>'
            for seconds, name in summary["slowest"]
        )
        failed = (
            '<p class="bad">Failing: ' + ", ".join(esc(n) for n in summary["failed_names"]) + "</p>"
            if summary["failed_names"]
            else '<p class="ok">No failing tests in this run.</p>'
        )
    else:
        tiles, categories, slowest = "", "", ""
        failed = '<p class="bad">pytest did not produce results.</p>'
    template = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "{{STAMP}}": esc(stamp),
        "{{REVISION}}": esc(revision),
        "{{TILES}}": tiles,
        "{{CHECKS}}": checks,
        "{{CATEGORIES}}": categories,
        "{{SLOWEST}}": slowest,
        "{{FAILED}}": failed,
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template


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
    REPORT_HTML.write_text(build_html(stamp, git_revision(), results, summary), encoding="utf-8")
    print(f"wrote {REPORT.relative_to(REPO)} and {REPORT_HTML.relative_to(REPO)}")
    for label, code, _ in results:
        print(f"  {label}: exit {code}")
    return 0 if all(code == 0 for _, code, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
