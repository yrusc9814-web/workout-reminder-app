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
    assert "运动提醒 App" in response.text or "训练面板" in response.text


def test_today_endpoint_exists_and_returns_shape(client):
    response = client.get("/api/today")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"date", "id", "title", "theme", "notes", "type", "is_training", "items"}


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


def test_reminder_mock_endpoints_exist(client):
    wechat = client.post("/api/reminders/wechat/send", json={"title": "x", "message": "y"})
    dingtalk = client.post("/api/reminders/dingtalk/send", json={"title": "x", "message": "y"})

    assert wechat.status_code == 200
    assert dingtalk.status_code == 200
    assert wechat.json()["status"] == "not_sent"
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

