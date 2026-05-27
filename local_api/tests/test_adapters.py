"""Phase 8A — Unit tests for mock adapters.

Run with:
    cd D:/hermes-agent
    python -m pytest local_api/tests/test_adapters.py -v
"""

import pytest

from local_api.adapters.apple_adapter import MockAppleAdapter
from local_api.adapters.weather_adapter import MockWeatherAdapter
from local_api.database import init_db, reset_db


@pytest.fixture(autouse=True)
def clean_db():
    reset_db()
    init_db()
    yield
    reset_db()


class TestMockAppleAdapter:
    """MockAppleAdapter: push, pull, validate_config."""

    def test_push_returns_success_and_external_id(self):
        adapter = MockAppleAdapter()
        result = adapter.push(
            {"title": "Team standup"},
            {"sync_id": "sync_001", "sync_target": "apple_calendar"},
        )
        assert result.success is True
        assert result.external_id is not None
        assert len(result.external_id) == 12
        assert result.sync_result == "success"

    def test_pull_returns_dict(self):
        adapter = MockAppleAdapter()
        result = adapter.pull("ext_abc123")
        assert isinstance(result, dict)
        assert result["source"] == "apple_calendar"
        assert "external_id" in result

    def test_validate_config_returns_valid(self):
        adapter = MockAppleAdapter()
        valid, err = adapter.validate_config()
        assert valid is True
        assert err is None


class TestMockWeatherAdapter:
    """MockWeatherAdapter: push, pull, validate_config."""

    def test_push_returns_weather_inline(self):
        adapter = MockWeatherAdapter()
        result = adapter.push(
            {"title": "Check weather"},
            {"sync_id": "sync_002", "sync_target": "weather"},
        )
        assert result.success is True
        assert result.external_id == "weather_inline"
        assert result.sync_result == "success"

    def test_pull_returns_dict(self):
        adapter = MockWeatherAdapter()
        result = adapter.pull("weather_inline")
        assert isinstance(result, dict)
        assert result["source"] == "weather"
        assert "temp" in result
        assert "condition" in result

    def test_validate_config_returns_valid(self):
        adapter = MockWeatherAdapter()
        valid, err = adapter.validate_config()
        assert valid is True
        assert err is None
