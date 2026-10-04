from __future__ import annotations

import copy
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


AI_ENV_NAMES = (
    "WORKOUT_AI_API_KEY",
    "WORKOUT_AI_BASE_URL",
    "WORKOUT_AI_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "WUAPI_API_KEY",
    "WUAPI_BASE_URL",
    "WUAPI_MODEL",
    "WORKOUT_KEY_STORE",
)


class _FakeProviderState:
    def __init__(self):
        self.mode = "success"
        self.authorization = []
        self.paths = []


class _FakeProviderHandler(BaseHTTPRequestHandler):
    state: _FakeProviderState

    def do_GET(self):  # noqa: N802
        self.state.authorization.append(self.headers.get("Authorization", ""))
        self.state.paths.append(self.path)
        if self.path != "/v1/models":
            self._send(404, {"error": "wrong path"})
            return
        if self.state.mode == "timeout":
            time.sleep(0.25)
            return
        if self.state.mode == "401":
            self._send(401, {"error": "UPSTREAM-SECRET-401"})
            return
        if self.state.mode == "403":
            self._send(403, {"error": "UPSTREAM-SECRET-403"})
            return
        if self.state.mode == "500":
            self._send(500, {"error": "UPSTREAM-SECRET-500"})
            return
        if self.state.mode == "invalid-json":
            self._send_raw(200, b"UPSTREAM-SECRET-not-json", "text/plain")
            return
        if self.state.mode == "incomplete":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b'{"data":')
            self.connection.close()
            return
        if self.state.mode == "wrong-shape":
            self._send(200, {"data": [{"name": "missing-id"}]})
            return
        if self.state.mode == "empty":
            self._send(200, {"object": "list", "data": []})
            return
        self._send(200, {"object": "list", "data": [{"id": "fake-model-a"}, {"id": "fake-model-b"}]})

    def log_message(self, *_args):
        return

    def _send(self, status, payload):
        self._send_raw(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _send_raw(self, status, payload, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture()
def fake_provider():
    state = _FakeProviderState()

    class Handler(_FakeProviderHandler):
        pass

    Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture()
def isolated_key_store(app_modules, monkeypatch):
    main = app_modules[1]
    store = {"active_provider": "", "providers": {}}
    calls = {"load": 0, "save": 0}

    def load():
        calls["load"] += 1
        return copy.deepcopy(store)

    def save(value):
        calls["save"] += 1
        store.clear()
        store.update(copy.deepcopy(value))

    monkeypatch.setattr(main.ai_service, "_load_key_store", load)
    monkeypatch.setattr(main.ai_service, "_save_key_store", save)
    return main, store, calls


def _clear_ai_env(monkeypatch):
    for name in AI_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_draft_models_uses_current_form_without_store_read_or_write(
    client, app_modules, isolated_key_store, fake_provider, monkeypatch
):
    _clear_ai_env(monkeypatch)
    main, store, calls = isolated_key_store
    store.update({
        "active_provider": "openai",
        "providers": {"openai": {"api_key": "old-key", "base_url": "http://old.invalid/v1", "model": "old-model"}},
    })
    state, base_url = fake_provider

    response = client.post(
        "/api/ai/models",
        json={"provider": "openai", "api_key": "form-key", "base_url": base_url},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "provider": "openai",
        "source": "draft",
        "models": ["fake-model-a", "fake-model-b"],
        "active_model": None,
        "status": "ok",
    }
    assert state.paths == ["/v1/models"]
    assert state.authorization == ["Bearer form-key"]
    assert calls == {"load": 0, "save": 0}
    assert store["providers"]["openai"]["api_key"] == "old-key"


def test_draft_models_can_switch_provider_without_using_old_saved_connection(
    client, isolated_key_store, fake_provider, monkeypatch
):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store
    state, base_url = fake_provider
    store.update({
        "active_provider": "openai",
        "providers": {"openai": {"api_key": "old-key", "base_url": "http://old.invalid/v1", "model": "old-model"}},
    })

    response = client.post(
        "/api/ai/models",
        json={"provider": "deepseek", "api_key": "new-deepseek-key", "base_url": base_url},
    )

    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "deepseek"
    assert state.authorization == ["Bearer new-deepseek-key"]
    assert state.paths == ["/v1/models"]
    assert calls == {"load": 0, "save": 0}
    assert store["active_provider"] == "openai"
    assert store["providers"]["openai"]["api_key"] == "old-key"


def test_blank_key_reuses_only_exact_saved_connection(client, isolated_key_store, fake_provider, monkeypatch):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store
    state, base_url = fake_provider
    store.update({
        "active_provider": "openai",
        "providers": {"openai": {"api_key": "saved-key", "base_url": base_url, "model": "saved-model"}},
    })

    same = client.post("/api/ai/models", json={"provider": "openai", "api_key": "", "base_url": base_url})
    assert same.status_code == 200, same.text
    assert state.authorization == ["Bearer saved-key"]
    assert calls == {"load": 1, "save": 0}

    changed = client.post(
        "/api/ai/models",
        json={"provider": "deepseek", "api_key": "", "base_url": base_url},
    )
    assert changed.status_code == 422
    assert "API Key" in changed.json()["detail"]
    assert "saved-key" not in changed.text
    assert calls["save"] == 0


@pytest.mark.parametrize(
    ("mode", "status", "message"),
    [
        ("401", 401, "无效或未授权"),
        ("403", 403, "没有读取模型"),
        ("500", 502, "HTTP 500"),
        ("invalid-json", 502, "非法 JSON"),
        ("incomplete", 502, "连接失败"),
        ("wrong-shape", 502, "结构异常"),
    ],
)
def test_draft_model_errors_are_safe_and_classified(
    client, isolated_key_store, fake_provider, monkeypatch, mode, status, message
):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store
    state, base_url = fake_provider
    state.mode = mode

    response = client.post(
        "/api/ai/models",
        json={"provider": "openai", "api_key": "fake-key", "base_url": base_url},
    )

    assert response.status_code == status
    assert message in response.json()["detail"]
    assert "UPSTREAM-SECRET" not in response.text
    assert "fake-key" not in response.text
    assert calls["save"] == 0
    assert store["providers"] == {}


def test_empty_model_list_is_explicit_success(client, isolated_key_store, fake_provider, monkeypatch):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store
    state, base_url = fake_provider
    state.mode = "empty"

    response = client.post(
        "/api/ai/models",
        json={"provider": "openai", "api_key": "fake-key", "base_url": base_url},
    )

    assert response.status_code == 200
    assert response.json()["models"] == []
    assert response.json()["status"] == "empty"
    assert calls == {"load": 0, "save": 0}
    assert store["providers"] == {}


def test_failed_draft_discovery_preserves_existing_saved_provider(client, isolated_key_store, fake_provider, monkeypatch):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store
    state, base_url = fake_provider
    state.mode = "500"
    old = {
        "active_provider": "openai",
        "providers": {"openai": {"api_key": "old-key", "base_url": "http://old.invalid/v1", "model": "old-model"}},
    }
    store.update(copy.deepcopy(old))

    response = client.post(
        "/api/ai/models",
        json={"provider": "deepseek", "api_key": "new-key", "base_url": base_url},
    )

    assert response.status_code == 502
    assert store == old
    assert calls == {"load": 0, "save": 0}


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://example.test/v1",
        "http://example.test/v1?key=secret",
        "http://user:pass@example.test/v1",
        "http://example.test/v1#fragment",
    ],
)
def test_base_url_validation_rejects_unsafe_forms(client, isolated_key_store, monkeypatch, base_url):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store

    response = client.post(
        "/api/ai/models",
        json={"provider": "openai", "api_key": "fake-key", "base_url": base_url},
    )

    assert response.status_code == 422
    assert calls == {"load": 0, "save": 0}
    assert store["providers"] == {}


def test_api_key_control_characters_are_rejected_without_leaking_value(client, isolated_key_store, monkeypatch):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store

    response = client.post(
        "/api/ai/models",
        json={"provider": "openai", "api_key": "fake-key\r\nInjected: secret", "base_url": "http://127.0.0.1:1/v1"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "api_key 格式不合法"
    assert "fake-key" not in response.text
    assert "Injected" not in response.text
    assert calls == {"load": 0, "save": 0}
    assert store["providers"] == {}


def test_invalid_request_shape_does_not_echo_api_key(client, isolated_key_store, monkeypatch):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store

    response = client.post(
        "/api/ai/models",
        json={"provider": "openai", "api_key": {"secret": "schema-secret"}, "base_url": "http://example.test/v1"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "AI provider 临时连接信息格式不合法。"
    assert "schema-secret" not in response.text
    assert calls == {"load": 0, "save": 0}
    assert store["providers"] == {}


def test_save_failure_preserves_previous_fake_store(client, isolated_key_store, monkeypatch):
    _clear_ai_env(monkeypatch)
    main, store, _calls = isolated_key_store
    old = {
        "active_provider": "openai",
        "providers": {"openai": {"api_key": "old-key", "base_url": "https://old.example/v1", "model": "old-model"}},
    }
    store.update(copy.deepcopy(old))

    def fail_save(_value):
        raise RuntimeError("DPAPI key_store 仅支持 Windows")

    monkeypatch.setattr(main.ai_service, "_save_key_store", fail_save)
    response = client.put(
        "/api/ai/provider",
        json={"provider": "openai", "api_key": "new-key", "base_url": "https://new.example/v1", "model": "new-model"},
    )

    assert response.status_code == 503
    assert "new-key" not in response.text
    assert store == old


def test_save_rejects_unsafe_base_url_without_store_write(client, isolated_key_store, monkeypatch):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store

    response = client.put(
        "/api/ai/provider",
        json={"provider": "openai", "api_key": "fake-key", "base_url": "https://fake.example/v1?token=secret", "model": "chosen-model"},
    )

    assert response.status_code == 422
    assert "secret" not in response.text
    assert calls == {"load": 0, "save": 0}
    assert store["providers"] == {}


def test_save_and_get_readback_with_fake_key_store(client, isolated_key_store, monkeypatch):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store

    saved = client.put(
        "/api/ai/provider",
        json={"provider": "openai", "api_key": "fake-key", "base_url": "https://fake.example/v1", "model": "chosen-model"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["base_url"] == "https://fake.example/v1"
    assert saved.json()["model"] == "chosen-model"
    assert saved.json()["key_configured"] is True
    assert "fake-key" not in saved.text

    provider = client.get("/api/ai/provider")
    models = client.get("/api/ai/models")
    assert provider.status_code == 200
    assert provider.json()["provider"] == "openai"
    assert provider.json()["base_url"] == "https://fake.example/v1"
    assert provider.json()["model"] == "chosen-model"
    assert models.json()["models"] == ["chosen-model"]
    assert store["providers"]["openai"]["api_key"] == "fake-key"
    assert calls["save"] == 1


def test_timeout_is_classified_without_upstream_body(fake_provider, app_modules, monkeypatch):
    _clear_ai_env(monkeypatch)
    state, base_url = fake_provider
    state.mode = "timeout"
    ai_service = app_modules[1].ai_service

    with pytest.raises(ai_service.ProviderModelsError) as exc_info:
        ai_service.discover_provider_models("openai", "fake-key", base_url, timeout=0.05)

    assert exc_info.value.status_code == 504
    assert "超时" in str(exc_info.value)
    assert "fake-key" not in str(exc_info.value)


def test_connection_failure_is_classified(client, isolated_key_store, monkeypatch):
    _clear_ai_env(monkeypatch)
    _main, store, calls = isolated_key_store
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    unused_port = sock.getsockname()[1]
    sock.close()

    response = client.post(
        "/api/ai/models",
        json={"provider": "openai", "api_key": "fake-key", "base_url": f"http://127.0.0.1:{unused_port}/v1"},
    )

    assert response.status_code == 502
    assert "连接失败" in response.json()["detail"]
    assert "fake-key" not in response.text
    assert calls["save"] == 0
    assert store["providers"] == {}


def test_main_post_json_still_constructs_urllib_request(app_modules, monkeypatch):
    main = app_modules[1]
    captured = {}

    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout):
        captured.update({"url": request.full_url, "method": request.method, "timeout": timeout})
        return Response()

    monkeypatch.setattr(main, "urlopen", fake_urlopen)
    result = main.post_json("http://127.0.0.1:9/mock", {"probe": True})

    assert result["http_status"] == 200
    assert captured == {"url": "http://127.0.0.1:9/mock", "method": "POST", "timeout": 10}
