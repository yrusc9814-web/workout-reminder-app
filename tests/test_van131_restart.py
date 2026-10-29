"""Real loopback API + tick subprocesses across process death, with fake DingTalk."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest


APP_DIR = Path(__file__).resolve().parents[1]
MOCK_SERVER = r'''
import json, os, socket, sys
from datetime import date
from pathlib import Path
# Fail closed if an unmocked external transport is accidentally used.
original_connect = socket.socket.connect
def connect(sock, address):
    if sock.family == socket.AF_UNIX or address[0] in ('127.0.0.1', '::1'):
        return original_connect(sock, address)
    raise RuntimeError('external network forbidden')
socket.socket.connect = connect
from adapters.dingtalk import DingTalkAdapter
state_file, calls_file, port = sys.argv[1:]
def post(url, payload, headers=None):
    channel = url.rsplit('/', 1)[-1]
    state = json.loads(Path(state_file).read_text())
    body = ({'errcode': 0 if state[channel] else 500} if channel == 'reminder'
            else {'taskId': 'fake-task'} if state[channel] else {'code': 'Failed'})
    with open(calls_file, 'a') as log:
        log.write(json.dumps({'channel':channel, 'body':body, 'pid':os.getpid()}) + '\n')
    return 200, json.dumps(body)
DingTalkAdapter._post_json = staticmethod(post)
import database
from main import app
# Only this test's isolated DB is opened; no seed/history DB is copied.
database.create_tables()
with database.SessionLocal() as db:
    if db.query(database.WorkoutPlan).filter_by(plan_date=date.today()).first() is None:
        db.add(database.WorkoutPlan(plan_date=date.today(), title='VAN-131 mock', focus='test', is_training_day=True))
        db.commit()
import uvicorn
uvicorn.run(app, host='127.0.0.1', port=int(port), log_level='error')
'''


@contextmanager
def mock_server(tmp_path, env, port, hard_stop=False):
    with (tmp_path / 'server.log').open('a') as log:
        process = subprocess.Popen(
            [sys.executable, '-c', MOCK_SERVER, str(tmp_path / 'state.json'), str(tmp_path / 'calls.jsonl'), str(port)],
            cwd=APP_DIR, env=env, stdout=log, stderr=log,
        )
        try:
            for _ in range(200):
                if process.poll() is not None:
                    pytest.fail((tmp_path / 'server.log').read_text())
                try:
                    with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=0.2) as response:
                        assert response.status == 200
                    break
                except (URLError, TimeoutError):
                    time.sleep(0.05)
            else:
                pytest.fail('mock API startup timeout')
            yield process.pid
        finally:
            process.kill() if hard_stop else process.terminate()
            process.wait(timeout=10)
            assert process.poll() is not None


@pytest.mark.parametrize('reminder_ok,todo_ok,first_status', [
    (True, False, 'partial_success'), (False, True, 'partial_success'),
    (False, False, 'failed'), (True, True, 'sent'),
])
def test_restart_preserves_channel_facts_and_tick_result(tmp_path, reminder_ok, todo_ok, first_status):
    env = {key: value for key, value in os.environ.items() if not key.startswith(('DINGTALK_', 'WORKBUDDY_', 'WORKOUT_NOTIFICATION_', 'OPENAI_', 'DEEPSEEK_', 'WUAPI_', 'WORKOUT_AI_'))}
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    env.update(WORKOUT_DB_PATH=str(tmp_path / 'acceptance.sqlite'), WORKOUT_DISABLE_SEED='1',
               DINGTALK_WEBHOOK_URL='https://mock.invalid/reminder', DINGTALK_TODO_CREATE_URL='https://mock.invalid/todo',
               DINGTALK_ACCESS_TOKEN='fake', WORKOUT_NOTIFICATION_URL=f'http://127.0.0.1:{port}/api/notifications/send')
    state_path = tmp_path / 'state.json'
    state_path.write_text(json.dumps({'reminder': reminder_ok, 'todo': todo_ok}))
    observations = []
    def tick(expected_status, expected_calls, force=False):
        calls_path = tmp_path / 'calls.jsonl'
        before = len(calls_path.read_text().splitlines()) if calls_path.exists() else 0
        result = subprocess.run([sys.executable, str(APP_DIR / 'scripts/workout_reminder_tick.py')],
                                cwd=APP_DIR, env={**env, 'WORKOUT_NOTIFICATION_FORCE': str(int(force))},
                                capture_output=True, text=True, timeout=10)
        body = json.loads(result.stdout.partition('\n')[2])
        assert body['status'] == expected_status
        assert result.returncode == (0 if expected_status in ('sent', 'duplicate_skipped') else 1)
        assert body['sent'] is (expected_status == 'sent')
        calls = [json.loads(line) for line in calls_path.read_text().splitlines()][before:]
        assert [call['channel'] for call in calls] == expected_calls
        with sqlite3.connect(env['WORKOUT_DB_PATH']) as db:
            facts = db.execute('SELECT plan_id, reminder_date, delivery_channel, is_active FROM reminders ORDER BY id').fetchall()
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        observations.append({'status': expected_status, 'exit_code': result.returncode, 'result': body, 'calls': calls, 'facts': facts})
    def unrelated_rows():
        with sqlite3.connect(env['WORKOUT_DB_PATH']) as db:
            names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'reminders' ORDER BY name")]
            return {name: db.execute(f'SELECT * FROM {name} ORDER BY rowid').fetchall() for name in names}
    with mock_server(tmp_path, env, port, hard_stop=True) as first_pid:
        tick(first_status, ['reminder', 'todo'])
        unchanged = unrelated_rows()
    # A new interpreter and service, same SQLite, even after SIGKILL.
    with mock_server(tmp_path, env, port) as second_pid:
        assert second_pid != first_pid
        missing = ([] if reminder_ok else ['reminder']) + ([] if todo_ok else ['todo'])
        tick('duplicate_skipped' if not missing else first_status, missing)
        state_path.write_text(json.dumps({'reminder': True, 'todo': True}))
        tick('sent' if missing else 'duplicate_skipped', missing)
        tick('duplicate_skipped', [])
        tick('sent', ['reminder', 'todo'], force=True)
        state_path.write_text(json.dumps({'reminder': False, 'todo': False}))
        tick('failed', ['reminder', 'todo'], force=True)
        tick('duplicate_skipped', [])
        assert unrelated_rows() == unchanged
    (tmp_path / 'observations.json').write_text(json.dumps({'first_pid': first_pid, 'second_pid': second_pid, 'ticks': observations}, ensure_ascii=False, indent=2))
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', port)) != 0
