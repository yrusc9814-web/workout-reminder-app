import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


APP_DIR = Path(__file__).resolve().parents[1]
SCRIPT = APP_DIR / "scripts" / "workout_reminder_tick.py"


class JsonHandler(BaseHTTPRequestHandler):
    response_status = 200
    response_body = {}
    response_content_type = "application/json"
    requests = []

    def do_GET(self):
        self.__class__.requests.append({"method": "GET", "path": self.path})
        body = self.response_body
        if isinstance(body, bytes):
            payload = body
        else:
            payload = json.dumps(body).encode("utf-8")
        self.send_response(self.response_status)
        self.send_header("Content-Type", self.response_content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        self.__class__.requests.append({
            "method": "POST",
            "path": self.path,
            "body": json.loads(raw.decode("utf-8")) if raw else None,
        })
        payload = json.dumps({"status": "not_configured"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


def run_tick(tmp_path, body=None, status=200, raw_body=None, extra_env=None):
    class Handler(JsonHandler):
        response_status = status
        response_body = raw_body if raw_body is not None else body
        requests = []

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        log_path = tmp_path / "reminder-log.json"
        env = {
            "WORKOUT_REMINDER_API_URL": f"http://127.0.0.1:{server.server_port}/api/today",
            "WORKOUT_REMINDER_LOG_PATH": str(log_path),
            "WORKOUT_DINGTALK_REMINDER_URL": f"http://127.0.0.1:{server.server_port}/api/reminders/dingtalk/send",
            "WORKOUT_DINGTALK_TODO_URL": f"http://127.0.0.1:{server.server_port}/api/todos/dingtalk/create",
        }
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=APP_DIR,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result, log_path, Handler.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_training_day_prints_reminder_and_appends_log(tmp_path):
    body = {
        "date": "2026-05-11",
        "id": 42,
        "title": "力量训练",
        "theme": "上肢",
        "type": "training",
        "is_training": True,
        "items": [],
    }

    result, log_path, _requests = run_tick(tmp_path, body=body)

    assert result.returncode == 0
    assert result.stderr == ""
    assert "REMINDER: 2026-05-11 训练日 - 力量训练" in result.stdout
    entries = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["date"] == "2026-05-11"
    assert entries[0]["plan_id"] == 42
    assert entries[0]["title"] == "力量训练"
    assert "reminded_at" in entries[0]


def test_duplicate_same_date_and_plan_does_not_repeat(tmp_path):
    body = {
        "date": "2026-05-12",
        "id": 99,
        "title": "核心训练",
        "type": "training",
        "is_training": True,
        "items": [],
    }

    first, log_path, first_requests = run_tick(tmp_path, body=body)
    second, _, second_requests = run_tick(tmp_path, body=body)

    assert first.returncode == 0
    assert second.returncode == 0
    assert "REMINDER:" in first.stdout
    assert "Already reminded for 2026-05-12 plan_id=99" in second.stdout
    entries = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(entries) == 1


def test_service_unavailable_reports_clear_error(tmp_path):
    log_path = tmp_path / "reminder-log.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=APP_DIR,
        env={
            **os.environ,
            "WORKOUT_REMINDER_API_URL": "http://127.0.0.1:9/api/today",
            "WORKOUT_REMINDER_LOG_PATH": str(log_path),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert "ERROR: API request failed" in result.stderr
    assert result.stdout == ""
    assert not log_path.exists()


def test_no_training_plan_prints_no_reminder_and_writes_no_log(tmp_path):
    body = {
        "date": "2026-05-13",
        "id": None,
        "title": None,
        "type": "rest",
        "is_training": False,
        "items": [],
    }

    result, log_path, _requests = run_tick(tmp_path, body=body)

    assert result.returncode == 0
    assert "No training plan for 2026-05-13; no reminder sent." in result.stdout
    assert result.stderr == ""
    assert not log_path.exists()


def test_bad_api_json_reports_error_and_writes_no_log(tmp_path):
    result, log_path, _requests = run_tick(tmp_path, raw_body=b"not-json")

    assert result.returncode == 1
    assert "ERROR: API returned invalid JSON" in result.stderr
    assert result.stdout == ""
    assert not log_path.exists()


def test_corrupt_log_reports_error_and_does_not_overwrite(tmp_path):
    log_path = tmp_path / "reminder-log.json"
    log_path.write_text("not-json", encoding="utf-8")
    body = {
        "date": "2026-05-14",
        "id": 101,
        "title": "有氧训练",
        "type": "training",
        "is_training": True,
        "items": [],
    }

    result, _, _requests = run_tick(tmp_path, body=body)

    assert result.returncode == 1
    assert "ERROR: reminder log is invalid JSON" in result.stderr
    assert log_path.read_text(encoding="utf-8") == "not-json"


def test_training_day_calls_dingtalk_reminder_and_todo_paths(tmp_path):
    body = {
        "date": "2026-06-01",
        "id": 201,
        "title": "Hip stability and core control",
        "theme": "Core",
        "type": "training",
        "is_training": True,
        "items": [
            {"name": "Supine pelvic clock", "video_url": "https://example.com/videos/pelvic-clock"},
        ],
    }

    result, log_path, requests = run_tick(tmp_path, body=body)

    assert result.returncode == 0
    post_paths = [request["path"] for request in requests if request["method"] == "POST"]
    assert "/api/reminders/dingtalk/send" in post_paths
    assert "/api/todos/dingtalk/create" in post_paths
    payloads = [request["body"] for request in requests if request["method"] == "POST"]
    assert all(payload["plan_id"] == 201 for payload in payloads)
    assert json.loads(log_path.read_text(encoding="utf-8"))[0]["dingtalk_reminder_status"] == "not_configured"
    assert json.loads(log_path.read_text(encoding="utf-8"))[0]["dingtalk_todo_status"] == "not_configured"


def test_duplicate_training_day_does_not_call_dingtalk_again(tmp_path):
    body = {
        "date": "2026-06-03",
        "id": 202,
        "title": "Breathing and balance",
        "type": "training",
        "is_training": True,
        "items": [{"name": "Box breathing", "video_url": "https://example.com/videos/box-breathing"}],
    }

    first, _log_path, first_requests = run_tick(tmp_path, body=body)
    second, _log_path, second_requests = run_tick(tmp_path, body=body)

    assert first.returncode == 0
    assert second.returncode == 0
    assert len([request for request in first_requests if request["method"] == "POST"]) == 2
    assert [request for request in second_requests if request["method"] == "POST"] == []


def test_rest_day_does_not_call_dingtalk_paths(tmp_path):
    body = {
        "date": "2026-06-02",
        "id": 203,
        "title": "Rest day",
        "type": "rest",
        "is_training": False,
        "items": [],
    }

    result, log_path, requests = run_tick(tmp_path, body=body)

    assert result.returncode == 0
    assert not log_path.exists()
    assert [request for request in requests if request["method"] == "POST"] == []
