import pytest


FIXTURE_MARKER = "VAN132_FIXTURE_MARKER"


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": FIXTURE_MARKER, "base_url": "https://mock.invalid/v1", "model": "mock"},
        {"provider": 123, "api_key": FIXTURE_MARKER, "base_url": "https://mock.invalid/v1", "model": "mock"},
        {"provider": "openai", "api_key": 123, "base_url": "https://mock.invalid/v1", "model": "mock"},
        {"provider": "openai", "api_key": FIXTURE_MARKER, "base_url": 123, "model": "mock"},
        {"provider": "openai", "api_key": FIXTURE_MARKER, "base_url": "https://mock.invalid/v1", "model": 123},
    ],
)
def test_provider_validation_does_not_echo_invalid_input(client, payload):
    response = client.put("/api/ai/provider", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "AI provider 配置格式不合法。"}
    assert FIXTURE_MARKER not in response.text


def test_local_demo_provider_request_is_not_blocked(client, app_modules, monkeypatch):
    main = app_modules[1]
    store = {"active_provider": "", "providers": {}}

    def load():
        return {"active_provider": store["active_provider"], "providers": dict(store["providers"])}

    def save(value):
        store["active_provider"] = value["active_provider"]
        store["providers"] = dict(value["providers"])

    monkeypatch.setattr(main.ai_service, "_load_key_store", load)
    monkeypatch.setattr(main.ai_service, "_save_key_store", save)

    response = client.put(
        "/api/ai/provider",
        json={"provider": "local-demo", "api_key": "", "base_url": "", "model": ""},
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "local-demo"


def test_models_validation_protection_is_preserved(client):
    response = client.post(
        "/api/ai/models",
        json={"api_key": FIXTURE_MARKER, "base_url": "https://mock.invalid/v1"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "AI provider 临时连接信息格式不合法。"}
    assert FIXTURE_MARKER not in response.text


@pytest.mark.parametrize("method,path,message", [
    ("PUT", "/api/ai/provider", "AI provider 配置格式不合法。"),
    ("POST", "/api/ai/models", "AI provider 临时连接信息格式不合法。"),
])
@pytest.mark.parametrize("payload", [
    None,
    [FIXTURE_MARKER],
    FIXTURE_MARKER,
    {"api_key": FIXTURE_MARKER},
    {"provider": {"value": FIXTURE_MARKER}, "api_key": FIXTURE_MARKER},
    {"provider": "openai", "api_key": {"value": FIXTURE_MARKER}},
    {"provider": "openai", "api_key": [FIXTURE_MARKER]},
    {"provider": "openai", "api_key": None, "base_url": FIXTURE_MARKER},
    {"provider": "openai", "api_key": FIXTURE_MARKER, "base_url": {"value": FIXTURE_MARKER}},
])
def test_provider_related_schema_errors_are_redacted(client, method, path, message, payload):
    response = client.request(method, path, json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": message}
    assert FIXTURE_MARKER not in response.text


@pytest.mark.parametrize("method,path,message", [
    ("PUT", "/api/ai/provider/", "AI provider 配置格式不合法。"),
    ("POST", "/api/ai/models/", "AI provider 临时连接信息格式不合法。"),
])
def test_invalid_json_is_redacted_after_slash_redirect(client, method, path, message):
    response = client.request(
        method, path + "?draft=1",
        content='{"api_key":"' + FIXTURE_MARKER + '",',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": message}
    assert FIXTURE_MARKER not in response.text


@pytest.mark.parametrize("method,path", [("PUT", "/api/ai/provider"), ("POST", "/api/ai/models")])
@pytest.mark.parametrize("field,value", [
    ("provider", FIXTURE_MARKER + "!"),
    ("api_key", FIXTURE_MARKER + "\r\nInjected: test"),
    ("api_key", FIXTURE_MARKER + "密钥"),
    ("base_url", "https://[" + FIXTURE_MARKER + "]/v1"),
    ("base_url", "https://" + FIXTURE_MARKER + ":bad-port/v1"),
    ("base_url", "https://mock.invalid/v1?key=" + FIXTURE_MARKER),
    ("base_url", "https://user:" + FIXTURE_MARKER + "@mock.invalid/v1"),
])
def test_provider_business_validation_never_echoes_input(client, method, path, field, value):
    payload = {
        "provider": "openai", "api_key": FIXTURE_MARKER,
        "base_url": "https://mock.invalid/v1", "model": "mock",
    }
    payload[field] = value
    response = client.request(method, path, json=payload)
    assert response.status_code == 422
    assert set(response.json()) == {"detail"}
    assert isinstance(response.json()["detail"], str)
    assert FIXTURE_MARKER not in response.text


def test_invalid_request_stays_422_even_when_store_is_corrupt(client, monkeypatch, tmp_path):
    path = tmp_path / "corrupt-store.enc"
    path.write_text("{", encoding="utf-8")
    monkeypatch.setenv("WORKOUT_KEY_STORE", str(path))

    response = client.put("/api/ai/provider", json={
        "provider": "openai", "api_key": FIXTURE_MARKER,
        "base_url": "not-an-http-url", "model": "mock",
    })
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert FIXTURE_MARKER not in response.text
    assert path.read_text(encoding="utf-8") == "{"
