import importlib
import pathlib
import warnings

import pytest

APP_DIR = pathlib.Path(__file__).resolve().parents[1]
_ORIG_IS_FILE = pathlib.Path.is_file


def _safe_is_file(self):
    try:
        return _ORIG_IS_FILE(self)
    except OSError as exc:
        if getattr(exc, 'winerror', 0) == 1337:
            return False
        raise


pathlib.Path.is_file = _safe_is_file


# Silence known Starlette/httpx TestClient deprecation when httpx2 is unavailable
# or still emitted by fastapi.testclient import path.
try:
    from starlette.exceptions import StarletteDeprecationWarning  # type: ignore
except Exception:  # pragma: no cover
    StarletteDeprecationWarning = DeprecationWarning  # type: ignore

warnings.filterwarnings(
    "ignore",
    message=r".*Using `httpx` with `starlette\.testclient` is deprecated.*",
    category=StarletteDeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r".*Using `httpx` with `starlette\.testclient` is deprecated.*",
    category=DeprecationWarning,
)

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def app_modules(tmp_path, monkeypatch):
    db_path = tmp_path / "workout-test.db"
    monkeypatch.setenv("WORKOUT_DB_PATH", str(db_path))
    monkeypatch.syspath_prepend(str(APP_DIR))

    for name in ["main", "seed", "database"]:
        import sys
        sys.modules.pop(name, None)

    database = importlib.import_module("database")
    main = importlib.import_module("main")
    database.init_db()  # create_tables (with FK listener) + seed_database
    database.migrate_database()
    return database, main


@pytest.fixture()
def client(app_modules):
    _database, main = app_modules
    return TestClient(main.app)


def pytest_configure(config):
    warnings.filterwarnings(
        "ignore",
        message=r".*Using `httpx` with `starlette\.testclient` is deprecated.*",
    )


def pytest_addoption(parser):
    parser.addoption("--legacy-e2e", action="store_true", help="Run the legacy Playwright flow on supported non-macOS hosts")


def pytest_collection_modifyitems(config, items):
    import sys
    for item in items:
        if item.path.name == "test_e2e_playwright.py":
            if sys.platform == "darwin" or not config.getoption("--legacy-e2e"):
                item.add_marker(pytest.mark.skip(reason="Legacy Playwright E2E; macOS requires approved headed runner"))


@pytest.fixture(autouse=True)
def isolated_external_services(tmp_path, monkeypatch):
    """Never inherit real provider/notification credentials or a user's key store."""
    import os
    import socket
    for name in list(os.environ):
        if name.startswith(("OPENAI_", "DEEPSEEK_", "WUAPI_", "WORKOUT_AI_", "DINGTALK_", "WORKBUDDY_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WORKOUT_KEY_STORE", str(tmp_path / "test-only-key-store.enc"))
    original_connect = socket.socket.connect
    def deny_external_network(sock, address):
        if sock.family == socket.AF_UNIX or (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1")):
            return original_connect(sock, address)
        raise RuntimeError("External network disabled in unit/DOM regression tests; mock the transport")
    monkeypatch.setattr(socket.socket, "connect", deny_external_network)
