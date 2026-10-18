# Test report

Generated 2026-10-18 19:14 UTC from revision `9fd1655`.

## Results

| Check | Exit code | Outcome |
|---|---|---|
| `pytest` | 0 | 307 passed, 1 warning in 6.34s |
| `ruff check` | 0 | All checks passed! |
| `ruff format --check` | 0 | 69 files already formatted |

pytest: 307 passed, 0 failed, 0 errors, 0 skipped, of 307 collected.

Five slowest tests:

- 0.428s `test_crm_recovery::test_recovery_creates_exactly_one_case_and_delivers_once`
- 0.423s `test_crm_recovery::test_the_caller_is_told_the_request_is_queued_not_delivered`
- 0.421s `test_crm_recovery::test_the_worker_saw_each_failure_mode_on_the_way`
- 0.331s `test_demo_data::test_the_same_seed_gives_the_same_schedule`
- 0.315s `test_demo_data::test_reset_rebuilds_a_marked_file`
- 0.211s `test_demo_data::test_counts_match_the_plan`
- 0.184s `test_demo_data::test_fixture_full_morning_for_provider_one`
- 0.182s `test_demo_data::test_fixture_staff_queue_has_each_state`

## Scope

Deterministic contract checks, the curated workflow fixtures in `evals/workflows.json`, and the offline recovery journey. Workflow fixtures are synthetic regression cases. No live voice call is part of this report, and no speech or model quality is measured.
