"""The seeded demo data: named fixtures, determinism, and the rules that protect other databases."""

import sqlite3
from datetime import timedelta

import pytest
from app.config import DEFAULT_DB_PATH
from demo_data.reset import reset
from demo_data.seed import BASE_DATE, FIXTURES, TOTAL_BOOKINGS, check_location, is_marked, seed


@pytest.fixture
def demo_root(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    return root


@pytest.fixture
def seeded(demo_root):
    path = demo_root / "clinic-demo.db"
    seed(path, root=demo_root)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def scalar(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def test_counts_match_the_plan(seeded):
    assert scalar(seeded, "SELECT COUNT(*) FROM customers") == 30
    assert scalar(seeded, "SELECT COUNT(*) FROM providers") == 2
    assert scalar(seeded, "SELECT COUNT(*) FROM appointments") == TOTAL_BOOKINGS
    assert scalar(seeded, "SELECT COUNT(*) FROM appointments WHERE status = 'cancelled'") >= 8


def test_fixture_full_morning_for_provider_one(seeded):
    day = (BASE_DATE + timedelta(days=2)).isoformat()
    morning = scalar(
        seeded,
        "SELECT COUNT(*) FROM appointments WHERE provider_id = 1 AND status = 'booked' "
        "AND date(starts_at) = ? AND time(starts_at) < '13:00'",
        day,
    )
    assert morning == 8, FIXTURES["full_morning_provider_1"]


def test_fixture_provider_two_closed_with_no_bookings(seeded):
    closed = (BASE_DATE + timedelta(days=4)).isoformat()
    assert (
        scalar(
            seeded,
            "SELECT COUNT(*) FROM provider_closures WHERE provider_id = 2 AND day = ?",
            closed,
        )
        == 1
    )
    assert (
        scalar(
            seeded,
            "SELECT COUNT(*) FROM appointments WHERE provider_id = 2 AND date(starts_at) = ?",
            closed,
        )
        == 0
    )


def test_fixture_notice_window_request_is_queued(seeded):
    reasons = {
        row["reason"]: row["status"]
        for row in seeded.execute("SELECT reason, status FROM staff_requests")
    }
    assert reasons["change_too_late"] == "resolved", FIXTURES["notice_window_change"]


def test_fixture_similar_names_keep_separate_bookings(seeded):
    rows = seeded.execute(
        "SELECT c.full_name, a.confirmation_code FROM appointments a "
        "JOIN customers c ON c.id = a.customer_id WHERE c.full_name LIKE 'Maria Lop%'"
    ).fetchall()
    assert {row["full_name"] for row in rows} == {"Maria Lopez", "Maria Lopes"}, FIXTURES[
        "similar_names"
    ]
    assert len({row["confirmation_code"] for row in rows}) == len(rows)


def test_fixture_new_callers_have_no_customer_record(seeded):
    assert scalar(seeded, "SELECT COUNT(*) FROM appointments WHERE customer_id IS NULL") == 4, (
        FIXTURES["new_caller"]
    )


def test_fixture_cancelled_history_frees_the_slot(seeded):
    cancelled = seeded.execute(
        "SELECT provider_id, starts_at FROM appointments WHERE status = 'cancelled'"
    ).fetchall()
    assert len(cancelled) >= 8, FIXTURES["cancelled_history"]
    for row in cancelled:
        clash = scalar(
            seeded,
            "SELECT COUNT(*) FROM appointments "
            "WHERE status = 'booked' AND provider_id = ? AND starts_at = ?",
            row["provider_id"],
            row["starts_at"],
        )
        assert clash <= 1  # a cancelled slot may be rebooked, but never double-booked


def test_fixture_staff_queue_has_each_state(seeded):
    states = {row["status"] for row in seeded.execute("SELECT status FROM staff_requests")}
    assert states >= {"open", "in_progress", "resolved"}, FIXTURES["staff_states"]


def test_the_same_seed_gives_the_same_schedule(demo_root, tmp_path):
    other_root = tmp_path / "other"
    other_root.mkdir()
    seed(demo_root / "a.db", root=demo_root)
    seed(other_root / "b.db", root=other_root)

    def schedule(path):
        conn = sqlite3.connect(path)
        try:
            return conn.execute(
                "SELECT patient_name, starts_at, provider_id, status FROM appointments "
                "ORDER BY starts_at, provider_id, patient_name"
            ).fetchall()
        finally:
            conn.close()

    assert schedule(demo_root / "a.db") == schedule(other_root / "b.db")


def test_seed_refuses_a_file_outside_the_demo_folder(tmp_path, demo_root):
    with pytest.raises(ValueError, match="refusing"):
        seed(tmp_path / "elsewhere.db", root=demo_root)


def test_seed_refuses_a_non_database_name(demo_root):
    with pytest.raises(ValueError, match="refusing"):
        check_location(demo_root / "notes.txt", demo_root)


def test_seed_refuses_to_overwrite_an_existing_file(demo_root):
    seed(demo_root / "once.db", root=demo_root)
    with pytest.raises(FileExistsError):
        seed(demo_root / "once.db", root=demo_root)


def test_reset_refuses_an_unmarked_file(demo_root):
    unmarked = demo_root / "mine.db"
    sqlite3.connect(unmarked).execute("CREATE TABLE keep_me (x INTEGER)").connection.commit()
    assert not is_marked(unmarked)
    with pytest.raises(PermissionError):
        reset(unmarked, root=demo_root)
    assert unmarked.exists()


def test_reset_rebuilds_a_marked_file(demo_root):
    path = demo_root / "again.db"
    seed(path, root=demo_root)
    counts = reset(path, root=demo_root)
    assert counts["bookings"] == TOTAL_BOOKINGS
    assert is_marked(path)


def test_the_real_clinic_database_is_never_a_reset_target():
    with pytest.raises(ValueError, match="refusing"):
        check_location(DEFAULT_DB_PATH)
