"""Acceptance: the recovery journey over real localhost HTTP, clinic to CRM sandbox.

The same run is available as a command: `python -m crm_sandbox.journey`.
"""

from crm_sandbox.journey import run


def test_recovery_creates_exactly_one_case_and_delivers_once():
    report = run(verbose=False)

    assert report["cases_in_crm"] == 1
    assert report["final_counts"] == {"queued": 0, "delivered": 1, "failed": 0}
    assert report["attempts"] == [4]


def test_the_caller_is_told_the_request_is_queued_not_delivered():
    report = run(verbose=False)

    message = report["refusal_message"]
    assert "queued" in message
    assert "not delivered until that system accepts it" in message
    assert "delivered." not in message.replace("not delivered", "")


def test_the_worker_saw_each_failure_mode_on_the_way():
    report = run(verbose=False)

    outcomes = report["outcomes"]
    # Two outages, then a lost response, then the recovered delivery.
    assert outcomes == ["retry", "retry", "retry", "delivered"]
