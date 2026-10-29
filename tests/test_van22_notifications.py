"""VAN-22: all transports are mocked and databases come from tmp_path."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from adapters.dingtalk import DingTalkAdapter


PLAN = {"id": 1, "title": "训练", "date": "2026-10-23", "items": []}


@pytest.mark.parametrize("body", [
    '{"errcode":310000,"errmsg":"invalid token"}', "null", "[]", "{}",
    "bad-json", '{"errcode":"0"}', '{"errcode":false}',
])
def test_reminder_requires_valid_business_ack(body):
    adapter = DingTalkAdapter(webhook_url="https://mock.invalid", post_func=lambda *a, **k: (200, body))
    result = adapter.send_reminder(PLAN)
    assert result["status"] == "failed"
    assert result["sent"] is False


def test_reminder_accepts_explicit_success_ack():
    adapter = DingTalkAdapter(webhook_url="https://mock.invalid", post_func=lambda *a, **k: (200, '{"errcode":0,"errmsg":"ok"}'))
    assert adapter.send_reminder(PLAN)["sent"] is True


@pytest.mark.parametrize("body", [
    '{"code":"InvalidParameter","message":"bad request"}', "null", "[]", "{}",
    "bad-json", '{"id":null}', '{"id":false}', '{"taskId":false}',
    '{"task":{"id":"todo-1"}}', '{"id":"todo-1","errcode":500}',
    '{"taskId":"todo-1","code":"Failed"}', '{"id":"todo-1","code":[]}',
    '{"id":"todo-1","errcode":false}',
])
def test_todo_requires_valid_business_ack(body):
    adapter = DingTalkAdapter(todo_url="https://mock.invalid", access_token="fake", post_func=lambda *a, **k: (200, body))
    result = adapter.create_todo(PLAN)
    assert result["status"] == "failed"
    assert result["created"] is False


@pytest.mark.parametrize("id_field", ["id", "taskId"])
def test_todo_accepts_explicit_success_ack(id_field):
    adapter = DingTalkAdapter(todo_url="https://mock.invalid", access_token="fake", post_func=lambda *a, **k: (200, json.dumps({id_field: "todo-1"})))
    assert adapter.create_todo(PLAN)["created"] is True


@pytest.mark.parametrize("http_status", [400, 500])
def test_http_failure_is_not_business_success(http_status):
    adapter = DingTalkAdapter(
        webhook_url="https://mock.invalid", todo_url="https://mock.invalid", access_token="fake",
        post_func=lambda *a, **k: (http_status, '{"errcode":0,"id":"todo-1"}'),
    )
    assert adapter.send_reminder(PLAN)["sent"] is False
    assert adapter.create_todo(PLAN)["created"] is False


@pytest.mark.parametrize("reminder_ok,todo_ok,expected", [
    (True, True, "sent"), (True, False, "partial_success"),
    (False, True, "partial_success"), (False, False, "failed"),
])
def test_api_delivery_status_and_retry_dedup(app_modules, monkeypatch, reminder_ok, todo_ok, expected):
    database, main = app_modules
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    calls = []
    state = {"reminder": reminder_ok, "todo": todo_ok}
    def post(url, payload, headers=None):
        channel = "reminder" if url.endswith("/reminder") else "todo"
        calls.append(channel)
        body = {"errcode": 0 if state[channel] else 500} if channel == "reminder" else (
            {"id": "todo-1"} if state[channel] else {"code": "Failed"}
        )
        return 200, json.dumps(body)
    monkeypatch.setenv("DINGTALK_WEBHOOK_URL", "https://mock.invalid/reminder")
    monkeypatch.setenv("DINGTALK_TODO_CREATE_URL", "https://mock.invalid/todo")
    monkeypatch.setenv("DINGTALK_ACCESS_TOKEN", "fake")
    monkeypatch.setattr(DingTalkAdapter, "_post_json", staticmethod(post))
    with database.SessionLocal() as db:
        plan = db.query(database.WorkoutPlan).filter(database.WorkoutPlan.is_training_day == True).first()
        plan_id = plan.id
        db.query(database.Reminder).delete()
        db.commit()
    first = client.post("/api/notifications/send", json={"plan_id": plan_id}).json()
    assert first["status"] == expected
    assert first["sent"] is (reminder_ok and todo_ok)
    with database.SessionLocal() as db:
        assert db.query(database.Reminder).filter_by(is_active=True).count() == int(reminder_ok) + int(todo_ok)
    state.update(reminder=True, todo=True)
    second = client.post("/api/notifications/send", json={"plan_id": plan_id}).json()
    assert second["status"] == ("duplicate_skipped" if expected == "sent" else "sent")
    assert len(calls) == 4 - int(reminder_ok) - int(todo_ok)
    third = client.post("/api/notifications/send", json={"plan_id": plan_id}).json()
    assert third["status"] == "duplicate_skipped"


def test_not_configured_is_not_deduplicated(client, app_modules):
    database, _main = app_modules
    with database.SessionLocal() as db:
        plan_id = db.query(database.WorkoutPlan).filter(database.WorkoutPlan.is_training_day == True).first().id
    for _ in range(2):
        result = client.post("/api/notifications/send", json={"plan_id": plan_id}).json()
        assert result["status"] == "not_configured"
        assert result["sent"] is False


def test_reminder_only_request_does_not_require_todo(client, app_modules, monkeypatch):
    database, _main = app_modules
    monkeypatch.setenv("DINGTALK_WEBHOOK_URL", "https://mock.invalid/reminder")
    monkeypatch.setattr(DingTalkAdapter, "_post_json", staticmethod(lambda *a, **k: (200, '{"errcode":0}')))
    with database.SessionLocal() as db:
        plan_id = db.query(database.WorkoutPlan).filter(database.WorkoutPlan.is_training_day == True).first().id
    result = client.post("/api/notifications/send", json={"plan_id": plan_id, "include_todo": False}).json()
    assert result["status"] == "sent"
    assert result["sent"] is True
    assert result["todo"] is None


def test_compatibility_reminder_handles_missing_and_rest_plan(client, app_modules):
    database, _main = app_modules
    missing = client.post("/api/reminders/dingtalk/send", json={"plan_id": 999999})
    assert missing.status_code == 200
    assert missing.json()["status"] == "not_found"
    with database.SessionLocal() as db:
        plan_id = db.query(database.WorkoutPlan).filter(database.WorkoutPlan.is_training_day == False).first().id
    rest = client.post("/api/reminders/dingtalk/send", json={"plan_id": plan_id})
    assert rest.status_code == 200
    assert rest.json()["status"] == "no_training_plan"


@pytest.mark.parametrize("returncode", [0, 1, 7])
def test_windows_wrapper_preserves_tick_exit_code(tmp_path, monkeypatch, returncode):
    path = Path(__file__).resolve().parents[1] / "scripts" / "windows_daily_reminder.py"
    spec = importlib.util.spec_from_file_location("van22_windows_tick", path)
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    monkeypatch.setattr(wrapper, "merge_secret_env", lambda *a: {})
    monkeypatch.setattr(wrapper, "refresh_access_token_if_possible", lambda *a: "skipped")
    monkeypatch.setattr(wrapper, "start_app_if_needed", lambda *a: (None, "already_running"))
    monkeypatch.setattr(wrapper, "health_ok", lambda *a: True)
    monkeypatch.setattr(wrapper, "run_tick", lambda *a: subprocess.CompletedProcess([], returncode, 'NOTIFICATION: test\n{"status":"partial_success", "reminder":{"status": "sent"}}', ""))
    log = tmp_path / "runs.jsonl"
    assert wrapper.main(["--run-log", str(log), "--secret-file", str(tmp_path / "absent")]) == returncode
    assert json.loads(log.read_text())["tick_returncode"] == returncode
    assert json.loads(log.read_text())["notification_status"] == "partial_success"
