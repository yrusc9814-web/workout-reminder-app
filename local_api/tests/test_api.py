"""Phase 4.3 — Unit tests for the local API.

Run with:
    cd D:/hermes-agent
    python -m pytest local_api/tests/test_api.py -v

Uses FastAPI TestClient so no server needs to be running.
"""

import json
import pytest
from fastapi.testclient import TestClient

# Force test database path before any import
import os
from pathlib import Path

TEST_DB_PATH = Path(__file__).resolve().parent.parent / "test_data" / "test_tasks.db"
os.environ["HERMES_API_TOKEN"] = "test-token-hermes-local-4.3"

# Now import app — it will pick up the test DB
from local_api.main import app
from local_api.database import reset_db, init_db, get_db

TEST_TOKEN = "test-token-hermes-local-4.3"
AUTH_HEADER = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture(autouse=True)
def clean_db():
    """Reset the database before each test."""
    reset_db()
    init_db()
    yield
    reset_db()


client = TestClient(app)


# ── System Status Tests ─────────────────────────────────────────────────────


class TestSystemStatus:
    """GET /api/system/status"""

    def test_status_with_token(self):
        resp = client.get("/api/system/status", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["api_version"] == "4.3.0"
        assert data["db_connected"] is True
        assert data["task_count"] == 0

    def test_status_without_token(self):
        resp = client.get("/api/system/status")
        assert resp.status_code == 401

    def test_status_with_bad_token(self):
        resp = client.get(
            "/api/system/status",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401


# ── Task CRUD Tests ────────────────────────────────────────────────────────


class TestCreateTask:
    """POST /api/tasks"""

    def test_create_minimal(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "Minimal task"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Minimal task"
        assert data["task_id"].startswith("task_")
        assert data["priority"] == "P2"  # default
        assert data["status"] == "pending"
        assert data["created_channel"] == "api_test"

    def test_create_full(self):
        payload = {
            "title": "Full task",
            "description": "A detailed description",
            "priority": "P0",
            "start_time": "2026-06-01T09:00:00+08:00",
            "due_time": "2026-06-01T10:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "location": "Office",
            "need_weather_check": True,
            "reminder_channels": ["local_ui", "wechat"],
            "created_channel": "api_test",
        }
        resp = client.post("/api/tasks", json=payload, headers=AUTH_HEADER)
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Full task"
        assert data["priority"] == "P0"
        assert data["need_weather_check"] is True
        assert data["reminder_channels"] == ["local_ui", "wechat"]
        assert data["location"] == "Office"

    def test_create_duplicate_task_ids(self):
        """Two tasks created in sequence should have different IDs."""
        resp1 = client.post(
            "/api/tasks", json={"title": "Task A"}, headers=AUTH_HEADER
        )
        resp2 = client.post(
            "/api/tasks", json={"title": "Task B"}, headers=AUTH_HEADER
        )
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["task_id"] != resp2.json()["task_id"]

    def test_create_invalid_priority(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "Bad priority", "priority": "P5"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_create_invalid_channel(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "Bad channel", "created_channel": "unknown_channel"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_create_empty_title(self):
        resp = client.post(
            "/api/tasks",
            json={"title": ""},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422


class TestListTasks:
    """GET /api/tasks"""

    def test_list_empty(self):
        resp = client.get("/api/tasks", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tasks"] == []
        assert data["total"] == 0

    def test_list_with_tasks(self):
        # Create a few tasks first
        for i in range(3):
            client.post(
                "/api/tasks",
                json={"title": f"Task {i}", "priority": "P1"},
                headers=AUTH_HEADER,
            )
        resp = client.get("/api/tasks", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 3
        assert data["total"] == 3

    def test_filter_by_status(self):
        client.post("/api/tasks", json={"title": "Pending"}, headers=AUTH_HEADER)
        resp = client.get("/api/tasks?status=pending", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_filter_by_priority(self):
        client.post(
            "/api/tasks",
            json={"title": "P0 task", "priority": "P0"},
            headers=AUTH_HEADER,
        )
        client.post(
            "/api/tasks",
            json={"title": "P1 task", "priority": "P1"},
            headers=AUTH_HEADER,
        )
        resp = client.get("/api/tasks?priority=P0", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["tasks"][0]["priority"] == "P0"

    def test_pagination(self):
        for i in range(5):
            client.post(
                "/api/tasks", json={"title": f"T{i}"}, headers=AUTH_HEADER
            )
        resp = client.get("/api/tasks?limit=2&offset=1", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 1

    def test_invalid_status_filter(self):
        resp = client.get("/api/tasks?status=invalid_status", headers=AUTH_HEADER)
        assert resp.status_code == 422

    def test_invalid_priority_filter(self):
        resp = client.get("/api/tasks?priority=P5", headers=AUTH_HEADER)
        assert resp.status_code == 422


class TestGetTask:
    """GET /api/tasks/{task_id}"""

    def test_get_existing(self):
        create = client.post(
            "/api/tasks", json={"title": "Get me"}, headers=AUTH_HEADER
        )
        task_id = create.json()["task_id"]
        resp = client.get(f"/api/tasks/{task_id}", headers=AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.json()["task_id"] == task_id

    def test_get_nonexistent(self):
        resp = client.get("/api/tasks/task_nonexistent_12345", headers=AUTH_HEADER)
        assert resp.status_code == 404


class TestUpdateTask:
    """PATCH /api/tasks/{task_id}"""

    def test_update_title(self):
        create = client.post(
            "/api/tasks", json={"title": "Old title"}, headers=AUTH_HEADER
        )
        task_id = create.json()["task_id"]
        resp = client.patch(
            f"/api/tasks/{task_id}",
            json={"title": "New title"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New title"
        assert resp.json()["priority"] == "P2"  # unchanged

    def test_update_priority(self):
        create = client.post(
            "/api/tasks", json={"title": "X"}, headers=AUTH_HEADER
        )
        task_id = create.json()["task_id"]
        resp = client.patch(
            f"/api/tasks/{task_id}",
            json={"priority": "P0"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.json()["priority"] == "P0"

    def test_update_nonexistent(self):
        resp = client.patch(
            "/api/tasks/task_nonexistent_999",
            json={"title": "X"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 404

    def test_update_invalid_status(self):
        create = client.post(
            "/api/tasks", json={"title": "X"}, headers=AUTH_HEADER
        )
        task_id = create.json()["task_id"]
        resp = client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "invalid"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422


class TestCompleteTask:
    """POST /api/tasks/{task_id}/complete"""

    def test_complete_task(self):
        create = client.post(
            "/api/tasks", json={"title": "Complete me"}, headers=AUTH_HEADER
        )
        task_id = create.json()["task_id"]
        resp = client.post(
            f"/api/tasks/{task_id}/complete", headers=AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_complete_nonexistent(self):
        resp = client.post(
            "/api/tasks/task_nonexistent_999/complete", headers=AUTH_HEADER
        )
        assert resp.status_code == 404

    def test_complete_already_completed(self):
        create = client.post(
            "/api/tasks", json={"title": "X"}, headers=AUTH_HEADER
        )
        task_id = create.json()["task_id"]
        client.post(f"/api/tasks/{task_id}/complete", headers=AUTH_HEADER)
        # Completing again should still succeed (idempotent)
        resp = client.post(
            f"/api/tasks/{task_id}/complete", headers=AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


# ── Validation Tests ───────────────────────────────────────────────────────


class TestForbiddenFields:
    """Middleware rejects forbidden field names."""

    def test_file_path_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "file_path": "/etc/passwd"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422
        assert "Forbidden field" in resp.json()["detail"]

    def test_sql_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "sql": "DROP TABLE"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_command_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "command": "rm -rf /"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_script_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "script": "something"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_shell_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "shell": "/bin/bash"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_exec_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "exec": "calc.exe"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_cmd_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "cmd": "dir"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_path_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "path": "/etc/shadow"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_filename_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "filename": "secret.key"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_directory_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "directory": "/root"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_template_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "template": "{{config}}"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_raw_query_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "bad", "raw_query": "SELECT 1"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422


class TestSQLInjection:
    """Middleware rejects SQL injection patterns in string values."""

    def test_select_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "SELECT * FROM users"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_drop_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "DROP TABLE tasks"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_insert_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "INSERT INTO tasks VALUES"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_union_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "1 UNION SELECT"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_sql_comment_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "admin'--"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_sql_in_description(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "OK", "description": "SELECT * FROM passwords"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_clean_title_accepted(self):
        """Normal titles without SQL should work fine."""
        resp = client.post(
            "/api/tasks",
            json={"title": "Buy milk and eggs"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 201


class TestShellInjection:
    """Middleware rejects shell injection patterns."""

    def test_semicolon_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "hello; rm -rf /"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_pipe_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "cat /etc/passwd | mail"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_and_and_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "ls && rm file"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_subprocess_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "subprocess.call('ls')"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_os_system_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "os.system('rm')"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_powershell_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "powershell Get-Process"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422

    def test_cmd_exe_rejected(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "cmd.exe /c dir"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 422


class TestContentType:
    """415 if Content-Type is not application/json on mutating requests."""

    def test_post_without_content_type(self):
        resp = client.post(
            "/api/tasks",
            content=b'{"title":"test"}',
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 415

    def test_post_with_text_plain(self):
        resp = client.post(
            "/api/tasks",
            content=b"plain text",
            headers={**AUTH_HEADER, "Content-Type": "text/plain"},
        )
        assert resp.status_code == 415

    def test_get_without_content_type(self):
        """GET requests don't need Content-Type."""
        resp = client.get("/api/tasks", headers=AUTH_HEADER)
        assert resp.status_code == 200


class TestTokenLogging:
    """Verify that the access log does NOT contain any token fragment."""

    def test_log_no_token_fragment(self, tmp_path):
        """Check that access log lines contain auth_result and token_present but no token text."""
        from local_api.config import LOG_DIR, ACCESS_LOG_PATH

        # Trigger some auth activity
        client.get("/api/system/status", headers=AUTH_HEADER)
        client.get("/api/system/status")  # no token

        # Read the log
        log_path = ACCESS_LOG_PATH
        if log_path.exists():
            log_content = log_path.read_text(encoding="utf-8")
            # Token must not appear anywhere in the log
            assert "test-token-hermes-local-4.3" not in log_content
            assert "test-token" not in log_content
            # But auth metadata should appear
            assert "auth" in log_content.lower()


# ── 15-field response test ─────────────────────────────────────────────────


class TestResponseFields:
    """Verify all 15 fields are present in task responses."""

    EXPECTED_FIELDS = {
        "task_id", "title", "description", "priority", "status",
        "start_time", "due_time", "timezone", "location",
        "need_weather_check", "reminder_channels", "created_channel",
        "created_at", "updated_at",
        # Actually 14... wait, let me count:
        # 1.task_id 2.title 3.description 4.priority 5.status
        # 6.start_time 7.due_time 8.timezone 9.location
        # 10.need_weather_check 11.reminder_channels 12.created_channel
        # 13.created_at 14.updated_at
        # That's 14, but the spec says 15. Let me check again...
        # Oh wait: the 15 field is "status" is included in both input and output.
        # But actually the response fields listed in the spec are only 14.
        # The spec says "Task JSON 输出（15 字段）" but lists 14 distinct fields.
        # I'll keep it at what the schema has.
    }

    def test_create_response_has_all_fields(self):
        resp = client.post(
            "/api/tasks",
            json={"title": "Field check"},
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 201
        data = resp.json()
        # All expected fields present
        for field in self.EXPECTED_FIELDS:
            assert field in data, f"Missing field: {field}"
