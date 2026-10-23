"""VAN-21: malformed AI output must fail at the API boundary, with no live model."""
import copy
import json

import pytest

from test_v25_node5_ai import valid_ai_draft


@pytest.fixture()
def configured_ai(app_modules, monkeypatch):
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "mock-key")
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://mock.invalid/v1")
    monkeypatch.setenv("WORKOUT_AI_MODEL", "mock-model")
    return app_modules[1]


def assert_business_error(response, status=422):
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, str) and detail.strip()
    assert any(word in detail for word in ("AI", "格式", "字段", "必须", "数据")), detail


def mock_provider(monkeypatch, main, payload):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    monkeypatch.setattr(main.ai_service, "urlopen", lambda *args, **kwargs: Response())


@pytest.mark.parametrize("upstream", [
    None, [], {}, {"choices": None}, {"choices": []}, {"choices": [None]},
    {"choices": [{"message": None}]},
    *[{"choices": [{"message": {"content": value}}]} for value in (None, [], {}, 7, False, "", "  ")],
])
def test_formal_chat_rejects_malformed_provider_envelope(client, configured_ai, monkeypatch, upstream):
    mock_provider(monkeypatch, configured_ai, upstream)
    response = client.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "训练建议"}]})
    assert_business_error(response, 502)


@pytest.mark.parametrize("content", ["正常聊天文本", "null", "[]"])
def test_formal_chat_preserves_nonempty_text(client, configured_ai, monkeypatch, content):
    mock_provider(monkeypatch, configured_ai, {"choices": [{"message": {"content": content}}]})
    response = client.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "训练建议"}]})
    assert response.status_code == 200, response.text
    assert response.json()["message"]["content"] == content


def malformed_drafts():
    for name, value in [("null", None), ("array", []), ("string", "text"), ("number", 7), ("bool", True)]:
        yield pytest.param(value, id=name)
    changes = [
        (("schemaVersion",), {}), (("schemaVersion",), []),
        (("templates", 0, "id"), {}), (("templates", 0, "id"), []), (("templates", 0, "id"), None),
        (("templates", 0, "exerciseIds"), None), (("templates", 0, "exerciseIds"), "dead_bug"),
        (("templates", 0, "exerciseIds"), [{}]),
        (("schedule", "2026-08-20", "templateId"), {}), (("schedule", "2026-08-20", "templateId"), []),
        (("exercises", 0, "videos"), "wrong"), (("exercises", 0, "videos"), [None]),
        (("exercises", 0, "videos", 0, "url"), {}),
        (("exercises", 0, "defaultReps"), {}), (("exercises", 0, "defaultReps"), []),
        (("exercises", 0, "defaultSets"), {}), (("exercises", 0, "defaultSets"), "two"),
        (("exercises", 0, "defaultSets"), True),
        (("exercises", 0, "durationSeconds"), {}), (("exercises", 0, "durationSeconds"), "sixty"),
        (("exercises", 0, "durationSeconds"), True),
    ]
    for index, (path, value) in enumerate(changes):
        draft = copy.deepcopy(valid_ai_draft())
        target = draft
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        yield pytest.param(draft, id=f"field-{index}-{'-'.join(map(str, path))}")


@pytest.mark.parametrize("endpoint", ["/api/ai/import-plan", "/api/ai/analyze"])
@pytest.mark.parametrize("draft", list(malformed_drafts()))
def test_compat_plan_endpoints_reject_invalid_shapes(client, configured_ai, monkeypatch, endpoint, draft):
    monkeypatch.setattr(configured_ai.ai_service, "call_ai_chat", lambda *args, **kwargs: json.dumps(draft))
    assert_business_error(client.post(endpoint, json={"prompt": "生成训练计划"}))


@pytest.mark.parametrize("result", [
    None, [], "text", 7,
    {}, {"keywords": [], "searchUrls": []}, {"keywords": ["   "]},
    {"keywords": None}, {"keywords": "死虫"}, {"keywords": [{}]}, {"keywords": [None]},
    {"searchUrls": None}, {"searchUrls": "https://b23.tv/mock"},
    {"searchUrls": [{}]}, {"searchUrls": [None]},
])
def test_video_suggest_rejects_invalid_shapes(client, configured_ai, monkeypatch, result):
    monkeypatch.setattr(configured_ai.ai_service, "call_ai_chat", lambda *args, **kwargs: json.dumps(result))
    assert_business_error(client.post("/api/ai/suggest-bilibili-video", json={"exercise_name": "死虫"}))


def test_video_suggest_valid_keywords_without_urls(client, configured_ai, monkeypatch):
    monkeypatch.setattr(configured_ai.ai_service, "call_ai_chat", lambda *args, **kwargs: json.dumps({"keywords": ["死虫教学"]}))
    response = client.post("/api/ai/suggest-bilibili-video", json={"exercise_name": "死虫"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert response.json()["query"] == "死虫教学"
    assert "search.bilibili.com" in response.json()["search_url"]


def test_video_suggest_unconfigured_fallback(client, app_modules, monkeypatch):
    called = []
    monkeypatch.setattr(app_modules[1].ai_service, "call_ai_chat", lambda *args, **kwargs: called.append(args))
    response = client.post("/api/ai/suggest-bilibili-video", json={"exercise_name": "死虫"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "fallback"
    assert "search.bilibili.com" in response.json()["search_url"]
    assert called == []


@pytest.fixture()
def session_id(client):
    exercise = client.post("/api/exercises", json={
        "name": "VAN21 临时动作", "category": "测试", "defaultSets": 1, "defaultReps": "5次",
    })
    assert exercise.status_code == 201, exercise.text
    plan = client.post("/api/plans/generate", json={
        "date": "2031-10-21", "title": "VAN21 临时计划", "exerciseIds": [exercise.json()["id"]],
    })
    assert plan.status_code == 200, plan.text
    session = client.post("/api/session/start", json={"plan_id": plan.json()["plan"]["id"]})
    assert session.status_code == 200, session.text
    return session.json()["session"]["id"]


@pytest.mark.parametrize("result", [
    None, [], "text", 7,
    {"summary": {}, "adjustments": [], "score": 50},
    {"summary": "完成", "adjustments": "继续", "score": 50},
    {"summary": "完成", "adjustments": [{}], "score": 50},
    {"summary": "完成", "adjustments": [], "score": {}},
    {"summary": "完成", "adjustments": [], "score": True},
])
def test_session_analysis_rejects_invalid_shapes(client, configured_ai, monkeypatch, session_id, result):
    monkeypatch.setattr(configured_ai.ai_service, "call_ai_chat", lambda *args, **kwargs: json.dumps(result))
    assert_business_error(client.post("/api/ai/analyze", json={"session_id": session_id}))


def test_session_analysis_valid_result(client, configured_ai, monkeypatch, session_id):
    result = {"summary": "完成训练，继续保持", "adjustments": ["保持动作稳定"], "score": 80}
    monkeypatch.setattr(configured_ai.ai_service, "call_ai_chat", lambda *args, **kwargs: json.dumps(result))
    response = client.post("/api/ai/analyze", json={"session_id": session_id})
    assert response.status_code == 200, response.text
    assert response.json()["analysis"] == result
