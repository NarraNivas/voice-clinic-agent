# Test report

Generated 2026-10-17 21:22 UTC from revision `10a31ed`.

## Results

| Check | Exit code | Outcome |
|---|---|---|
| `pytest` | 0 | 294 passed, 1 warning in 5.83s |
| `ruff check` | 0 | All checks passed! |
| `ruff format --check` | 0 | 65 files already formatted |

pytest: 294 passed, 0 failed, 0 errors, 0 skipped, of 294 collected.

Five slowest tests:

- 0.426s `test_crm_recovery::test_the_worker_saw_each_failure_mode_on_the_way`
- 0.423s `test_crm_recovery::test_recovery_creates_exactly_one_case_and_delivers_once`
- 0.422s `test_crm_recovery::test_the_caller_is_told_the_request_is_queued_not_delivered`
- 0.367s `test_demo_data::test_the_same_seed_gives_the_same_schedule`
- 0.307s `test_demo_data::test_reset_rebuilds_a_marked_file`
- 0.203s `test_demo_data::test_fixture_staff_queue_has_each_state`
- 0.194s `test_demo_data::test_counts_match_the_plan`
- 0.189s `test_demo_data::test_fixture_notice_window_request_is_queued`

## Scope

Deterministic contract checks, the curated workflow fixtures in `evals/workflows.json`, and the offline recovery journey. Workflow fixtures are synthetic regression cases. No live voice call is part of this report, and no speech or model quality is measured.
