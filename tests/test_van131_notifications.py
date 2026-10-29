"""VAN-131: isolated SQLite; mock business receipts, never real notifications."""
import json

import pytest
from fastapi.testclient import TestClient

from adapters.dingtalk import DingTalkAdapter


@pytest.fixture()
def deliveries(app_modules, monkeypatch):
    database, main = app_modules
    calls = []
    state = {'reminder': True, 'todo': True}
    def post(url, payload, headers=None):
        channel = url.rsplit('/', 1)[-1]
        calls.append(channel)
        body = ({'errcode': 0 if state[channel] else 500} if channel == 'reminder'
                else {'id': 'todo-1'} if state[channel] else {'code': 'Failed'})
        return 200, json.dumps(body)
    monkeypatch.setenv('DINGTALK_WEBHOOK_URL', 'https://mock.invalid/reminder')
    monkeypatch.setenv('DINGTALK_TODO_CREATE_URL', 'https://mock.invalid/todo')
    monkeypatch.setenv('DINGTALK_ACCESS_TOKEN', 'fake')
    monkeypatch.setattr(DingTalkAdapter, '_post_json', staticmethod(post))
    with database.SessionLocal() as db:
        plan_id = db.query(database.WorkoutPlan).filter_by(is_training_day=True).first().id
    return database, TestClient(main.app), plan_id, calls, state


@pytest.mark.parametrize('reminder_ok,todo_ok,expected,retry_calls', [
    (True, False, 'partial_success', ['todo']),
    (False, True, 'partial_success', ['reminder']),
    (False, False, 'failed', ['reminder', 'todo']),
    (True, True, 'sent', []),
])
def test_ordinary_retry_only_requests_missing_channels(deliveries, reminder_ok, todo_ok, expected, retry_calls):
    database, client, plan_id, calls, state = deliveries
    state.update(reminder=reminder_ok, todo=todo_ok)
    first = client.post('/api/notifications/send', json={'plan_id': plan_id}).json()
    assert first['status'] == expected
    assert first['sent'] is (reminder_ok and todo_ok)
    state.update(reminder=True, todo=True)
    calls.clear()
    second = client.post('/api/notifications/send', json={'plan_id': plan_id}).json()
    assert second['status'] == ('sent' if retry_calls else 'duplicate_skipped')
    assert calls == retry_calls
    calls.clear()
    assert client.post('/api/notifications/send', json={'plan_id': plan_id}).json()['status'] == 'duplicate_skipped'
    assert calls == []
    with database.SessionLocal() as db:
        assert {r.delivery_channel for r in db.query(database.Reminder).filter_by(plan_id=plan_id)} == {'dingtalk_reminder', 'dingtalk_todo'}
        assert db.execute(database.text('PRAGMA foreign_key_check')).all() == []


def test_repeated_partial_failure_keeps_success_fact(deliveries):
    database, client, plan_id, calls, state = deliveries
    state['todo'] = False
    for attempt in range(3):
        calls.clear()
        result = client.post('/api/notifications/send', json={'plan_id': plan_id}).json()
        assert result['status'] == 'partial_success'
        assert result['sent'] is False
        assert calls == (['reminder', 'todo'] if attempt == 0 else ['todo'])
        if attempt:
            assert result['reminder'] == {'channel': 'dingtalk', 'status': 'duplicate_skipped', 'sent': True, 'previously_sent': True}
    with database.SessionLocal() as db:
        assert [r.delivery_channel for r in db.query(database.Reminder).filter_by(plan_id=plan_id)] == ['dingtalk_reminder']


def test_reminder_only_does_not_suppress_future_todo(deliveries):
    _, client, plan_id, calls, _ = deliveries
    assert client.post('/api/notifications/send', json={'plan_id': plan_id, 'include_todo': False}).json()['status'] == 'sent'
    calls.clear()
    result = client.post('/api/notifications/send', json={'plan_id': plan_id}).json()
    assert result['status'] == 'sent'
    assert result['todo']['created'] is True
    assert result['reminder']['previously_sent'] is True
    assert calls == ['todo']


@pytest.mark.parametrize('force_ok,expected', [(True, 'sent'), (False, 'failed')])
def test_force_resends_all_and_reports_current_attempt(deliveries, force_ok, expected):
    database, client, plan_id, calls, state = deliveries
    client.post('/api/notifications/send', json={'plan_id': plan_id})
    calls.clear()
    state.update(reminder=force_ok, todo=force_ok)
    result = client.post('/api/notifications/send', json={'plan_id': plan_id, 'force': True}).json()
    assert calls == ['reminder', 'todo']
    assert result['status'] == expected
    assert result['sent'] is force_ok
    calls.clear()
    assert client.post('/api/notifications/send', json={'plan_id': plan_id}).json()['status'] == 'duplicate_skipped'
    assert calls == []
    with database.SessionLocal() as db:
        assert db.query(database.Reminder).filter_by(plan_id=plan_id).count() == (4 if force_ok else 2)


def test_channel_plan_and_date_scopes(deliveries, monkeypatch):
    database, client, plan_id, calls, _ = deliveries
    client.post('/api/notifications/send', json={'plan_id': plan_id})
    calls.clear()
    # DingTalk success must not suppress another adapter.
    from adapters.workbuddy import WorkBuddyAdapter
    workbuddy_calls = []
    def workbuddy_send(self, payload):
        workbuddy_calls.append(payload['id'])
        return {'channel': 'workbuddy', 'status': 'sent', 'sent': True}
    monkeypatch.setattr(WorkBuddyAdapter, 'send_reminder', workbuddy_send)
    assert client.post('/api/notifications/send', json={'plan_id': plan_id, 'channel': 'workbuddy'}).json()['status'] == 'sent'
    assert client.post('/api/notifications/send', json={'plan_id': plan_id, 'channel': 'workbuddy'}).json()['status'] == 'duplicate_skipped'
    assert workbuddy_calls == [plan_id]
    with database.SessionLocal() as db:
        other_id = db.query(database.WorkoutPlan).filter(database.WorkoutPlan.id != plan_id, database.WorkoutPlan.is_training_day == True).first().id
        plan = db.get(database.WorkoutPlan, plan_id)
        from datetime import date
        plan.plan_date = date(2099, 1, 1)
        db.commit()
    for target in (plan_id, other_id):
        assert client.post('/api/notifications/send', json={'plan_id': target}).json()['status'] == 'sent'
    assert calls == ['reminder', 'todo', 'reminder', 'todo']


def test_compatibility_endpoints_share_channel_successes(deliveries, monkeypatch):
    database, client, plan_id, calls, _ = deliveries
    # The todo compatibility API injects main.post_json; reuse our fake.
    import main
    monkeypatch.setattr(main, 'post_json', DingTalkAdapter._post_json)
    assert client.post('/api/todos/dingtalk/create', json={'plan_id': plan_id}).json()['created'] is True
    calls.clear()
    assert client.post('/api/notifications/send', json={'plan_id': plan_id}).json()['status'] == 'sent'
    assert calls == ['reminder']
    with database.SessionLocal() as db:
        db.query(database.Reminder).delete()
        db.commit()
    calls.clear()
    for _ in range(2):  # existing explicit resend behavior is preserved
        assert client.post('/api/reminders/dingtalk/send', json={'plan_id': plan_id}).json()['sent'] is True
    assert calls == ['reminder', 'reminder']
    calls.clear()
    assert client.post('/api/notifications/send', json={'plan_id': plan_id}).json()['status'] == 'sent'
    assert calls == ['todo']


def test_todo_exception_does_not_lose_reminder_success(deliveries, monkeypatch):
    database, client, plan_id, calls, _ = deliveries
    original = DingTalkAdapter.create_todo
    def crash(*args):
        raise RuntimeError('simulated unexpected todo error')
    monkeypatch.setattr(DingTalkAdapter, 'create_todo', crash)
    with pytest.raises(RuntimeError, match='unexpected todo'):
        client.post('/api/notifications/send', json={'plan_id': plan_id})
    with database.SessionLocal() as db:
        assert [r.delivery_channel for r in db.query(database.Reminder).filter_by(plan_id=plan_id)] == ['dingtalk_reminder']
    monkeypatch.setattr(DingTalkAdapter, 'create_todo', original)
    calls.clear()
    assert client.post('/api/notifications/send', json={'plan_id': plan_id}).json()['status'] == 'sent'
    assert calls == ['todo']


@pytest.mark.parametrize('failed_channel', ['dingtalk_reminder', 'dingtalk_todo'])
def test_persistence_failure_is_http_error_not_fake_success(deliveries, failed_channel):
    database, client, plan_id, calls, _ = deliveries
    from sqlalchemy import event
    def reject_commit(session):
        if any(row.__tablename__ == 'reminders' and row.delivery_channel == failed_channel for row in session.new):
            raise RuntimeError('simulated persistence failure')
    event.listen(database.SessionLocal.class_, 'before_commit', reject_commit)
    try:
        response = TestClient(client.app, raise_server_exceptions=False).post('/api/notifications/send', json={'plan_id': plan_id})
        assert response.status_code == 500
    finally:
        event.remove(database.SessionLocal.class_, 'before_commit', reject_commit)
    with database.SessionLocal() as db:
        assert [r.delivery_channel for r in db.query(database.Reminder).filter_by(plan_id=plan_id)] == ([] if failed_channel == 'dingtalk_reminder' else ['dingtalk_reminder'])
        assert db.execute(database.text('PRAGMA foreign_key_check')).all() == []
    if failed_channel == 'dingtalk_reminder':
        assert calls == ['reminder']  # do not proceed after an unrecorded success
    calls.clear()
    assert client.post('/api/notifications/send', json={'plan_id': plan_id}).json()['status'] == 'sent'
    assert calls == (['reminder', 'todo'] if failed_channel == 'dingtalk_reminder' else ['todo'])


def test_legacy_migration_preserves_all_rows_and_original_dedup(deliveries):
    database, client, plan_id, calls, _ = deliveries
    with database.engine.begin() as conn:
        conn.execute(database.text('DROP TABLE reminders'))
        conn.execute(database.text('''CREATE TABLE reminders (
            id INTEGER PRIMARY KEY, plan_id INTEGER REFERENCES workout_plans(id),
            reminder_date DATE NOT NULL, message VARCHAR(240) NOT NULL,
            is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)'''))
        conn.execute(database.text('''INSERT INTO reminders (id, plan_id, reminder_date, message, is_active)
            SELECT 41, id, plan_date, 'historical success', 1 FROM workout_plans WHERE id=:id'''), {'id': plan_id})
        conn.execute(database.text("INSERT INTO reminders (id, reminder_date, message, is_active) VALUES (42, '2000-01-01', 'inactive legacy', 0)"))
        before = conn.execute(database.text('SELECT * FROM reminders ORDER BY id')).all()
        other_before = {table: conn.execute(database.text(f'SELECT * FROM {table}')).all() for table in database.Base.metadata.tables if table != 'reminders'}
    for _ in range(2):
        database.create_tables()
    with database.engine.connect() as conn:
        after = conn.execute(database.text('SELECT id, plan_id, reminder_date, message, is_active, created_at FROM reminders ORDER BY id')).all()
        assert after == before
        assert conn.execute(database.text('SELECT delivery_channel FROM reminders')).all() == [(None,), (None,)]
        assert {table: conn.execute(database.text(f'SELECT * FROM {table}')).all() for table in other_before} == other_before
        assert conn.execute(database.text('PRAGMA integrity_check')).scalar() == 'ok'
        assert conn.execute(database.text('PRAGMA foreign_key_check')).all() == []
    assert client.post('/api/notifications/send', json={'plan_id': plan_id}).json()['status'] == 'duplicate_skipped'
    assert calls == []
    assert client.post('/api/notifications/send', json={'plan_id': plan_id, 'force': True}).json()['status'] == 'sent'
    assert calls == ['reminder', 'todo']
