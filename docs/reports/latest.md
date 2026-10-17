# Test report

Generated 2026-10-17 21:13 UTC from revision `6272d2c`.

## Results

| Check | Exit code | Outcome |
|---|---|---|
| `pytest` | 0 | 294 passed, 1 warning in 9.68s |
| `ruff check` | 0 | All checks passed! |
| `ruff format --check` | 0 | 65 files already formatted |

pytest: 294 passed, 0 failed, 0 errors, 0 skipped, of 294 collected.

Five slowest tests:

- 0.564s `tests.test_crm_recovery::test_recovery_creates_exactly_one_case_and_delivers_once`
- 0.535s `tests.test_crm_recovery::test_the_worker_saw_each_failure_mode_on_the_way`
- 0.446s `tests.test_demo_data::test_fixture_full_morning_for_provider_one`
- 0.439s `tests.test_demo_data::test_reset_rebuilds_a_marked_file`
- 0.433s `tests.test_crm_recovery::test_the_caller_is_told_the_request_is_queued_not_delivered`

## Scope

Deterministic contract checks, the curated workflow fixtures in `evals/workflows.json`, and the offline recovery journey. Workflow fixtures are synthetic regression cases. No live voice call is part of this report, and no speech or model quality is measured.
