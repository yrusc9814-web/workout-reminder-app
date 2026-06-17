import importlib
import os
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture()
def app_modules(tmp_path, monkeypatch):
    db_path = tmp_path / "workout-test.db"
    monkeypatch.setenv("WORKOUT_DB_PATH", str(db_path))
    monkeypatch.syspath_prepend(str(APP_DIR))

    for name in ["main", "seed", "database"]:
        sys.modules.pop(name, None)

    database = importlib.import_module("database")
    main = importlib.import_module("main")
    database.Base.metadata.create_all(bind=database.engine)
    database.seed_database()
    return database, main


@pytest.fixture()
def client(app_modules):
    _database, main = app_modules
    return TestClient(main.app)
