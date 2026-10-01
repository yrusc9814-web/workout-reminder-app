from datetime import date
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


APP_DIR = Path(__file__).resolve().parents[1]


def test_health_endpoint_exists(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_returns_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "轻动日记" in response.text
    assert "v25" in response.text
    assert "今日训练" in response.text
    assert 'id="startTodayBtn"' in response.text


def test_today_endpoint_exists_and_returns_shape(client):
    response = client.get("/api/today")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"date", "id", "title", "theme", "notes", "type", "is_training", "template_id", "items"}


def test_month_accepts_legacy_year_month_parameters(client):
    response = client.get("/api/plans/month", params={"year": 2026, "month": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_month_accepts_yyyy_mm_query_token_on_same_url(client):
    response = client.get("/api/plans/month", params={"month": "2026-05"})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_month_summary_accepts_yyyy_mm_token(client):
    response = client.get("/api/plans/month/summary", params={"month": "2026-05"})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_month_rejects_missing_year(client):
    response = client.get("/api/plans/month", params={"month": 5})

    assert response.status_code == 422


def test_month_rejects_invalid_yyyy_mm_token(client):
    response = client.get("/api/plans/month", params={"month": "2026/05"})

    assert response.status_code == 422


def test_week_returns_range(client):
    response = client.get("/api/plans/week", params={"date": "2026-05-11"})

    assert response.status_code == 200
    body = response.json()
    assert body["start"] == "2026-05-11"
    assert body["end"] == "2026-05-17"
    assert len(body["days"]) == 7


def test_week_rejects_invalid_date(client):
    response = client.get("/api/plans/week", params={"date": "not-a-date"})

    assert response.status_code == 422


def test_stats_endpoint_exists(client):
    response = client.get("/api/stats")

    assert response.status_code == 200
    body = response.json()
    assert {"plans", "training_days", "rest_days", "completed", "skipped", "postponed"} <= set(body)


def test_stats_month_accepts_yyyy_mm_token(client):
    response = client.get("/api/stats/month", params={"month": "2026-05"})

    assert response.status_code == 200
    body = response.json()
    assert body["month"] == "2026-05"
    assert {"plans", "training_days", "rest_days", "completed", "skipped", "postponed"} <= set(body)


def test_calendar_accepts_legacy_year_month_parameters(client):
    response = client.get("/api/calendar", params={"year": 2026, "month": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_calendar_accepts_yyyy_mm_query_token_on_same_url(client):
    response = client.get("/api/calendar", params={"month": "2026-05"})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_calendar_month_accepts_yyyy_mm_token(client):
    response = client.get("/api/calendar/month", params={"month": "2026-05"})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 5
    assert len(body["days"]) == 31


def test_calendar_rejects_invalid_yyyy_mm_token(client):
    response = client.get("/api/calendar", params={"month": "2026/05"})

    assert response.status_code == 422


def test_settings_roundtrip(client):
    save = client.post("/api/settings", json={"key": "reminder_time", "value": "07:30"})

    assert save.status_code == 200
    assert save.json() == {"key": "reminder_time", "value": "07:30"}

    fetch = client.get("/api/settings")
    assert fetch.status_code == 200
    assert fetch.json()["settings"]["reminder_time"] == "07:30"


@pytest.mark.parametrize(
    ("endpoint", "expected_status"),
    [
        ("/api/logs/complete", "completed"),
        ("/api/logs/skip", "skipped"),
        ("/api/logs/postpone", "postponed"),
    ],
)
def test_log_endpoints_share_shape(client, endpoint, expected_status):
    plan = client.get("/api/plans/month", params={"year": 2026, "month": 5}).json()["days"][0]

    response = client.post(endpoint, json={"plan_id": plan["id"], "notes": "test"})

    assert response.status_code == 200
    body = response.json()
    assert body["plan_id"] == plan["id"]
    assert body["action"] == expected_status
    assert body["status"] == expected_status
    assert body["notes"] == "test"


def test_log_returns_404_for_missing_plan(client):
    response = client.post("/api/logs/complete", json={"plan_id": 999999, "notes": "missing"})

    assert response.status_code == 404


def test_seed_database_is_idempotent(app_modules):
    database, _main = app_modules

    db = database.SessionLocal()
    try:
        before = (
            db.query(database.WorkoutPlan).count(),
            db.query(database.WorkoutExercise).count(),
            db.query(database.Setting).count(),
        )
    finally:
        db.close()

    database.seed_database()

    db = database.SessionLocal()
    try:
        after = (
            db.query(database.WorkoutPlan).count(),
            db.query(database.WorkoutExercise).count(),
            db.query(database.Setting).count(),
        )
    finally:
        db.close()

    assert after == before


def test_seed_includes_future_months_without_changing_may(app_modules):
    database, _main = app_modules

    db = database.SessionLocal()
    try:
        may_training_dates = {
            row.plan_date
            for row in db.query(database.WorkoutPlan)
            .filter(
                database.WorkoutPlan.plan_date >= date(2026, 5, 1),
                database.WorkoutPlan.plan_date <= date(2026, 5, 31),
                database.WorkoutPlan.is_training_day == True,
            )
            .all()
        }
        assert may_training_dates == {
            date(2026, 5, 1),
            date(2026, 5, 4),
            date(2026, 5, 6),
            date(2026, 5, 8),
            date(2026, 5, 11),
            date(2026, 5, 13),
            date(2026, 5, 15),
            date(2026, 5, 18),
            date(2026, 5, 20),
            date(2026, 5, 22),
            date(2026, 5, 25),
            date(2026, 5, 27),
            date(2026, 5, 29),
        }

        assert db.query(database.WorkoutPlan).count() == 123
        assert (
            db.query(database.WorkoutPlan)
            .filter(database.WorkoutPlan.is_training_day == True)
            .count()
            == 53
        )
        assert db.query(database.WorkoutExercise).count() == 265

        expected_training_days = {6: 13, 7: 14, 8: 13}
        for month, expected_count in expected_training_days.items():
            month_start = date(2026, month, 1)
            month_end = date(2026, month, 30 if month in {6} else 31)
            training_days = (
                db.query(database.WorkoutPlan)
                .filter(
                    database.WorkoutPlan.plan_date >= month_start,
                    database.WorkoutPlan.plan_date <= month_end,
                    database.WorkoutPlan.is_training_day == True,
                )
                .all()
            )
            assert len(training_days) == expected_count
            assert {row.plan_date.weekday() for row in training_days} <= {0, 2, 4}
    finally:
        db.close()


def test_future_month_api_returns_seeded_june_plan(client):
    response = client.get("/api/plans/month", params={"month": "2026-06"})

    assert response.status_code == 200
    body = response.json()
    assert body["year"] == 2026
    assert body["month"] == 6
    assert len(body["days"]) == 30
    training_days = [day for day in body["days"] if day["is_training"]]
    assert len(training_days) == 13
    assert training_days[0]["date"] == "2026-06-01"
    assert training_days[0]["type"] == "training"
    assert len(training_days[0]["items"]) == 5


def test_today_returns_plan_on_mocked_future_training_day(app_modules, monkeypatch):
    _database, main = app_modules

    class MockDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 1)

    monkeypatch.setattr(main, "date", MockDate)

    with TestClient(main.app) as test_client:
        response = test_client.get("/api/today")

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-06-01"
    assert body["is_training"] is True
    assert body["type"] == "training"
    assert body["id"] is not None
    assert len(body["items"]) == 5


def test_deprecated_mock_reminder_routes_are_removed_but_real_dingtalk_remains(client):
    mock_test = client.post("/api/reminders/test", json={"title": "x", "message": "y"})
    wechat = client.post("/api/reminders/wechat/send", json={"title": "x", "message": "y"})
    dingtalk = client.post("/api/reminders/dingtalk/send", json={"title": "x", "message": "y"})

    assert mock_test.status_code == 404
    assert wechat.status_code == 404
    assert dingtalk.status_code == 200
    assert dingtalk.json()["status"] == "not_sent"


def june_training_plan(client):
    month = client.get("/api/plans/month", params={"month": "2026-06"})
    assert month.status_code == 200
    return next(day for day in month.json()["days"] if day["is_training"])


def test_training_items_include_video_links(client):
    plan = june_training_plan(client)

    assert plan["items"]
    assert all(item["video_url"].startswith("https://") for item in plan["items"])
    assert all(
        "bilibili.com" in item["video_url"] or "b23.tv" in item["video_url"]
        for item in plan["items"]
    )
    assert "youtube" not in json.dumps(plan, ensure_ascii=False).lower()


def test_dingtalk_reminder_not_configured_returns_payload_with_video_links(client, monkeypatch):
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)
    plan = june_training_plan(client)

    response = client.post("/api/reminders/dingtalk/send", json={"plan_id": plan["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["channel"] == "dingtalk"
    assert body["status"] == "not_configured"
    assert body["mock"] is False
    assert body["sent"] is False
    assert body["payload"]["title"] == f"【待办】{plan['title']}"
    assert f"【待办】{plan['title']}" in body["payload"]["text"]
    assert f"训练日期：{plan['date']}" in body["payload"]["text"]
    assert "训练动作：" in body["payload"]["text"]
    assert "完成后在群里回复“已完成”" in body["payload"]["text"]
    for item in plan["items"]:
        assert item["video_url"] in body["payload"]["text"]


def test_dingtalk_todo_not_configured_returns_payload_with_video_links(client, monkeypatch):
    monkeypatch.delenv("DINGTALK_TODO_CREATE_URL", raising=False)
    monkeypatch.delenv("DINGTALK_ACCESS_TOKEN", raising=False)
    plan = june_training_plan(client)

    response = client.post("/api/todos/dingtalk/create", json={"plan_id": plan["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["channel"] == "dingtalk_todo"
    assert body["status"] == "not_configured"
    assert body["created"] is False
    assert body["payload"]["subject"] == f"训练计划：{plan['title']}"
    assert plan["title"] in body["payload"]["description"]
    for item in plan["items"]:
        assert item["video_url"] in body["payload"]["description"]


def test_dingtalk_todo_uses_dingtalk_access_token_header(client, monkeypatch):
    captured = {}

    def fake_post_json(url, payload, headers=None):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return 200, "{}"

    monkeypatch.setenv("DINGTALK_TODO_CREATE_URL", "https://api.dingtalk.example/todos")
    monkeypatch.setenv("DINGTALK_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr("main.post_json", fake_post_json)
    plan = june_training_plan(client)

    response = client.post("/api/todos/dingtalk/create", json={"plan_id": plan["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert captured["url"] == "https://api.dingtalk.example/todos"
    assert captured["headers"] == {"x-acs-dingtalk-access-token": "test-token"}
    assert captured["payload"]["subject"] == f"训练计划：{plan['title']}"
    assert "Authorization" not in captured["headers"]


def test_dingtalk_todo_permission_denied_returns_clear_status(client, monkeypatch):
    def fake_post_json(url, payload, headers=None):
        return {
            "http_status": 403,
            "response_body": json.dumps(
                {
                    "code": "Forbidden.AccessDenied.AccessTokenPermissionDenied",
                    "message": "应用尚未开通所需的权限：[Todo.PersonalTodo.Write]",
                }
            ),
            "request_url": url,
            "request_headers": {"x-acs-dingtalk-access-token": "***"},
            "request_body": payload,
            "response_headers": {"x-acs-request-id": "req-403"},
            "request_id": "req-403",
        }

    monkeypatch.setenv("DINGTALK_TODO_CREATE_URL", "https://api.dingtalk.example/todos")
    monkeypatch.setenv("DINGTALK_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr("main.post_json", fake_post_json)
    plan = june_training_plan(client)

    response = client.post("/api/todos/dingtalk/create", json={"plan_id": plan["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "todo_unavailable_due_to_permission"
    assert body["created"] is False
    assert body["enabled"] is True
    assert body["permission"] == "Todo.PersonalTodo.Write"
    assert body["debug_trace"]["request_url"] == "https://api.dingtalk.example/todos"
    assert body["debug_trace"]["request_headers"]["x-acs-dingtalk-access-token"] == "***"
    assert body["debug_trace"]["response_status"] == 403
    assert body["debug_trace"]["request_id"] == "req-403"
    assert body["error_type"] == "api"


def test_dingtalk_todo_network_failure_returns_debug_trace(client, monkeypatch):
    def fake_post_json(url, payload, headers=None):
        raise RuntimeError(
            json.dumps(
                {
                    "error": "钉钉请求失败：timed out",
                    "error_type": "network",
                    "debug_trace": {
                        "request_url": url,
                        "request_headers": {"x-acs-dingtalk-access-token": "***"},
                        "request_body": payload,
                        "response_status": None,
                        "response_body": "",
                        "request_id": None,
                    },
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setenv("DINGTALK_TODO_CREATE_URL", "https://api.dingtalk.example/todos")
    monkeypatch.setenv("DINGTALK_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr("main.post_json", fake_post_json)
    plan = june_training_plan(client)

    response = client.post("/api/todos/dingtalk/create", json={"plan_id": plan["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_type"] == "network"
    assert body["debug_trace"]["request_url"] == "https://api.dingtalk.example/todos"
    assert body["debug_trace"]["request_headers"]["x-acs-dingtalk-access-token"] == "***"
    assert body["debug_trace"]["response_status"] is None


# ── AI 辅助能力测试 ───────────────────────────────────────────────────────


def test_ai_health_unconfigured(client, monkeypatch):
    monkeypatch.delenv("WORKOUT_AI_BASE_URL", raising=False)
    monkeypatch.delenv("WORKOUT_AI_API_KEY", raising=False)

    response = client.get("/api/ai/health")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["provider"] == "openai-compatible"
    assert body["model"] == ""
    assert body["key_configured"] is False
    assert "未配置" in body["message"]


def test_ai_health_configured(client, monkeypatch):
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "sk-test")
    monkeypatch.setenv("WORKOUT_AI_MODEL", "gpt-4o-mini")

    response = client.get("/api/ai/health")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["key_configured"] is True
    assert body["model"] == "gpt-4o-mini"
    assert "已配置" in body["message"]


def test_ai_import_plan_no_key_returns_fallback(client, monkeypatch):
    for name in [
        "WORKOUT_AI_BASE_URL", "WORKOUT_AI_API_KEY", "WORKOUT_AI_MODEL",
        "OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL",
        "DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL",
        "WUAPI_BASE_URL", "WUAPI_API_KEY", "WUAPI_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)

    response = client.post("/api/ai/import-plan", json={"prompt": "生成一份核心训练"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fallback"
    assert body["ai_enabled"] is False
    assert "bilibili.com" in body["fallback"]["search_url"]


VALID_DRAFT_JSON = json.dumps({
    "version": "1.0",
    "source": "ai_generated",
    "title": "核心训练",
    "theme": "核心控制",
    "recommendedDate": "2026-06-22",
    "exercises": [
        {
            "id": "pelvic_tilt",
            "name": "仰卧骨盆后倾",
            "category": "核心控制",
            "bodyParts": ["核心"],
            "difficulty": "低",
            "defaultSets": 3,
            "defaultReps": "12次",
            "durationSeconds": None,
            "notes": "核心激活",
            "tips": ["慢一点"],
            "videos": [{"id": "v1", "title": "教学", "platform": "bilibili", "url": "https://www.bilibili.com/video/BV1xx", "isDefault": True, "remark": ""}],
        }
    ],
    "templates": [
        {"id": "core_a", "name": "核心A", "description": "", "exerciseIds": ["pelvic_tilt"]}
    ],
    "schedule": {
        "2026-06-22": {"type": "training", "templateId": "core_a", "status": "pending", "note": ""},
    },
})


def test_ai_import_plan_valid_draft(client, monkeypatch):
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "sk-test")

    def mock_call(base_url, api_key, model, system_prompt, user_prompt, timeout=60):
        return VALID_DRAFT_JSON

    monkeypatch.setattr("main._call_ai_chat", mock_call)

    response = client.post("/api/ai/import-plan", json={
        "prompt": "核心训练",
        "current_data": {"exercises": [], "templates": [], "schedule": {}},
    })

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert "draft" in body
    assert isinstance(body["draft"]["exercises"], list)
    assert isinstance(body["draft"]["templates"], list)
    assert isinstance(body["draft"]["plans"], list)
    assert len(body["draft"]["exercises"]) == 1
    assert len(body["draft"]["templates"]) == 1
    assert len(body["draft"]["plans"]) == 1
    assert body["draft"]["plans"][0]["date"] == "2026-06-22"
    assert body["draft"]["plans"][0]["type"] == "training"
    assert body["warnings"] == []


def test_ai_import_plan_non_json_returns_422(client, monkeypatch):
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "sk-test")

    def mock_call(base_url, api_key, model, system_prompt, user_prompt, timeout=60):
        return "这不是 JSON"

    monkeypatch.setattr("main._call_ai_chat", mock_call)

    response = client.post("/api/ai/import-plan", json={"prompt": "核心训练"})

    assert response.status_code == 422
    assert "不是合法 JSON" in response.json()["detail"]


def test_ai_import_plan_structural_error_returns_422(client, monkeypatch):
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "sk-test")

    def mock_call(base_url, api_key, model, system_prompt, user_prompt, timeout=60):
        return json.dumps({
            "version": "1.0",
            "exercises": [],  # 空 — 结构错误
            "templates": [],
            "schedule": {},
        })

    monkeypatch.setattr("main._call_ai_chat", mock_call)

    response = client.post("/api/ai/import-plan", json={"prompt": "核心训练"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "校验失败" in detail
    assert "至少需要 1 个动作" in detail


def test_ai_import_plan_handles_schedule_to_plans(client, monkeypatch):
    """测试 schedule 正确转换为 plans 数组。"""
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "sk-test")

    draft = json.loads(VALID_DRAFT_JSON)
    draft["schedule"]["2026-06-23"] = {"type": "rest", "status": "pending", "note": "休息"}

    def mock_call(base_url, api_key, model, system_prompt, user_prompt, timeout=60):
        return json.dumps(draft)

    monkeypatch.setattr("main._call_ai_chat", mock_call)

    response = client.post("/api/ai/import-plan", json={"prompt": "核心训练"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["draft"]["plans"]) == 2
    assert body["draft"]["plans"][0]["date"] == "2026-06-22"
    assert body["draft"]["plans"][1]["date"] == "2026-06-23"
    assert body["draft"]["plans"][1]["type"] == "rest"


def test_ai_suggest_bilibili_no_key_fallback(client, monkeypatch):
    for name in [
        "WORKOUT_AI_BASE_URL", "WORKOUT_AI_API_KEY", "WORKOUT_AI_MODEL",
        "OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL",
        "DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL",
        "WUAPI_BASE_URL", "WUAPI_API_KEY", "WUAPI_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)

    response = client.post("/api/ai/suggest-bilibili-video", json={
        "exercise_name": "平板支撑",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fallback"
    assert body["ai_enabled"] is False
    assert "bilibili.com" in body["search_url"]


def test_ai_suggest_bilibili_valid(client, monkeypatch):
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "sk-test")

    def mock_call(base_url, api_key, model, system_prompt, user_prompt, timeout=60):
        return json.dumps({
            "keywords": ["平板支撑 教学"],
            "searchUrls": ["https://search.bilibili.com/all?keyword=平板支撑"],
            "recommendedTitle": "平板支撑标准动作教学",
            "note": "初学者建议从30秒开始",
        })

    monkeypatch.setattr("main._call_ai_chat", mock_call)

    response = client.post("/api/ai/suggest-bilibili-video", json={
        "exercise_name": "平板支撑",
        "description": "核心训练动作",
        "notes": "30秒一组",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["query"] == "平板支撑 教学"
    assert "bilibili.com" in body["search_url"]
    assert isinstance(body["candidates"], list)
    assert len(body["candidates"]) == 1


def test_ai_suggest_bilibili_rejects_youtube(client, monkeypatch):
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "sk-test")

    def mock_call(base_url, api_key, model, system_prompt, user_prompt, timeout=60):
        return json.dumps({
            "keywords": ["plank"],
            "searchUrls": ["https://www.youtube.com/watch?v=xxx"],
            "recommendedTitle": "",
            "note": "",
        })

    monkeypatch.setattr("main._call_ai_chat", mock_call)

    response = client.post("/api/ai/suggest-bilibili-video", json={
        "exercise_name": "plank",
    })

    assert response.status_code == 422
    assert "非 Bilibili" in response.json()["detail"]


def test_validate_bilibili_url_pure():
    """纯函数校验：白名单通过，YouTube 拒绝。"""
    from main import _validate_bilibili_url

    # 白名单通过
    assert _validate_bilibili_url("https://www.bilibili.com/video/BV1xx")
    assert _validate_bilibili_url("https://bilibili.com/video/BV1xx")
    assert _validate_bilibili_url("https://b23.tv/xxx")

    # 拒绝
    assert not _validate_bilibili_url("")
    assert not _validate_bilibili_url(None)
    assert not _validate_bilibili_url("https://www.youtube.com/watch?v=xxx")
    assert not _validate_bilibili_url("https://youtu.be/xxx")
    assert not _validate_bilibili_url("https://m.youtube.com/xxx")
    assert not _validate_bilibili_url("https://example.com/video")


def test_validate_ai_draft_pure():
    """纯函数校验：合法草稿通过，非 JSON 拒绝。"""
    from main import _validate_ai_draft

    # 不是字典
    errors = _validate_ai_draft("not a dict")
    assert len(errors) > 0

    # 空字典 - 缺少很多东西
    errors = _validate_ai_draft({})
    assert len(errors) > 0

    # 缺少 exercises
    errors = _validate_ai_draft({"version": "1.0"})
    assert any("exercises" in e for e in errors)


# ── Exercise Library CRUD ───────────────────────────────────────────────────


def test_exercise_list_empty_when_no_data(client):
    """新数据库应返回空动作列表。"""
    response = client.get("/api/exercises")
    assert response.status_code == 200
    body = response.json()
    assert "exercises" in body
    assert isinstance(body["exercises"], list)


def test_exercise_create_and_read(client):
    """创建动作并读取。"""
    payload = {"name": "测试动作", "category": "核心控制", "difficulty": "低", "default_sets": 3}
    create = client.post("/api/exercises", json=payload)
    assert create.status_code == 201
    created = create.json()
    assert created["name"] == "测试动作"
    assert created["id"] > 0

    # 读取
    get = client.get(f"/api/exercises/{created['id']}")
    assert get.status_code == 200
    assert get.json()["name"] == "测试动作"

    # 列表包含新动作
    lst = client.get("/api/exercises")
    ids = [e["id"] for e in lst.json()["exercises"]]
    assert created["id"] in ids


def test_exercise_update(client):
    """更新动作字段。"""
    payload = {"name": "原名称", "category": "核心", "difficulty": "低", "default_sets": 2}
    create = client.post("/api/exercises", json=payload)
    uid = create.json()["id"]

    update_payload = {"name": "新名称", "category": "髋部", "difficulty": "中", "default_sets": 3}
    update = client.put(f"/api/exercises/{uid}", json=update_payload)
    assert update.status_code == 200
    assert update.json()["name"] == "新名称"
    assert update.json()["category"] == "髋部"


def test_exercise_delete(client):
    """删除动作。"""
    payload = {"name": "待删除", "category": "测试", "difficulty": "低", "default_sets": 1}
    create = client.post("/api/exercises", json=payload)
    uid = create.json()["id"]

    delete = client.delete(f"/api/exercises/{uid}")
    assert delete.status_code == 200
    assert delete.json()["status"] == "deleted"

    get = client.get(f"/api/exercises/{uid}")
    assert get.status_code == 404


def test_exercise_get_404(client):
    """获取不存在的动作返回 404。"""
    response = client.get("/api/exercises/999999")
    assert response.status_code == 404


def test_exercise_created_with_video_url(client):
    """创建动作时可以设置 Bilibili 视频 URL。"""
    payload = {"name": "带视频动作", "category": "核心", "difficulty": "低", "default_sets": 3, "video_url": "https://www.bilibili.com/video/BV1xx"}
    create = client.post("/api/exercises", json=payload)
    assert create.status_code == 201
    assert create.json()["video_url"] == "https://www.bilibili.com/video/BV1xx"


# ── Template CRUD ────────────────────────────────────────────────────────────


def test_template_list_empty_when_no_data(client):
    """新数据库应返回空模板列表。"""
    response = client.get("/api/templates")
    assert response.status_code == 200
    body = response.json()
    assert "templates" in body


def test_template_create_with_exercises(client):
    """创建模板并关联动作。"""
    ex1 = client.post("/api/exercises", json={"name": "动作1", "category": "核心", "difficulty": "低", "default_sets": 3}).json()
    ex2 = client.post("/api/exercises", json={"name": "动作2", "category": "髋部", "difficulty": "低", "default_sets": 2}).json()

    payload = {"name": "测试模板", "description": "一个测试模板", "difficulty": "低强度", "estimated_minutes": 30, "exercise_ids": [ex1["id"], ex2["id"]]}
    create = client.post("/api/templates", json=payload)
    assert create.status_code == 201
    created = create.json()
    assert created["name"] == "测试模板"
    assert len(created["exercises"]) == 2

    # 读取
    get = client.get(f"/api/templates/{created['id']}")
    assert get.status_code == 200
    assert get.json()["name"] == "测试模板"


def test_template_update(client):
    """更新模板名称和关联动作。"""
    ex = client.post("/api/exercises", json={"name": "E1", "category": "核心", "difficulty": "低", "default_sets": 3}).json()
    tmpl = client.post("/api/templates", json={"name": "旧模板", "description": "", "exercise_ids": [ex["id"]]}).json()

    update = client.put(f"/api/templates/{tmpl['id']}", json={"name": "新模板", "description": "更新描述", "difficulty": "低强度", "estimated_minutes": 40, "exercise_ids": []})
    assert update.status_code == 200
    assert update.json()["name"] == "新模板"
    assert update.json()["description"] == "更新描述"
    assert update.json()["estimated_minutes"] == 40


def test_template_delete(client):
    """删除模板。"""
    ex = client.post("/api/exercises", json={"name": "E", "category": "核心", "difficulty": "低", "default_sets": 3}).json()
    tmpl = client.post("/api/templates", json={"name": "待删除模板", "description": "", "exercise_ids": [ex["id"]]}).json()

    delete = client.delete(f"/api/templates/{tmpl['id']}")
    assert delete.status_code == 200
    assert delete.json()["status"] == "deleted"

    get = client.get(f"/api/templates/{tmpl['id']}")
    assert get.status_code == 404


def test_template_get_404(client):
    """获取不存在的模板返回 404。"""
    response = client.get("/api/templates/999999")
    assert response.status_code == 404


# ── Training Completion ──────────────────────────────────────────────────────


def test_training_complete_records_log(client):
    """训练完成记录到后端，自动查找当日计划。"""
    response = client.post("/api/training/complete", json={
        "date": "2026-06-01",
        "template_id": 1,
        "completed": ["动作1", "动作2"],
        "skipped": [],
        "status": "done",
        "notes": "完成训练",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "recorded"
    assert body["log_id"] > 0
    assert len(body["completed"]) == 2
    assert len(body["skipped"]) == 0


def test_training_complete_with_skipped(client):
    """跳过动作的训练记录。"""
    response = client.post("/api/training/complete", json={
        "date": "2026-06-03",
        "completed": [],
        "skipped": ["动作1"],
        "status": "partial",
        "notes": "跳过大部分动作",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "recorded"
    assert len(body["skipped"]) == 1


def test_training_complete_rejects_bad_date(client):
    """无效日期格式返回 422。"""
    response = client.post("/api/training/complete", json={
        "date": "not-a-date",
        "status": "done",
    })
    assert response.status_code == 422


def test_training_complete_appears_in_logs(client):
    """训练完成记录出现在日志列表中。"""
    client.post("/api/training/complete", json={
        "date": "2026-06-05",
        "completed": ["动作1"],
        "skipped": [],
        "status": "done",
    })
    response = client.get("/api/logs")
    assert response.status_code == 200
    logs = response.json()["logs"]
    assert any(log["action"] == "completed" for log in logs)


# ── Plan Update ──────────────────────────────────────────────────────────────


def test_plan_update_title(client):
    """更新计划的主题字段。"""
    plan = client.get("/api/plans/month", params={"month": "2026-06"}).json()["days"][0]
    pid = plan["id"]
    assert pid is not None

    update = client.put(f"/api/plans/{pid}", json={"title": "修改后的训练计划", "focus": "高强度"})
    assert update.status_code == 200
    assert update.json()["title"] == "修改后的训练计划"

    # 验证持久化
    get = client.get("/api/plans/month", params={"month": "2026-06"})
    updated = next(d for d in get.json()["days"] if d["id"] == pid)
    assert updated["title"] == "修改后的训练计划"
    assert updated["theme"] == "高强度"


def test_plan_update_404(client):
    """更新不存在的计划返回 404。"""
    response = client.put("/api/plans/999999", json={"title": "无"})
    assert response.status_code == 404


def test_plan_update_training_day(client):
    """切换训练日状态。"""
    plan = client.get("/api/plans/month", params={"month": "2026-06"}).json()["days"][0]
    pid = plan["id"]
    original = plan["is_training"]

    update = client.put(f"/api/plans/{pid}", json={"is_training_day": not original})
    assert update.status_code == 200
    assert update.json()["is_training"] == (not original)


# ── Stats Consistency ─────────────────────────────────────────────────────────


def test_stats_reflects_training_logs(client):
    """记录训练完成后统计数据更新。"""
    before = client.get("/api/stats/month", params={"month": "2026-06"}).json()
    before_completed = before["completed"]

    # 找到一个训练日
    month = client.get("/api/plans/month", params={"month": "2026-06"}).json()
    training_day = next(d for d in month["days"] if d["is_training"])
    client.post("/api/logs/complete", json={"plan_id": training_day["id"], "notes": "测试"})

    after = client.get("/api/stats/month", params={"month": "2026-06"}).json()
    assert after["completed"] == before_completed + 1


def test_stats_overall_matches_month_sum(client):
    """整体统计与各月统计之和一致。"""
    overall = client.get("/api/stats").json()
    june = client.get("/api/stats/month", params={"month": "2026-06"}).json()

    assert overall["plans"] >= june["plans"]
    assert overall["training_days"] >= june["training_days"]


# ── Real AI Assistant ───────────────────────────────────────────────────────


def _valid_ai_draft():
    return {
        "version": "1.0",
        "source": "ai_generated",
        "title": "核心稳定训练",
        "theme": "核心控制",
        "recommendedDate": "2026-06-15",
        "exercises": [
            {
                "id": "dead_bug_ai",
                "name": "死虫训练",
                "category": "核心控制",
                "bodyParts": ["核心"],
                "difficulty": "低",
                "defaultSets": 3,
                "defaultReps": "10次/侧",
                "durationSeconds": None,
                "notes": "保持腰背贴地",
                "tips": ["慢速控制"],
                "videos": [
                    {
                        "id": "video_dead_bug_ai",
                        "title": "死虫训练 B站搜索",
                        "platform": "bilibili",
                        "url": "https://search.bilibili.com/all?keyword=%E6%AD%BB%E8%99%AB%E8%AE%AD%E7%BB%83",
                        "isDefault": True,
                        "remark": "AI 建议搜索词",
                    }
                ],
            }
        ],
        "templates": [
            {
                "id": "core_ai_template",
                "name": "核心稳定训练",
                "description": "AI 生成草稿，需用户确认后导入",
                "exerciseIds": ["dead_bug_ai"],
                "difficulty": "低强度",
                "estimatedMinutes": 25,
            }
        ],
        "schedule": {
            "2026-06-15": {
                "type": "training",
                "templateId": "core_ai_template",
                "status": "pending",
                "note": "注意腰背稳定",
            }
        },
    }


def test_ai_health_unconfigured_reports_disabled(client, monkeypatch):
    for name in [
        "WORKOUT_AI_API_KEY", "WORKOUT_AI_BASE_URL", "WORKOUT_AI_MODEL",
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
        "WUAPI_API_KEY", "WUAPI_BASE_URL", "WUAPI_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)

    response = client.get("/api/ai/health")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["key_configured"] is False
    assert body["base_url"] == ""
    assert "api_key" not in body


def test_ai_health_deepseek_env_uses_safe_defaults(client, monkeypatch):
    monkeypatch.delenv("WORKOUT_AI_API_KEY", raising=False)
    monkeypatch.delenv("WORKOUT_AI_BASE_URL", raising=False)
    monkeypatch.delenv("WORKOUT_AI_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-key")

    response = client.get("/api/ai/health")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["model"] == "deepseek-v4-flash"
    assert body["base_url"] == "api.deepseek.com"
    assert "test-secret-key" not in json.dumps(body, ensure_ascii=False)


def test_ai_import_plan_calls_openai_compatible_backend(app_modules, client, monkeypatch):
    _database, main = app_modules
    captured = {}

    def fake_call(base_url, api_key, model, system_prompt, user_prompt, timeout=60):
        captured.update({
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "timeout": timeout,
        })
        return json.dumps(_valid_ai_draft(), ensure_ascii=False)

    monkeypatch.setenv("WORKOUT_AI_API_KEY", "test-secret-key")
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://ai.example.test/v1")
    monkeypatch.setenv("WORKOUT_AI_MODEL", "deepseek-v4-flash")
    monkeypatch.setattr(main, "_call_ai_chat", fake_call)

    response = client.post("/api/ai/analyze", json={"prompt": "生成核心训练"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["ai_enabled"] is True
    assert body["draft"]["exercises"][0]["name"] == "死虫训练"
    assert body["draft"]["plans"][0]["date"] == "2026-06-15"
    assert captured["base_url"] == "https://ai.example.test/v1"
    assert captured["api_key"] == "test-secret-key"
    assert captured["model"] == "deepseek-v4-flash"
    assert "Bilibili" in captured["system_prompt"] or "bilibili" in captured["system_prompt"]


def test_ai_import_plan_rejects_youtube_from_model(app_modules, client, monkeypatch):
    _database, main = app_modules
    draft = _valid_ai_draft()
    draft["exercises"][0]["videos"][0]["url"] = "https://youtu.be/not-allowed"

    monkeypatch.setenv("WORKOUT_AI_API_KEY", "test-secret-key")
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://ai.example.test/v1")
    monkeypatch.setattr(main, "_call_ai_chat", lambda *args, **kwargs: json.dumps(draft, ensure_ascii=False))

    response = client.post("/api/ai/import-plan", json={"prompt": "生成训练"})

    assert response.status_code == 422
    assert "非 Bilibili" in response.json()["detail"] or "Bilibili" in response.json()["detail"]


def test_ai_import_plan_rejects_non_json_model_output(app_modules, client, monkeypatch):
    _database, main = app_modules
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "test-secret-key")
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://ai.example.test/v1")
    monkeypatch.setattr(main, "_call_ai_chat", lambda *args, **kwargs: "不是 JSON")

    response = client.post("/api/ai/import-plan", json={"prompt": "生成训练"})

    assert response.status_code == 422
    assert "不是合法 JSON" in response.json()["detail"]


def test_ai_import_plan_rejects_missing_required_fields(app_modules, client, monkeypatch):
    _database, main = app_modules
    draft = _valid_ai_draft()
    draft.pop("title")

    monkeypatch.setenv("WORKOUT_AI_API_KEY", "test-secret-key")
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://ai.example.test/v1")
    monkeypatch.setattr(main, "_call_ai_chat", lambda *args, **kwargs: json.dumps(draft, ensure_ascii=False))

    response = client.post("/api/ai/import-plan", json={"prompt": "生成训练"})

    assert response.status_code == 422
    assert "title" in response.json()["detail"]


def test_ai_unconfigured_returns_bilibili_fallback_preview(client, monkeypatch):
    for name in [
        "WORKOUT_AI_API_KEY", "WORKOUT_AI_BASE_URL", "WORKOUT_AI_MODEL",
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
        "WUAPI_API_KEY", "WUAPI_BASE_URL", "WUAPI_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)

    response = client.post("/api/ai/analyze", json={"prompt": "死虫训练"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fallback"
    assert body["ai_enabled"] is False
    assert "search.bilibili.com" in body["fallback"]["search_url"]
    assert body["draft"] is None


def test_exercises_table_seeded_correctly(app_modules):
    """验证新增的 Exercise/Template 表初始化正确。"""
    database, _ = app_modules
    db = database.SessionLocal()
    try:
        ex_count = db.query(database.Exercise).count()
        tmpl_count = db.query(database.Template).count()
        assert ex_count == 5
        assert tmpl_count == 1

        tmpl = db.query(database.Template).first()
        assert tmpl is not None
        assert len(tmpl.exercises) == 5
    finally:
        db.close()


def test_seed_exercise_library_is_idempotent(app_modules):
    """Exercise/Template 种子数据是幂等的。"""
    database, _ = app_modules
    database.seed_database()

    db = database.SessionLocal()
    try:
        assert db.query(database.Exercise).count() == 5
        assert db.query(database.Template).count() == 1
    finally:
        db.close()


# ── Gate 0 new tests ─────────────────────────────────────────────────────────


def test_seed_does_not_overwrite_user_edit(app_modules, client):
    """用户修改计划后重启 seed 不会覆盖用户编辑。"""
    database, _ = app_modules
    # Change a plan title
    resp = client.get("/api/plans/month?month=2026-05")
    plans = resp.json()["days"]
    plan_05_01 = [d for d in plans if d["date"] == "2026-05-01"][0]
    assert plan_05_01["id"] is not None

    client.put(f"/api/plans/{plan_05_01['id']}", json={"title": "用户自定义标题", "notes": "用户备注"})

    # Re-seed — should NOT overwrite
    database.seed_database()

    # Verify title survived
    resp2 = client.get(f"/api/plans/month?month=2026-05")
    plan_after = [d for d in resp2.json()["days"] if d["date"] == "2026-05-01"][0]
    assert plan_after["title"] == "用户自定义标题"
    assert plan_after["notes"] == "用户备注"


def test_seed_safe_when_db_has_data(app_modules, client):
    """当 DB 已有数据时 seed_database 直接跳过，不抛异常。"""
    database, _ = app_modules
    # DB already has seed data (from fixture)
    db = database.SessionLocal()
    try:
        count_before = db.query(database.WorkoutPlan).count()
        assert count_before > 0
    finally:
        db.close()

    # Call seed again — should be a no-op
    database.seed_database()

    db = database.SessionLocal()
    try:
        count_after = db.query(database.WorkoutPlan).count()
        assert count_after == count_before
    finally:
        db.close()


# ── Gate 1 new tests ─────────────────────────────────────────────────────────


def test_exercise_crud_persists(client):
    """新增动作后重新查询，数据应持久化在 DB 中。"""
    created = client.post("/api/exercises", json={
        "name": "测试动作持久化",
        "category": "测试",
        "difficulty": "低",
        "defaultSets": 3,
        "defaultReps": "10次",
    })
    assert created.status_code == 201
    ex_id = created.json()["id"]

    fetched = client.get(f"/api/exercises/{ex_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "测试动作持久化"


def test_template_crud_persists(client):
    """新建模板后重新查询，数据应持久化。"""
    # First create an exercise
    ex_resp = client.post("/api/exercises", json={
        "name": "模板动作",
        "category": "核心",
        "difficulty": "低",
        "defaultSets": 2,
        "defaultReps": "8次",
    })
    ex_id = ex_resp.json()["id"]

    created = client.post("/api/templates", json={
        "name": "测试模板持久化",
        "description": "测试描述",
        "exercise_ids": [ex_id],
        "estimated_minutes": 20,
    })
    assert created.status_code == 201
    tmpl_id = created.json()["id"]

    fetched = client.get(f"/api/templates/{tmpl_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "测试模板持久化"
    assert len(fetched.json()["exercises"]) == 1


def test_plan_update_persists(client):
    """更新计划标题后重新查询，数据应持久化。"""
    resp = client.get("/api/plans/month?month=2026-06")
    plan = [d for d in resp.json()["days"] if d["id"] is not None][0]

    updated = client.put(f"/api/plans/{plan['id']}", json={"title": "持久化测试标题"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "持久化测试标题"

    fetched = client.get("/api/plans/month?month=2026-06")
    plan_after = [d for d in fetched.json()["days"] if d["id"] == plan["id"]][0]
    assert plan_after["title"] == "持久化测试标题"


# ── Gate 2 new tests (session state machine) ─────────────────────────────────


def test_session_complete_is_idempotent(client, app_modules):
    """重复调用 session/complete 应返回 already_completed，不重复创建 WorkoutLog。"""
    database, _ = app_modules
    # Setup: create exercise, generate plan, start session
    ex = client.post("/api/exercises", json={
        "name": "幂等测试动作", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-20", "title": "幂等", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    started = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    session_id = started.json()["session"]["id"]
    record = started.json()["session"]["records"][0]
    updated = client.post("/api/session/update", json={
        "session_id": session_id, "exercise_id": record["exercise_id"],
        "status": "completed", "sets_completed": 1,
    })
    assert updated.status_code == 200

    # Complete first time
    c1 = client.post("/api/session/complete", json={"session_id": session_id, "rating": 5})
    assert c1.status_code == 200
    assert c1.json()["status"] == "completed"

    # Complete second time — should be idempotent
    c2 = client.post("/api/session/complete", json={"session_id": session_id, "rating": 5})
    assert c2.status_code == 200
    assert c2.json()["status"] == "already_completed"

    # Verify only one WorkoutLog created
    db = database.SessionLocal()
    try:
        logs = db.query(database.WorkoutLog).filter(
            database.WorkoutLog.plan_id == gen.json()["plan"]["id"]
        ).all()
        assert len([l for l in logs if l.action == "completed"]) == 1
    finally:
        db.close()


def test_session_update_rejects_completed(client, app_modules):
    """已完成的 session 不应再接受 update。"""
    database, _ = app_modules
    ex = client.post("/api/exercises", json={
        "name": "拒绝更新测试", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-21", "title": "拒绝更新", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    started = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    session_id = started.json()["session"]["id"]

    client.post("/api/session/update", json={
        "session_id": session_id, "exercise_id": ex.json()["id"],
        "status": "completed", "sets_completed": 1,
    })
    completed = client.post("/api/session/complete", json={"session_id": session_id})
    assert completed.status_code == 200

    # Try to update completed session
    resp = client.post("/api/session/update", json={
        "session_id": session_id, "exercise_id": ex.json()["id"],
        "status": "completed",
    })
    assert resp.status_code == 422


def test_session_update_rejects_non_plan_exercise(client, app_modules):
    """非计划内的动作不应被 session/update 接受。"""
    ex1 = client.post("/api/exercises", json={
        "name": "计划内动作", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    ex2 = client.post("/api/exercises", json={
        "name": "计划外动作", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-22", "title": "归属测试", "theme": "测试", "exerciseIds": [ex1.json()["id"]],
    })
    started = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    session_id = started.json()["session"]["id"]

    # Try to update with exercise NOT in plan
    resp = client.post("/api/session/update", json={
        "session_id": session_id, "exercise_id": ex2.json()["id"],
        "status": "completed",
    })
    assert resp.status_code == 422


def test_session_start_resumes_existing(client):
    """同一 plan 重复调用 session/start 应返回已有活跃会话。"""
    ex = client.post("/api/exercises", json={
        "name": "恢复测试动作", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-23", "title": "恢复", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    s1 = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    s1_id = s1.json()["session"]["id"]

    s2 = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    assert s2.status_code == 200
    assert s2.json()["status"] == "resumed"
    assert s2.json()["session"]["id"] == s1_id


def test_session_cancel_and_current(client):
    """测试 /api/session/cancel 和 /api/session/current。"""
    ex = client.post("/api/exercises", json={
        "name": "取消测试动作", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-24", "title": "取消", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    started = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    session_id = started.json()["session"]["id"]

    # Check current
    cur = client.get(f"/api/session/current?plan_id={gen.json()['plan']['id']}")
    assert cur.status_code == 200
    assert cur.json()["session"]["id"] == session_id

    # Cancel
    cancel = client.post("/api/session/cancel", json={"session_id": session_id})
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    # Current should now be empty
    cur2 = client.get(f"/api/session/current?plan_id={gen.json()['plan']['id']}")
    assert cur2.json()["session"] is None


# ── Gate 3/4 new tests ───────────────────────────────────────────────────────


def test_ai_feedback_persists_to_db(client, app_modules):
    """AI feedback 应真正写入 WorkoutSession。"""
    database, _ = app_modules
    ex = client.post("/api/exercises", json={
        "name": "反馈测试动作", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-25", "title": "反馈", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    started = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    session_id = started.json()["session"]["id"]

    # Submit feedback
    fb = client.post("/api/ai/feedback", json={
        "session_id": session_id, "rating": 4, "comment": "训练感觉不错",
    })
    assert fb.status_code == 200

    # Verify persisted
    db = database.SessionLocal()
    try:
        session = db.query(database.WorkoutSession).filter(
            database.WorkoutSession.id == session_id
        ).first()
        assert session.rating == 4
        assert session.ai_feedback == "训练感觉不错"
    finally:
        db.close()


def test_ai_import_fallback_draft_null(client):
    """AI 未配置时返回 draft:null 和 fallback 状态。"""
    resp = client.post("/api/ai/import-plan", json={
        "prompt": "测试训练计划",
        "current_data": None,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "fallback"
    assert data["draft"] is None
    assert "fallback" in data


def test_restore_defaults_dry_run(client):
    """restore-defaults 在 confirm=false 时不执行，只返回预览。"""
    resp = client.post("/api/data/restore-defaults", json={"confirm": False})
    assert resp.status_code == 200
    assert resp.json()["status"] == "dry_run"


def test_stats_no_duplicate_completion(client):
    """同一 plan 多次 complete 不应导致统计重复。"""
    ex = client.post("/api/exercises", json={
        "name": "统计去重动作", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-26", "title": "统计", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    started = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    session_id = started.json()["session"]["id"]
    client.post("/api/session/update", json={
        "session_id": session_id, "exercise_id": ex.json()["id"],
        "status": "completed", "sets_completed": 1,
    })
    client.post("/api/session/complete", json={"session_id": session_id})
    # Second complete (idempotent)
    client.post("/api/session/complete", json={"session_id": session_id})

    stats = client.get("/api/stats/month?month=2026-06")
    assert stats.status_code == 200
    assert stats.json()["completed"] >= 1
    # Stats should NOT be doubled by idempotent call


# ── Gate 4/5 new tests (migration, template contract, concurrency, terminal states) ──────────────

def test_migration_is_idempotent(app_modules):
    """迁移可重复执行，第二次不改变数据。"""
    database, _ = app_modules
    result1 = database.migrate_database()
    result2 = database.migrate_database()
    assert result2["migrated_workout_exercises"] == 0
    assert result2["migrated_plans"] == 0
    assert result1.get("backup") is not None
    assert result1["backup"]["integrity"] == "ok"


def test_migration_handles_ambiguous_names(app_modules):
    """歧义名称不被错误迁移，保持 NULL。"""
    database, _ = app_modules
    db = database.SessionLocal()
    try:
        # Seed two exercises with the same name (ambiguous)
        a = database.Exercise(name="歧义动作", category="测试", difficulty="低", default_sets=1)
        b = database.Exercise(name="歧义动作", category="测试", difficulty="中", default_sets=2)
        db.add(a)
        db.add(b)
        plan = database.WorkoutPlan(
            plan_date=__import__("datetime").date(2026, 9, 1),
            title="歧义计划",
            is_training_day=True,
            focus="测试",
            notes="",
        )
        db.add(plan)
        db.flush()
        we = database.WorkoutExercise(
            plan_id=plan.id,
            sort_order=1,
            name="歧义动作",
            description="x",
            sets=1,
            exercise_id=None,
        )
        db.add(we)
        db.commit()
        we_id = we.id
    finally:
        db.close()

    result = database.migrate_database()
    assert result["ambiguous_workout_exercises"] >= 1

    db = database.SessionLocal()
    try:
        row = db.query(database.WorkoutExercise).filter(database.WorkoutExercise.id == we_id).one()
        assert row.exercise_id is None
    finally:
        db.close()


def test_concurrent_start_only_one_active_session(app_modules, client):
    """并发 start 只允许一个 active session（DB 唯一索引 + IntegrityError 路径）。"""
    import concurrent.futures
    database, _ = app_modules
    ex = client.post("/api/exercises", json={
        "name": "并发start动作", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "3次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-09-10", "title": "并发start", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    plan_id = gen.json()["plan"]["id"]

    def _start():
        return client.post("/api/session/start", json={"plan_id": plan_id})

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_start) for _ in range(8)]
        results = [f.result() for f in futures]

    assert all(r.status_code == 200 for r in results)
    session_ids = {r.json()["session"]["id"] for r in results}
    assert len(session_ids) == 1

    db = database.SessionLocal()
    try:
        active = db.query(database.WorkoutSession).filter(
            database.WorkoutSession.plan_id == plan_id,
            database.WorkoutSession.status == "in_progress",
        ).count()
        assert active == 1
    finally:
        db.close()


def test_concurrent_dual_complete_one_log(app_modules, client):
    """并发 complete（双入口）只产生一条完成日志。"""
    import concurrent.futures
    database, _ = app_modules
    ex = client.post("/api/exercises", json={
        "name": "并发complete动作", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "3次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-09-11", "title": "并发complete", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    plan = gen.json()["plan"]
    start = client.post("/api/session/start", json={"plan_id": plan["id"]})
    sid = start.json()["session"]["id"]
    rec = start.json()["session"]["records"][0]
    client.post("/api/session/update", json={
        "session_id": sid, "exercise_id": rec["exercise_id"], "status": "completed", "sets_completed": 1,
    })

    def _complete_session():
        return client.post("/api/session/complete", json={"session_id": sid})

    def _complete_training():
        return client.post("/api/training/complete", json={
            "date": "2026-09-11", "status": "done", "completed": [str(rec["exercise_id"])], "skipped": [],
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = []
        for _ in range(3):
            futures.append(pool.submit(_complete_session))
            futures.append(pool.submit(_complete_training))
        results = [f.result() for f in futures]

    assert all(r.status_code == 200 for r in results)
    db = database.SessionLocal()
    try:
        logs = db.query(database.WorkoutLog).filter(
            database.WorkoutLog.plan_id == plan["id"],
            database.WorkoutLog.action == "completed",
        ).all()
        assert len(logs) == 1
    finally:
        db.close()


def test_plan_template_contract_create_and_switch(app_modules, client):
    """计划创建后切换模板，动作同步替换且刷新一致。"""
    database, _ = app_modules
    # Create template 1
    ex1 = client.post("/api/exercises", json={"name": "模板1动作", "category": "测试", "difficulty": "低", "defaultSets": 1, "defaultReps": "5次"})
    ex2 = client.post("/api/exercises", json={"name": "模板2动作", "category": "测试", "difficulty": "低", "defaultSets": 2, "defaultReps": "5次"})
    t1 = client.post("/api/templates", json={"name": "模板A", "exercise_ids": [ex1.json()["id"]], "estimated_minutes": 15})
    t2 = client.post("/api/templates", json={"name": "模板B", "exercise_ids": [ex2.json()["id"]], "estimated_minutes": 20})

    # Generate a plan with template A
    gen = client.post("/api/plans/generate", json={"date": "2026-07-10", "title": "切换测试", "theme": "测试", "exerciseIds": [ex1.json()["id"]]})
    plan_id = gen.json()["plan"]["id"]
    plan1 = client.get(f"/api/plans?date=2026-07-10")
    assert len(plan1.json()["plans"][0]["items"]) >= 1

    # Switch to template B via plan edit
    resp = client.put(f"/api/plans/{plan_id}", json={"template_id": t2.json()["id"]})
    assert resp.status_code == 200
    plan2 = client.get(f"/api/plans?date=2026-07-10")
    items = plan2.json()["plans"][0]["items"]
    assert len(items) >= 1
    # Should now have template B's exercises
    assert plan2.json()["plans"][0]["template_id"] == t2.json()["id"]


def test_plan_template_delete_and_missing(client):
    """模板删除后，计划仍存在且 template_id 被置空，不静默绑定错误模板。"""
    t1 = client.post("/api/templates", json={"name": "待删除模板"})
    ex1 = client.post("/api/exercises", json={"name": "TMP动作", "category": "测试", "difficulty": "低", "defaultSets": 1, "defaultReps": "3次"})
    gen = client.post("/api/plans/generate", json={"date": "2026-07-11", "title": "删除测试", "theme": "测试", "exerciseIds": [ex1.json()["id"]]})
    plan_id = gen.json()["plan"]["id"]
    client.put(f"/api/plans/{plan_id}", json={"template_id": t1.json()["id"]})

    deleted = client.delete(f"/api/templates/{t1.json()['id']}")
    assert deleted.status_code == 200

    plan_resp = client.get("/api/plans?date=2026-07-11")
    assert plan_resp.status_code == 200
    plan = plan_resp.json()["plans"][0]
    assert plan["id"] == plan_id
    assert plan.get("template_id") is None


def test_training_rest_day_conversion(client):
    """训练日↔休息日转换，动作和模板正确清理/生成。"""
    ex1 = client.post("/api/exercises", json={"name": "转换测试", "category": "测试", "difficulty": "低", "defaultSets": 1, "defaultReps": "3次"})
    gen = client.post("/api/plans/generate", json={"date": "2026-07-12", "title": "原始训练", "theme": "测试", "exerciseIds": [ex1.json()["id"]]})
    plan_id = gen.json()["plan"]["id"]

    # Convert to rest day
    resp = client.put(f"/api/plans/{plan_id}", json={"is_training_day": False})
    assert resp.status_code == 200
    assert resp.json()["is_training"] is False
    assert len(resp.json()["items"]) == 0

    # Convert back to training day with template
    t1 = client.post("/api/templates", json={"name": "新模板", "exercise_ids": [ex1.json()["id"]]})
    resp2 = client.put(f"/api/plans/{plan_id}", json={"is_training_day": True, "template_id": t1.json()["id"]})
    assert resp2.status_code == 200
    assert resp2.json()["is_training"] is True
    assert len(resp2.json()["items"]) >= 1


def test_session_terminal_state_cannot_update(client, app_modules):
    """completed/cancelled 会话不得再接受 update。"""
    ex1 = client.post("/api/exercises", json={"name": "终态测试", "category": "测试", "difficulty": "低", "defaultSets": 1, "defaultReps": "3次"})
    gen = client.post("/api/plans/generate", json={"date": "2026-07-13", "title": "终态", "theme": "测试", "exerciseIds": [ex1.json()["id"]]})
    started = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    sid = started.json()["session"]["id"]
    recs = started.json()["session"]["records"]

    # Complete
    client.post("/api/session/update", json={
        "session_id": sid, "exercise_id": recs[0]["exercise_id"],
        "status": "completed", "sets_completed": 1,
    })
    client.post("/api/session/complete", json={"session_id": sid})
    # Try update after complete
    if recs:
        up = client.post("/api/session/update", json={"session_id": sid, "exercise_id": recs[0]["exercise_id"], "status": "completed"})
        assert up.status_code == 422

    # Try cancel after complete
    cancel = client.post("/api/session/cancel", json={"session_id": sid})
    assert cancel.status_code == 422


def test_session_cancelled_cannot_complete(client, app_modules):
    """cancelled 会话不得再完成。"""
    ex1 = client.post("/api/exercises", json={"name": "取消测试", "category": "测试", "difficulty": "低", "defaultSets": 1, "defaultReps": "3次"})
    gen = client.post("/api/plans/generate", json={"date": "2026-07-14", "title": "取消", "theme": "测试", "exerciseIds": [ex1.json()["id"]]})
    started = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    sid = started.json()["session"]["id"]
    client.post("/api/session/cancel", json={"session_id": sid})
    # Try complete after cancel
    compile_resp = client.post("/api/session/complete", json={"session_id": sid})
    assert compile_resp.status_code == 422


def test_duplicate_start_returns_same_session(client, app_modules):
    """同一计划重复 start 返回同一个活动会话。"""
    ex1 = client.post("/api/exercises", json={"name": "重复start", "category": "测试", "difficulty": "低", "defaultSets": 1, "defaultReps": "3次"})
    gen = client.post("/api/plans/generate", json={"date": "2026-07-15", "title": "重复start", "theme": "测试", "exerciseIds": [ex1.json()["id"]]})
    s1 = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    s2 = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    assert s2.json()["session"]["id"] == s1.json()["session"]["id"]


def test_sqlite_backup_integrity(app_modules, tmp_path):
    """SQLite 备份通过 integrity_check。"""
    database, _ = app_modules
    import os
    db_path = os.environ.get("WORKOUT_DB_PATH", database.DATABASE_PATH)
    backup = database.sqlite_backup(db_path, str(tmp_path / "backups"))
    assert backup["integrity"] == "ok"
    assert backup["size_bytes"] > 0
    assert len(backup["sha256"]) == 64


def test_restore_defaults_dry_run_shows_counts(client):
    """restore-defaults dry-run 返回实际计划/动作数量，不显示 ?。"""
    resp = client.post("/api/data/restore-defaults", json={"confirm": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "dry_run"
    assert "current_state" in data
    assert isinstance(data["current_state"].get("plans"), int)
    assert isinstance(data["current_state"].get("exercises"), int)


# ═══════════════════════════════════════════════════════════════════════════════
# Gate 4 — Required new tests (Round 2 targeted fixes)
# ═══════════════════════════════════════════════════════════════════════════════


def test_foreign_keys_enabled_on_session_connection(app_modules):
    """PRAGMA foreign_keys == 1 on a real SQLAlchemy Session connection."""
    database, _ = app_modules
    from sqlalchemy import text
    db = database.SessionLocal()
    try:
        fk = db.execute(text("PRAGMA foreign_keys")).fetchone()[0]
        assert fk == 1, f"Expected foreign_keys=1, got {fk}"
    finally:
        db.close()


def test_seeded_plan_session_update_succeeds(client):
    """session/update works on default seed plan exercises (not just /plans/generate)."""
    plans = client.get("/api/plans/month?month=2026-05").json()
    training_day = next((d for d in plans["days"] if d["is_training"] and d["items"]), None)
    assert training_day is not None, "No seeded training day found for May 2026"

    start = client.post("/api/session/start", json={"plan_id": training_day["id"]})
    assert start.status_code == 200, f"Start failed: {start.json()}"
    recs = start.json()["session"]["records"]
    assert len(recs) > 0, "No session records created"

    eid = recs[0]["exercise_id"]
    assert eid is not None, "Seeded exercise_id should not be None"

    up = client.post("/api/session/update", json={
        "session_id": start.json()["session"]["id"],
        "exercise_id": eid,
        "status": "completed",
    })
    assert up.status_code == 200, f"Seed plan update failed: {up.json()}"
    assert up.json()["record"]["status"] == "completed"


def test_multiset_first_set_update_does_not_500(client):
    """Completing first set of a multi-set exercise returns 200, sets_completed=1."""
    ex = client.post("/api/exercises", json={
        "name": "多组测试", "category": "测试", "difficulty": "低",
        "defaultSets": 3, "defaultReps": "10次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-27", "title": "多组", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    start = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    sid = start.json()["session"]["id"]
    recs = start.json()["session"]["records"]
    eid = recs[0]["exercise_id"]

    # First set (not last) → in_progress maps to pending with sets_completed
    up = client.post("/api/session/update", json={
        "session_id": sid, "exercise_id": eid,
        "status": "in_progress", "sets_completed": 1,
    })
    assert up.status_code == 200, f"First set update returned {up.status_code}: {up.json()}"
    assert up.json()["record"]["status"] == "pending"
    assert up.json()["record"]["sets_completed"] == 1


def test_skipped_exercise_persists(client):
    """Skipping an exercise writes status=skipped to SessionRecord."""
    ex = client.post("/api/exercises", json={
        "name": "跳过测试", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-28", "title": "跳过", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    start = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    sid = start.json()["session"]["id"]
    eid = start.json()["session"]["records"][0]["exercise_id"]

    up = client.post("/api/session/update", json={
        "session_id": sid, "exercise_id": eid, "status": "skipped",
    })
    assert up.status_code == 200
    assert up.json()["record"]["status"] == "skipped"


def test_completed_session_is_not_resumed(client):
    """session/start should NOT resume a completed session."""
    ex = client.post("/api/exercises", json={
        "name": "不恢复测试", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-29", "title": "不恢复", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    s1 = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    sid_completed = s1.json()["session"]["id"]
    client.post("/api/session/update", json={
        "session_id": sid_completed,
        "exercise_id": s1.json()["session"]["records"][0]["exercise_id"],
        "status": "completed", "sets_completed": 1,
    })
    client.post("/api/session/complete", json={"session_id": sid_completed})

    # Try to start again — should create NEW session, not resume completed one
    s2 = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    assert s2.status_code == 200
    assert s2.json()["status"] == "started", f"Expected 'started', got '{s2.json()['status']}'"
    assert s2.json()["session"]["id"] != sid_completed


def test_cancelled_session_is_not_resumed(client):
    """session/start should NOT resume a cancelled session."""
    ex = client.post("/api/exercises", json={
        "name": "取消不恢复测试", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-06-30", "title": "取消不恢复", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    s1 = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    sid_cancelled = s1.json()["session"]["id"]
    client.post("/api/session/cancel", json={"session_id": sid_cancelled})

    s2 = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    assert s2.status_code == 200
    assert s2.json()["status"] == "started", f"Expected 'started', got '{s2.json()['status']}'"
    assert s2.json()["session"]["id"] != sid_cancelled


def test_session_complete_and_training_complete_do_not_duplicate_log(client, app_modules):
    """Both endpoints should not produce duplicate WorkoutLog entries."""
    database, _ = app_modules
    ex = client.post("/api/exercises", json={
        "name": "不重复日志测试", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-07-01", "title": "不重复", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })

    # Complete via session
    start = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    client.post("/api/session/update", json={
        "session_id": start.json()["session"]["id"],
        "exercise_id": start.json()["session"]["records"][0]["exercise_id"],
        "status": "completed", "sets_completed": 1,
    })
    client.post("/api/session/complete", json={"session_id": start.json()["session"]["id"]})

    # Call legacy /api/training/complete for same date
    client.post("/api/training/complete", json={"date": "2026-07-01", "status": "done"})

    # Count WorkoutLog entries for this plan
    db = database.SessionLocal()
    try:
        from datetime import date
        logs = db.query(database.WorkoutLog).filter(
            database.WorkoutLog.plan_id == gen.json()["plan"]["id"]
        ).all()
        # Should NOT be 2 (one from session/complete, one from training/complete)
        assert len([l for l in logs if l.action == "completed"]) == 1, \
            f"Expected 1 completed log, got {len([l for l in logs if l.action == 'completed'])}"
    finally:
        db.close()


def test_empty_api_does_not_load_demo_data(app_modules, client):
    """Empty database returns real empty arrays, not demo data."""
    database, _ = app_modules
    db = database.SessionLocal()
    try:
        # Clear dependents first under foreign_keys=ON
        db.query(database.SessionRecord).delete()
        db.query(database.WorkoutSession).delete()
        db.query(database.WorkoutLog).delete()
        db.query(database.WorkoutExercise).delete()
        db.query(database.Reminder).delete()
        db.query(database.WorkoutPlan).update({database.WorkoutPlan.template_id: None})
        db.query(database.WorkoutPlan).delete()
        db.execute(database.text("DELETE FROM template_exercises"))
        db.query(database.Template).delete()
        db.query(database.Exercise).delete()
        db.commit()

        exercises_resp = client.get("/api/exercises")
        assert exercises_resp.status_code == 200
        assert exercises_resp.json()["exercises"] == []

        templates_resp = client.get("/api/templates")
        assert templates_resp.status_code == 200
        assert templates_resp.json()["templates"] == []
    finally:
        db.close()


def test_plan_edit_uses_target_month(app_modules, client):
    """Editing a non-current-month plan still returns correct plan after save."""
    database, _ = app_modules
    from datetime import date
    # Find a plan in a different month
    # Use plans/month for August 2026
    plans = client.get("/api/plans/month?month=2026-08").json()
    training_day = next((d for d in plans["days"] if d["is_training"] and d["id"] is not None), None)
    assert training_day is not None, "No training day in Aug 2026"
    plan_id = training_day["id"]
    original_title = training_day["title"]

    updated = client.put(f"/api/plans/{plan_id}", json={
        "title": "八月测试标题",
        "is_training_day": True,
    })
    assert updated.status_code == 200
    assert updated.json()["date"] == training_day["date"]

    # Re-fetch August — plan should still be there with new title
    plans2 = client.get("/api/plans/month?month=2026-08").json()
    plan2 = next((d for d in plans2["days"] if d["id"] == plan_id), None)
    assert plan2 is not None
    assert plan2["title"] == "八月测试标题"


def test_plan_template_change_persists_exercises(app_modules, client):
    """Template change persists exercises through /plans/generate."""
    database, _ = app_modules
    ex1 = client.post("/api/exercises", json={
        "name": "模板动作A", "category": "测试", "difficulty": "低",
        "defaultSets": 2, "defaultReps": "8次",
    })
    ex2 = client.post("/api/exercises", json={
        "name": "模板动作B", "category": "测试", "difficulty": "低",
        "defaultSets": 3, "defaultReps": "6次",
    })

    gen = client.post("/api/plans/generate", json={
        "date": "2026-07-02", "title": "模板变更测试", "theme": "测试",
        "exerciseIds": [ex1.json()["id"]],
    })
    plan_id = gen.json()["plan"]["id"]

    # Change exercises by generating again
    gen2 = client.post("/api/plans/generate", json={
        "date": "2026-07-02", "title": "模板变更测试", "theme": "测试",
        "exerciseIds": [ex1.json()["id"], ex2.json()["id"]],
    })
    assert gen2.status_code == 200
    assert len(gen2.json()["plan"]["items"]) == 2

    # Re-fetch and verify
    plans = client.get("/api/plans/month?month=2026-07").json()
    plan = next((d for d in plans["days"] if d["date"] == "2026-07-02"), None)
    assert plan is not None
    assert len(plan["items"]) == 2


def test_video_save_failure_does_not_report_success(app_modules, client):
    """Backend video save failure returns clear error, not success."""
    # Non-existent exercise ID → 404
    resp = client.put("/api/exercises/99999", json={
        "name": "不存在动作", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "1次",
        "video_url": "https://www.bilibili.com/video/BV1234567890/",
    })
    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


def test_restore_defaults_uses_dry_run_before_confirm(client):
    """restore-defaults with confirm=false returns preview, not execute."""
    dry = client.post("/api/data/restore-defaults", json={"confirm": False})
    assert dry.status_code == 200
    data = dry.json()
    assert data["status"] == "dry_run", f"Expected dry_run, got {data.get('status')}"


def test_sqlite_backup_integrity(app_modules):
    """Backup integrity check — verify database can be copied and verified."""
    database, _ = app_modules
    import shutil, sqlite3, tempfile
    tmp = tempfile.mktemp(suffix=".backup.db")

    # Use SQLite backup API for consistency
    src = sqlite3.connect(str(database.DATABASE_PATH))
    dst = sqlite3.connect(tmp)
    src.backup(dst)
    src.close()
    dst.close()

    # Verify backup
    verify = sqlite3.connect(tmp)
    result = verify.execute("PRAGMA integrity_check").fetchone()[0]
    assert result == "ok", f"Integrity check failed: {result}"
    verify.close()


def test_migration_is_idempotent(app_modules):
    """Seed database can be called multiple times without errors or data changes."""
    database, _ = app_modules
    db = database.SessionLocal()
    try:
        plan_count_before = db.query(database.WorkoutPlan).count()
        ex_count_before = db.query(database.Exercise).count()

        # Call seed again
        database.seed_database()

        plan_count_after = db.query(database.WorkoutPlan).count()
        ex_count_after = db.query(database.Exercise).count()
        assert plan_count_after == plan_count_before, "Seed changed plan count"
        assert ex_count_after == ex_count_before, "Seed changed exercise count"
    finally:
        db.close()


def test_completed_session_current_returns_null(client):
    """After session complete, /api/session/current returns session=null."""
    ex = client.post("/api/exercises", json={
        "name": "当前测试", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-07-03", "title": "当前测试", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    start = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    sid = start.json()["session"]["id"]

    cur1 = client.get(f"/api/session/current?plan_id={gen.json()['plan']['id']}")
    assert cur1.json()["session"] is not None

    client.post("/api/session/update", json={
        "session_id": sid,
        "exercise_id": start.json()["session"]["records"][0]["exercise_id"],
        "status": "completed", "sets_completed": 1,
    })
    client.post("/api/session/complete", json={"session_id": sid})

    cur2 = client.get(f"/api/session/current?plan_id={gen.json()['plan']['id']}")
    assert cur2.json()["session"] is None


def test_invalid_status_rejected(client):
    """SessionRecord update with invalid status returns 422 not 500."""
    ex = client.post("/api/exercises", json={
        "name": "无效状态测试", "category": "测试", "difficulty": "低",
        "defaultSets": 1, "defaultReps": "5次",
    })
    gen = client.post("/api/plans/generate", json={
        "date": "2026-07-04", "title": "无效", "theme": "测试", "exerciseIds": [ex.json()["id"]],
    })
    start = client.post("/api/session/start", json={"plan_id": gen.json()["plan"]["id"]})
    sid = start.json()["session"]["id"]
    eid = start.json()["session"]["records"][0]["exercise_id"]

    # Send invalid status
    resp = client.post("/api/session/update", json={
        "session_id": sid, "exercise_id": eid, "status": "bogus_status",
    })
    assert resp.status_code == 422
    assert "status" in str(resp.json()).lower() or "不允许" in str(resp.json())


def test_seed_exercise_ids_not_null(app_modules):
    """All seeded WorkoutExercises have non-NULL exercise_id."""
    database, _ = app_modules
    db = database.SessionLocal()
    try:
        null_count = db.query(database.WorkoutExercise).filter(
            database.WorkoutExercise.exercise_id.is_(None)
        ).count()
        assert null_count == 0, f"Found {null_count} WorkoutExercises with NULL exercise_id"
    finally:
        db.close()


def test_canonical_plan_save_replaces_actions_and_roundtrips(app_modules, client):
    """Date edits persist the complete action snapshot and survive re-read."""
    database, _ = app_modules
    exercises = client.get("/api/exercises").json()["exercises"]
    first, second = exercises[:2]
    payload = {
        "date": "2026-09-15",
        "title": "VAN-10 统一编辑",
        "is_training_day": True,
        "focus": "测试计划",
        "notes": "首次保存",
        "items": [
            {"exercise_id": first["id"], "sets": 2, "reps": 8},
            {"exercise_id": second["id"], "sets": 1, "duration_seconds": 30},
        ],
    }
    saved = client.put("/api/plans/by-date/2026-09-15", json=payload)
    assert saved.status_code == 200
    assert saved.json()["plan"]["title"] == "VAN-10 统一编辑"
    assert [item["exercise_id"] for item in saved.json()["plan"]["items"]] == [first["id"], second["id"]]

    payload["items"] = [{"exercise_id": second["id"], "sets": 3, "reps": 6, "duration_seconds": 30, "notes": "保留备注"}]
    payload["notes"] = "替换后"
    replaced = client.put("/api/plans/by-date/2026-09-15", json=payload)
    assert replaced.status_code == 200

    fetched = client.get("/api/plans/month", params={"month": "2026-09"}).json()
    day = next(item for item in fetched["days"] if item["date"] == "2026-09-15")
    assert day["title"] == "VAN-10 统一编辑"
    assert day["notes"] == "替换后"
    assert len(day["items"]) == 1
    assert day["items"][0]["exercise_id"] == second["id"]
    assert day["items"][0]["sets"] == 3

    # The surviving action keeps explicit nullable/structured fields exactly.
    assert day["items"][0]["reps"] == 6
    assert day["items"][0]["duration_seconds"] == 30
    assert day["items"][0]["notes"] == "保留备注"
    assert day["items"][0]["spec"] == "3 组 · 6 次 · 30 秒"

    nullable = client.put(
        "/api/plans/by-date/2026-09-15",
        json={
            "date": "2026-09-15",
            "title": "VAN-10 nullable",
            "is_training_day": True,
            "items": [{"exercise_id": second["id"], "sets": 4, "reps": None, "duration_seconds": None, "notes": "显式空值"}],
        },
    )
    assert nullable.status_code == 200
    nullable_item = nullable.json()["plan"]["items"][0]
    assert nullable_item["sets"] == 4
    assert nullable_item["reps"] is None
    assert nullable_item["duration_seconds"] is None
    assert nullable_item["notes"] == "显式空值"

    cleared = client.put(
        "/api/plans/by-date/2026-09-15",
        json={"date": "2026-09-15", "is_training_day": False, "title": "恢复日", "items": []},
    )
    assert cleared.status_code == 200
    assert cleared.json()["plan"]["is_training"] is False
    assert cleared.json()["plan"]["items"] == []

    db = database.SessionLocal()
    try:
        row = db.query(database.WorkoutPlan).filter(database.WorkoutPlan.plan_date == date(2026, 9, 15)).one()
        assert row.is_training_day is False
        assert row.template_id is None
        assert row.exercises == []
    finally:
        db.close()


def test_postpone_moves_plan_and_restores_source_atomically(app_modules, client):
    """Postpone updates both dates in one backend transaction."""
    database, _ = app_modules
    exercise = client.get("/api/exercises").json()["exercises"][0]
    source = client.put(
        "/api/plans/by-date/2026-09-20",
        json={
            "date": "2026-09-20",
            "title": "待推迟计划",
            "is_training_day": True,
            "items": [{"exercise_id": exercise["id"], "sets": 2, "reps": 5}],
        },
    )
    assert source.status_code == 200

    moved = client.post(
        "/api/plans/postpone",
        json={"source_date": "2026-09-20", "target_date": "2026-09-21"},
    )
    assert moved.status_code == 200
    assert moved.json()["source"]["is_training"] is False
    assert moved.json()["target"]["is_training"] is True
    assert moved.json()["target"]["items"][0]["exercise_id"] == exercise["id"]

    source_after = client.get("/api/plans", params={"date": "2026-09-20"}).json()["plans"][0]
    target_after = client.get("/api/plans", params={"date": "2026-09-21"}).json()["plans"][0]
    assert source_after["isTrainingDay"] is False
    assert source_after["items"] == []
    assert target_after["isTrainingDay"] is True
    assert len(target_after["items"]) == 1

    db = database.SessionLocal()
    try:
        assert db.query(database.WorkoutPlan).filter(database.WorkoutPlan.plan_date == date(2026, 9, 20), database.WorkoutPlan.is_training_day == True).count() == 0
        assert db.query(database.WorkoutExercise).join(database.WorkoutPlan).filter(database.WorkoutPlan.plan_date == date(2026, 9, 21)).count() == 1
    finally:
        db.close()


def test_import_plans_writes_and_reads_canonical_snapshots(app_modules, client):
    """Import writes date plans to SQLite; the subsequent API read is canonical."""
    exercises = client.get("/api/exercises").json()["exercises"]
    response = client.post(
        "/api/plans/import",
        json={
            "plans": [
                {
                    "date": "2026-09-25",
                    "title": "导入训练",
                    "is_training_day": True,
                    "focus": "导入",
                    "items": [{"exercise_id": exercises[0]["id"], "sets": 1, "reps": 4}],
                },
                {
                    "date": "2026-09-26",
                    "title": "导入恢复",
                    "is_training_day": False,
                    "items": [],
                },
            ]
        },
    )
    assert response.status_code == 200
    assert {plan["date"] for plan in response.json()["plans"]} == {"2026-09-25", "2026-09-26"}

    month = client.get("/api/plans/month", params={"month": "2026-09"}).json()
    imported_training = next(day for day in month["days"] if day["date"] == "2026-09-25")
    imported_rest = next(day for day in month["days"] if day["date"] == "2026-09-26")
    assert imported_training["is_training"] is True
    assert imported_training["items"][0]["exercise_id"] == exercises[0]["id"]
    assert imported_rest["is_training"] is False
    assert imported_rest["items"] == []


def test_import_replaces_unlisted_pending_plans_in_represented_month(app_modules, client):
    """Import coverage follows the UI's month replacement semantics."""
    exercise = client.get("/api/exercises").json()["exercises"][0]
    for day in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-11-02"):
        saved = client.put(
            f"/api/plans/by-date/{day}",
            json={
                "date": day,
                "title": f"旧计划 {day}",
                "is_training_day": True,
                "items": [{"exercise_id": exercise["id"], "sets": 2, "reps": 6}],
            },
        )
        assert saved.status_code == 200
    historical = client.get("/api/plans", params={"date": "2026-10-01"}).json()["plans"][0]
    assert client.post("/api/logs/complete", json={"plan_id": historical["id"], "notes": "历史完成"}).status_code == 200

    imported = client.post(
        "/api/plans/import",
        json={
            "replace_months": True,
            "plans": [
                {
                    "date": "2026-10-03",
                    "title": "备份中的计划",
                    "is_training_day": True,
                    "items": [{"exercise_id": exercise["id"], "sets": 4, "reps": 8, "duration_seconds": 30, "notes": "保留备注", "spec": "自定义规格：保持 30 秒"}],
                }
            ],
        },
    )
    assert imported.status_code == 200

    omitted = client.get("/api/plans", params={"date": "2026-10-02"}).json()["plans"][0]
    omitted_other_month = client.get("/api/plans", params={"date": "2026-11-02"}).json()["plans"][0]
    historical_after = client.get("/api/plans", params={"date": "2026-10-01"}).json()["plans"][0]
    kept = client.get("/api/plans", params={"date": "2026-10-03"}).json()["plans"][0]
    assert omitted["isTrainingDay"] is False
    assert omitted["items"] == []
    assert omitted_other_month["isTrainingDay"] is False
    assert omitted_other_month["items"] == []
    assert historical_after["isTrainingDay"] is True
    assert len(historical_after["items"]) == 1
    assert kept["isTrainingDay"] is True
    assert kept["items"][0]["sets"] == 4
    assert kept["items"][0]["reps"] == 8
    assert kept["items"][0]["durationSeconds"] == 30
    assert kept["items"][0]["notes"] == "保留备注"
    assert kept["items"][0]["spec"] == "自定义规格：保持 30 秒"


def test_empty_import_clears_pending_but_preserves_history(app_modules, client):
    exercise = client.get("/api/exercises").json()["exercises"][0]
    pending = client.put(
        "/api/plans/by-date/2026-12-02",
        json={"date": "2026-12-02", "title": "待清除", "is_training_day": True, "items": [{"exercise_id": exercise["id"]}]},
    ).json()["plan"]
    historical = client.put(
        "/api/plans/by-date/2026-12-01",
        json={"date": "2026-12-01", "title": "历史保留", "is_training_day": True, "items": [{"exercise_id": exercise["id"]}]},
    ).json()["plan"]
    assert client.post("/api/logs/complete", json={"plan_id": historical["id"], "notes": "保留"}).status_code == 200

    response = client.post("/api/plans/import", json={"plans": []})
    assert response.status_code == 200
    assert response.json()["plans"] == []

    pending_after = client.get("/api/plans", params={"date": "2026-12-02"}).json()["plans"][0]
    historical_after = client.get("/api/plans", params={"date": "2026-12-01"}).json()["plans"][0]
    assert pending_after["isTrainingDay"] is False
    assert pending_after["items"] == []
    assert historical_after["isTrainingDay"] is True
    assert len(historical_after["items"]) == 1


def test_existing_schema_adds_spec_column_without_losing_rows(app_modules):
    """The startup migration adds the VAN-10 spec column to an old temp DB."""
    database, _ = app_modules
    import sqlite3

    db = database.SessionLocal()
    try:
        before = db.query(database.WorkoutExercise).count()
    finally:
        db.close()

    raw = sqlite3.connect(database.DATABASE_PATH)
    try:
        raw.execute("ALTER TABLE workout_exercises DROP COLUMN spec")
        raw.commit()
    finally:
        raw.close()
    database.engine.dispose()
    database.create_tables()

    inspector = database.inspect(database.engine)
    assert "spec" in {column["name"] for column in inspector.get_columns("workout_exercises")}
    db = database.SessionLocal()
    try:
        assert db.query(database.WorkoutExercise).count() == before
    finally:
        db.close()
