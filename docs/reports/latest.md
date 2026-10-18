# Test report

Generated 2026-10-18 18:52 UTC from revision `bebe826`.

## Results

| Check | Exit code | Outcome |
|---|---|---|
| `pytest` | 0 | 301 passed, 1 warning in 12.05s |
| `ruff check` | 0 | All checks passed! |
| `ruff format --check` | 0 | 68 files already formatted |

pytest: 301 passed, 0 failed, 0 errors, 0 skipped, of 301 collected.

Five slowest tests:

- 2.390s `test_demo_data::test_fixture_similar_names_keep_separate_bookings`
- 0.647s `test_demo_data::test_fixture_staff_queue_has_each_state`
- 0.640s `test_demo_data::test_reset_rebuilds_a_marked_file`
- 0.578s `test_demo_data::test_the_same_seed_gives_the_same_schedule`
- 0.480s `test_demo_data::test_fixture_provider_two_closed_with_no_bookings`
- 0.442s `test_crm_recovery::test_the_worker_saw_each_failure_mode_on_the_way`
- 0.439s `test_demo_data::test_fixture_new_callers_have_no_customer_record`
- 0.430s `test_crm_recovery::test_recovery_creates_exactly_one_case_and_delivers_once`

## Scope

Deterministic contract checks, the curated workflow fixtures in `evals/workflows.json`, and the offline recovery journey. Workflow fixtures are synthetic regression cases. No live voice call is part of this report, and no speech or model quality is measured.
