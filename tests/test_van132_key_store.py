import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


FIXTURE_MARKER = "VAN132_FIXTURE_MARKER"
APP_DIR = Path(__file__).resolve().parents[1]
STORE_ERROR = {"detail": "AI provider 配置不可用。"}
PROVIDER_PAYLOAD = {
    "provider": "openai",
    "api_key": FIXTURE_MARKER,
    "base_url": "https://mock.invalid/v1",
    "model": "mock-model",
}


def assert_store_failure(client):
    requests = [
        ("GET", "/api/ai/provider", None),
        ("GET", "/api/ai/models", None),
        ("GET", "/api/ai/health", None),
        ("PUT", "/api/ai/provider", PROVIDER_PAYLOAD),
        ("PUT", "/api/ai/provider", {"provider": "local-demo"}),
        ("POST", "/api/ai/models", {**PROVIDER_PAYLOAD, "api_key": ""}),
        ("POST", "/api/ai/chat", {"messages": [{"role": "user", "content": "hello"}]}),
    ]
    for method, path, payload in requests:
        response = client.request(method, path, json=payload)
        assert response.status_code == 500, (method, path, response.status_code)
        assert response.json() == STORE_ERROR
        assert FIXTURE_MARKER not in response.text
        assert "protected" not in response.text


@pytest.mark.parametrize("raw", [
    b'{"api_key":"VAN132_FIXTURE_MARKER",',
    b'{"version":1,"protected":"\xffVAN132_FIXTURE_MARKER"}',
    b'{"version":1,"protected":"VAN132_FIXTURE_MARKER"}',
    b'{"version":true,"protected":"VAN132_FIXTURE_MARKER"}',
])
def test_unreadable_key_store_is_server_error_without_content_echo(client, monkeypatch, tmp_path, raw):
    path = tmp_path / "invalid-key-store.enc"
    path.write_bytes(raw)
    monkeypatch.setenv("WORKOUT_KEY_STORE", str(path))

    assert_store_failure(client)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("plain", [
    b'\xffVAN132_FIXTURE_MARKER',
    b'{"api_key":"VAN132_FIXTURE_MARKER",',
    b'[]',
    b'{}',
    b'{"active_provider":123,"providers":{}}',
    b'{"active_provider":"openai","providers":[]}',
    b'{"active_provider":"openai","providers":{}}',
    b'{"active_provider":"openai","providers":{"openai":[]}}',
    b'{"active_provider":"openai","providers":{"openai":{"api_key":123,"base_url":"https://mock.invalid/v1","model":"mock-model"}}}',
    b'{"active_provider":"openai","providers":{"openai":{"api_key":"VAN132_FIXTURE_MARKER","model":"mock-model"}}}',
    b'{"active_provider":"openai","providers":{"openai":{"api_key":"VAN132_FIXTURE_MARKER","base_url":"https://[VAN132_FIXTURE_MARKER]/v1","model":"mock-model"}}}',
    b'{"active_provider":"openai","providers":{"openai":{"api_key":"VAN132_FIXTURE_MARKER\\r\\nInjected","base_url":"https://mock.invalid/v1","model":"mock-model"}}}',
])
def test_decrypted_key_store_structure_is_checked_before_use(client, app_modules, monkeypatch, tmp_path, plain):
    path = tmp_path / "invalid-plaintext-key-store.enc"
    raw = json.dumps({"version": 1, "protected": FIXTURE_MARKER})
    path.write_text(raw, encoding="utf-8")
    monkeypatch.setenv("WORKOUT_KEY_STORE", str(path))
    monkeypatch.setattr(app_modules[1].ai_service, "_dpapi_unprotect", lambda _value: plain)

    assert_store_failure(client)
    assert path.read_text(encoding="utf-8") == raw


def test_key_store_os_error_does_not_expose_path_or_exception(client, app_modules, monkeypatch):
    def fail_load():
        raise OSError(f"C:/private/{FIXTURE_MARKER}/key-store.enc")

    monkeypatch.setattr(app_modules[1].ai_service, "_load_key_store", fail_load)
    for path in ("/api/ai/provider", "/api/ai/models"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == STORE_ERROR
        assert FIXTURE_MARKER not in response.text

    response = client.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hello"}]})
    assert response.status_code == 503
    assert response.json() == STORE_ERROR


@pytest.mark.skipif(os.name != "nt", reason="Requires native Windows DPAPI")
def test_native_dpapi_store_decrypts_in_a_new_process(app_modules, monkeypatch, tmp_path):
    service = app_modules[1].ai_service
    path = tmp_path / "native-key-store.enc"
    monkeypatch.setenv("WORKOUT_KEY_STORE", str(path))
    service.save_provider_config(**PROVIDER_PAYLOAD)

    raw = path.read_text(encoding="utf-8")
    assert FIXTURE_MARKER not in raw
    assert set(json.loads(raw)) == {"version", "protected"}
    assert service._load_key_store()["providers"]["openai"]["api_key"] == FIXTURE_MARKER
    assert not list(tmp_path.glob(".ai-key-store-*.tmp"))

    code = """
import json
import ai_service
config = ai_service.active_provider_config()
assert config['provider'] == 'openai'
assert config['api_key'] == 'VAN132_FIXTURE_MARKER'
assert config['base_url'] == 'https://mock.invalid/v1'
assert config['model'] == 'mock-model'
print(json.dumps({'cross_process_decryption': True}))
"""
    child = subprocess.run(
        [sys.executable, "-c", code],
        cwd=APP_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 0
    assert json.loads(child.stdout) == {"cross_process_decryption": True}
    assert FIXTURE_MARKER not in child.stdout + child.stderr


@pytest.mark.skipif(os.name != "nt", reason="Requires native Windows DPAPI")
@pytest.mark.parametrize("plain", [b'[]', b'{"api_key":"VAN132_FIXTURE_MARKER",'])
def test_native_dpapi_invalid_plaintext_is_a_controlled_server_error(client, app_modules, monkeypatch, tmp_path, plain):
    path = tmp_path / "corrupt-native-key-store.enc"
    protected = app_modules[1].ai_service._dpapi_protect(plain)
    path.write_text(json.dumps({"version": 1, "protected": protected}), encoding="utf-8")
    monkeypatch.setenv("WORKOUT_KEY_STORE", str(path))

    assert_store_failure(client)
