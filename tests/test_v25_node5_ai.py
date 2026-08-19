import json


def clear_ai_env(monkeypatch):
    for name in (
        "WORKOUT_AI_API_KEY", "WORKOUT_AI_BASE_URL", "WORKOUT_AI_MODEL",
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
        "WUAPI_API_KEY", "WUAPI_BASE_URL", "WUAPI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def valid_ai_draft():
    return {
        "schemaVersion": "v1",
        "version": "1.0",
        "source": "ai_generated",
        "title": "Mock 核心训练",
        "theme": "核心稳定",
        "recommendedDate": "2026-08-20",
        "exercises": [{
            "id": "dead_bug",
            "name": "死虫",
            "category": "核心",
            "defaultSets": 2,
            "defaultReps": "8次",
            "durationSeconds": None,
            "notes": "保持腰背稳定",
            "videos": [{
                "id": "b1",
                "title": "B站搜索",
                "platform": "bilibili",
                "url": "https://search.bilibili.com/all?keyword=%E6%AD%BB%E8%99%AB",
                "isDefault": True,
            }],
        }],
        "templates": [{"id": "core_1", "name": "核心模板", "description": "", "exerciseIds": ["dead_bug"]}],
        "schedule": {"2026-08-20": {"type": "training", "templateId": "core_1", "status": "pending", "note": ""}},
    }


def test_ai_unconfigured_uses_explicit_fallback_without_external_call(client, app_modules, monkeypatch):
    clear_ai_env(monkeypatch)
    called = []
    monkeypatch.setattr(app_modules[1].ai_service, "call_ai_chat", lambda *args, **kwargs: called.append(args))

    health = client.get("/api/ai/health")
    assert health.status_code == 200
    assert health.json()["enabled"] is False
    response = client.post("/api/ai/import-plan", json={"prompt": "肩颈放松"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fallback"
    assert body["ai_enabled"] is False
    assert "search_url" in body["fallback"]
    assert called == []


def test_ai_import_uses_mock_and_returns_validated_draft_only(client, app_modules, monkeypatch):
    clear_ai_env(monkeypatch)
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "mock-key")
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://mock.invalid/v1")
    monkeypatch.setenv("WORKOUT_AI_MODEL", "mock-model")
    captured = {}

    def fake_chat(base_url, api_key, model, system_prompt, user_prompt, timeout=60):
        captured.update({"base_url": base_url, "api_key": api_key, "model": model, "prompt": user_prompt})
        return json.dumps(valid_ai_draft(), ensure_ascii=False)

    monkeypatch.setattr(app_modules[1].ai_service, "call_ai_chat", fake_chat)
    response = client.post("/api/ai/import-plan", json={"prompt": "生成低强度核心训练"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["ai_enabled"] is True
    assert body["draft"]["schemaVersion"] == "v1"
    assert body["draft"]["templates"][0]["exerciseIds"] == ["dead_bug"]
    assert captured["base_url"] == "https://mock.invalid/v1"
    assert captured["api_key"] == "mock-key"
    assert captured["model"] == "mock-model"


def test_ai_rejects_forbidden_video_from_mock_response(client, app_modules, monkeypatch):
    clear_ai_env(monkeypatch)
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "mock-key")
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://mock.invalid/v1")
    monkeypatch.setenv("WORKOUT_AI_MODEL", "mock-model")
    draft = valid_ai_draft()
    draft["exercises"][0]["videos"][0]["url"] = "https://youtube.com/watch?v=blocked"
    monkeypatch.setattr(
        app_modules[1].ai_service,
        "call_ai_chat",
        lambda *args, **kwargs: json.dumps(draft, ensure_ascii=False),
    )
    response = client.post("/api/ai/import-plan", json={"prompt": "生成计划"})
    assert response.status_code == 422
    assert "Bilibili" in response.json()["detail"]


def test_ai_video_recommendation_is_mocked_and_bilibili_only(client, app_modules, monkeypatch):
    clear_ai_env(monkeypatch)
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "mock-key")
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://mock.invalid/v1")
    monkeypatch.setenv("WORKOUT_AI_MODEL", "mock-model")
    monkeypatch.setattr(
        app_modules[1].ai_service,
        "call_ai_chat",
        lambda *args, **kwargs: json.dumps({
            "keywords": ["死虫教学"],
            "searchUrls": ["https://search.bilibili.com/all?keyword=%E6%AD%BB%E8%99%AB"],
        }, ensure_ascii=False),
    )
    response = client.post("/api/ai/suggest-bilibili-video", json={"exercise_name": "死虫"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ai_enabled"] is True
    assert all("bilibili" in url for url in body["candidates"])


def test_ai_chat_provider_models_and_dpapi_key_store(client, app_modules, monkeypatch, tmp_path):
    clear_ai_env(monkeypatch)
    key_store = tmp_path / "ai-key-store.enc"
    monkeypatch.setenv("WORKOUT_KEY_STORE", str(key_store))
    main = app_modules[1]

    local = client.get("/api/ai/provider")
    assert local.status_code == 200
    assert local.json()["provider"] == "local-demo"
    assert local.json()["source"] == "local-demo"

    messages = [
        {"role": "system", "content": "你是训练助手"},
        {"role": "user", "content": "第一轮"},
        {"role": "assistant", "content": "已记录"},
        {"role": "user", "content": "第二轮"},
    ]
    local_chat = client.post("/api/ai/chat", json={"messages": messages})
    assert local_chat.status_code == 200
    assert local_chat.json()["source"] == "local-demo"
    assert local_chat.json()["messages"] == messages

    configured = client.put("/api/ai/provider", json={
        "provider": "openai",
        "api_key": "super-secret-key",
        "base_url": "https://mock.invalid/v1",
        "model": "mock-model",
    })
    assert configured.status_code == 200, configured.text
    assert configured.json()["provider"] == "openai"
    assert configured.json()["source"] == "api"
    assert configured.json()["key_configured"] is True
    assert "api_key" not in configured.json()
    assert "super-secret-key" not in key_store.read_text(encoding="utf-8")

    monkeypatch.setattr(main.ai_service, "call_ai_messages", lambda base, key, model, sent, timeout=60: (
        assert_messages(sent, messages) or "mock api answer"
    ))
    api_chat = client.post("/api/ai/chat", json={"messages": messages})
    assert api_chat.status_code == 200
    assert api_chat.json()["source"] == "api"
    assert api_chat.json()["message"]["content"] == "mock api answer"

    models = client.get("/api/ai/models")
    assert models.status_code == 200
    assert models.json()["provider"] == "openai"
    assert models.json()["active_model"] == "mock-model"

    monkeypatch.delenv("WORKOUT_KEY_STORE", raising=False)
    monkeypatch.setenv("WORKOUT_KEY_STORE", str(key_store))
    persisted = client.get("/api/ai/provider")
    assert persisted.status_code == 200
    assert persisted.json()["provider"] == "openai"
    assert persisted.json()["source"] == "api"


def assert_messages(actual, expected):
    assert actual == expected
    return False


def test_ai_provider_has_one_deterministic_environment_priority(client, app_modules, monkeypatch, tmp_path):
    clear_ai_env(monkeypatch)
    monkeypatch.setenv("WORKOUT_KEY_STORE", str(tmp_path / "priority.enc"))
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.invalid/v1")
    monkeypatch.setenv("OPENAI_MODEL", "openai-model")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.invalid/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-model")
    body = client.get("/api/ai/provider").json()
    assert body["provider"] == "openai"
    assert body["source"] == "api"
    assert body["model"] == "openai-model"
