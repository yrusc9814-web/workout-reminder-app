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
    response_body = {"status": "not_configured", "plan_id": 42, "date": "2026-06-01"}
    response_content_type = "application/json"
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        self.__class__.requests.append(
            {
                "method": "POST",
                "path": self.path,
                "body": json.loads(raw.decode("utf-8")) if raw else None,
                "headers": {key: value for key, value in self.headers.items()},
            }
        )
        body = self.response_body
        payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(self.response_status)
        self.send_header("Content-Type", self.response_content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


def run_tick(body=None, status=200, raw_body=None, extra_env=None):
    class Handler(JsonHandler):
        response_status = status
        response_body = raw_body if raw_body is not None else (body or JsonHandler.response_body)
        requests = []

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {
            "WORKOUT_NOTIFICATION_URL": f"http://127.0.0.1:{server.server_port}/api/notifications/send",
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
        return result, Handler.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_tick_posts_only_notification_endpoint():
    result, requests = run_tick()

    assert result.returncode == 0
    assert result.stderr == ""
    assert "NOTIFICATION: 2026-06-01 plan_id=42 status=not_configured" in result.stdout
    assert [request["path"] for request in requests] == ["/api/notifications/send"]
    assert requests[0]["body"] == {"channel": "dingtalk", "include_todo": True, "force": False}


def test_tick_forwards_environment_options():
    result, requests = run_tick(
        body={"status": "sent", "plan_id": 7, "date": "2026-06-02"},
        extra_env={
            "WORKOUT_NOTIFICATION_CHANNEL": "workbuddy",
            "WORKOUT_NOTIFICATION_INCLUDE_TODO": "0",
            "WORKOUT_NOTIFICATION_FORCE": "1",
        },
    )

    assert result.returncode == 0
    assert requests[0]["body"] == {"channel": "workbuddy", "include_todo": False, "force": True}


def test_service_unavailable_reports_clear_error():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=APP_DIR,
        env={**os.environ, "WORKOUT_NOTIFICATION_URL": "http://127.0.0.1:9/api/notifications/send"},
        capture_output=True,
        text=True,
        errors="replace",
        timeout=10,
    )

    assert result.returncode == 1
    assert "ERROR: notification API request failed" in result.stderr


def test_bad_notification_json_reports_error():
    result, _requests = run_tick(raw_body=b"not-json")

    assert result.returncode == 1
    assert "ERROR: notification API returned invalid JSON" in result.stderr


def test_non_object_notification_json_reports_error():
    result, _requests = run_tick(raw_body=b"[]")

    assert result.returncode == 1
    assert "ERROR: notification API returned invalid JSON: expected object" in result.stderr


def test_http_error_reports_response_body():
    result, _requests = run_tick(status=500, body={"detail": "boom"})

    assert result.returncode == 1
    assert "boom" in result.stderr
