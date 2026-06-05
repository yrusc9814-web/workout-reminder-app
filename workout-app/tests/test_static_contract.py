from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]


def test_frontend_calls_existing_backend_endpoints():
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    expected = [
        "/api/health",
        "/api/today",
        "/api/plans/week?date=${isoToday}",
        "/api/plans/month?year=${year}&month=${month}",
        "/api/calendar?year=${year}&month=${month}",
        "/api/stats",
        "/api/settings",
        "/api/logs",
        "/api/logs/${action}",
        "/api/reminders/test",
    ]

    for endpoint in expected:
        assert endpoint in app_js