"""Phase 6 integration tests for the sync engine scanner."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from local_api import config
from local_api.database import get_db, init_db, reset_db
from local_api.services.sync_log_service import create_sync_log, list_sync_logs
from local_api.services.sync_state_service import (
    create_sync_state,
    get_sync_state,
    transition_sync_state,
)
from local_api.sync_engine import ScanResult, SyncEngine


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    reset_db()
    init_db()
    monkeypatch.setattr(config, "SYNC_JITTER_ENABLED", False)
    monkeypatch.setattr(config, "SYNC_BATCH_SIZE", 10)
    monkeypatch.setattr(config, "SYNC_TIMEOUT_SECONDS", 300)
    monkeypatch.setattr(config, "SYNC_SCAN_INTERVAL", 1)
    yield
    reset_db()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _insert_task(task_id: str) -> None:
    conn = get_db()
    now = _iso(_now())
    conn.execute(
        """INSERT INTO tasks (
            task_id, title, status, priority, created_channel, created_at, updated_at
        ) VALUES (?, ?, 'pending', 'P2', 'api_test', ?, ?)""",
        (task_id, f"Task {task_id}", now, now),
    )
    conn.commit()


def _sync(
    task_id: str,
    *,
    status: str = "pending",
    target: str = "apple_calendar",
) -> dict:
    _insert_task(task_id)
    return create_sync_state(task_id=task_id, sync_target=target, sync_status=status)


def _set_updated_at(sync_id: str, dt: datetime) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE sync_state SET updated_at = ? WHERE sync_id = ?",
        (_iso(dt), sync_id),
    )
    conn.commit()


def _logs(sync_id: str) -> list[dict]:
    records, _ = list_sync_logs(sync_id=sync_id)
    return records


def test_empty_scan_returns_all_zeroes():
    result = SyncEngine().scan_once()

    assert result == ScanResult()
    assert result.errors == []


def test_pick_pending_promotes_to_in_progress_without_log():
    sync = _sync("task_engine_pending")

    result = SyncEngine().scan_once()

    assert result.pending_picked == 1
    assert get_sync_state(sync["sync_id"])["sync_status"] == "in_progress"
    assert _logs(sync["sync_id"]) == []


def test_retry_failed_after_backoff_promotes_without_log():
    sync = _sync("task_engine_retry", status="failed")
    create_sync_log(
        sync_id=sync["sync_id"],
        local_task_id=sync["task_id"],
        sync_target=sync["sync_target"],
        sync_attempt=1,
        sync_result="failed",
        error_code="network",
        triggered_by="test",
    )
    conn = get_db()
    conn.execute(
        "UPDATE sync_logs SET created_at = ? WHERE sync_id = ?",
        (_iso(_now() - timedelta(seconds=31)), sync["sync_id"]),
    )
    conn.commit()

    result = SyncEngine().scan_once()

    assert result.retry_triggered == 1
    assert get_sync_state(sync["sync_id"])["sync_status"] == "in_progress"
    assert len(_logs(sync["sync_id"])) == 1


def test_no_retry_before_backoff_expires():
    sync = _sync("task_engine_no_retry", status="failed")
    create_sync_log(
        sync_id=sync["sync_id"],
        local_task_id=sync["task_id"],
        sync_target=sync["sync_target"],
        sync_attempt=1,
        sync_result="failed",
        error_code="network",
        triggered_by="test",
    )

    result = SyncEngine().scan_once()

    assert result.retry_triggered == 0
    assert get_sync_state(sync["sync_id"])["sync_status"] == "failed"
    assert len(_logs(sync["sync_id"])) == 1


def test_timeout_first_attempt_goes_failed_and_logs_attempt_1():
    sync = _sync("task_engine_timeout_1", status="in_progress")
    _set_updated_at(sync["sync_id"], _now() - timedelta(seconds=301))

    result = SyncEngine().scan_once()

    assert result.timeout_detected == 1
    assert result.failed == 1
    assert get_sync_state(sync["sync_id"])["sync_status"] == "failed"
    logs = _logs(sync["sync_id"])
    assert len(logs) == 1
    assert logs[0]["sync_result"] == "failed"
    assert logs[0]["error_code"] == "timeout"
    assert logs[0]["sync_attempt"] == 1


def test_timeout_fourth_attempt_goes_failed_permanent_and_logs_attempt_4():
    sync = _sync("task_engine_timeout_4", status="in_progress")
    for attempt in (1, 2, 3):
        create_sync_log(
            sync_id=sync["sync_id"],
            local_task_id=sync["task_id"],
            sync_target=sync["sync_target"],
            sync_attempt=attempt,
            sync_result="failed",
            error_code="network",
            triggered_by="test",
        )
    _set_updated_at(sync["sync_id"], _now() - timedelta(seconds=301))

    result = SyncEngine().scan_once()

    assert result.timeout_detected == 1
    assert get_sync_state(sync["sync_id"])["sync_status"] == "failed_permanent"
    logs = _logs(sync["sync_id"])
    assert len(logs) == 4
    timeout_log = [log for log in logs if log["error_code"] == "timeout"][0]
    assert timeout_log["sync_attempt"] == 4
    assert timeout_log["sync_result"] == "failed"


def test_full_cycle_pending_to_synced_with_mock_completion_log():
    sync = _sync("task_engine_full_cycle")

    result = SyncEngine().scan_once()
    assert result.pending_picked == 1
    assert get_sync_state(sync["sync_id"])["sync_status"] == "in_progress"

    transition_sync_state(sync["sync_id"], "synced", trigger="engine")
    create_sync_log(
        sync_id=sync["sync_id"],
        local_task_id=sync["task_id"],
        sync_target=sync["sync_target"],
        sync_attempt=1,
        sync_result="success",
        triggered_by="test",
    )

    assert get_sync_state(sync["sync_id"])["sync_status"] == "synced"
    logs = _logs(sync["sync_id"])
    assert len(logs) == 1
    assert logs[0]["sync_result"] == "success"
    assert logs[0]["sync_attempt"] == 1


def test_unretryable_error_goes_failed_permanent_with_log_attempt():
    sync = _sync("task_engine_unretryable", status="in_progress")

    transition_sync_state(sync["sync_id"], "failed_permanent", trigger="engine")
    create_sync_log(
        sync_id=sync["sync_id"],
        local_task_id=sync["task_id"],
        sync_target=sync["sync_target"],
        sync_attempt=1,
        sync_result="failed",
        error_code="auth_failed",
        triggered_by="test",
    )

    assert get_sync_state(sync["sync_id"])["sync_status"] == "failed_permanent"
    logs = _logs(sync["sync_id"])
    assert len(logs) == 1
    assert logs[0]["error_code"] == "auth_failed"


def test_retry_cap_failed_attempt_4_goes_failed_permanent_and_logs():
    sync = _sync("task_engine_retry_cap", status="failed")
    create_sync_log(
        sync_id=sync["sync_id"],
        local_task_id=sync["task_id"],
        sync_target=sync["sync_target"],
        sync_attempt=4,
        sync_result="failed",
        error_code="network",
        triggered_by="test",
    )

    result = SyncEngine().scan_once()

    assert result.failed == 1
    assert get_sync_state(sync["sync_id"])["sync_status"] == "failed_permanent"
    logs = _logs(sync["sync_id"])
    assert len(logs) == 2
    retry_cap_log = [log for log in logs if log["error_code"] == "retry_cap"][0]
    assert retry_cap_log["sync_attempt"] == 4
    assert retry_cap_log["sync_result"] == "failed"


def test_stale_promotes_to_pending_without_log():
    sync = _sync("task_engine_stale", status="stale")

    result = SyncEngine().scan_once()

    assert result.stale_triggered == 1
    assert get_sync_state(sync["sync_id"])["sync_status"] == "pending"
    assert _logs(sync["sync_id"]) == []


def test_timeout_priority_beats_pending_in_same_cycle():
    timed_out = _sync("task_engine_priority_timeout", status="in_progress")
    pending = _sync("task_engine_priority_pending")
    _set_updated_at(timed_out["sync_id"], _now() - timedelta(seconds=301))

    result = SyncEngine().scan_once()

    assert result.timeout_detected == 1
    assert result.pending_picked == 0
    assert get_sync_state(timed_out["sync_id"])["sync_status"] == "failed"
    assert get_sync_state(pending["sync_id"])["sync_status"] == "pending"


def test_start_stop_lifecycle():
    engine = SyncEngine()

    engine.start()
    assert engine.is_running

    engine.stop()
    assert not engine.is_running
