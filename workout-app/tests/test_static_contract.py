from pathlib import Path
import re


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
        "/api/reminders/dingtalk/send",
        "/api/todos/dingtalk/create",
    ]

    for endpoint in expected:
        assert endpoint in app_js


def test_frontend_primary_copy_is_chinese():
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    visible_copy = "\n".join([index_html, app_js])

    forbidden_copy = [
        "Workout Reminder App",
        "Progress",
        "This week",
        "Month list",
        "Mock reminder",
        "Activity",
        "Complete",
        "Skip",
        "Postpone",
        "Rest day",
        "Hip stability",
        "Supine pelvic clock",
        "Supported bridge hold",
        "Side-lying hip abduction",
        "Dead bug heel taps",
        "Seated hip march",
    ]
    # Normalize: remove JS identifiers, function names, and quoted strings so we test only visible copy.
    visible_clean = re.sub(r'[a-zA-Z_][a-zA-Z0-9_]*\s*\(', ' ', visible_copy)
    visible_clean = re.sub(r'[\'"`]([^\'"]{0,30})[\'"`]', ' ', visible_clean)
    for text in forbidden_copy:
        assert text not in visible_clean

    assert re.search(r'运动提醒 App', visible_copy)
    assert re.search(r'今日训练', visible_copy)
    assert re.search(r'打开.*Bilibili', visible_copy)


def test_windows_one_click_launcher_exists():
    launcher = APP_DIR / "scripts" / "start_workout_app.cmd"
    shortcut_script = APP_DIR / "scripts" / "create_start_shortcut.ps1"

    launcher_text = launcher.read_text(encoding="utf-8")
    shortcut_text = shortcut_script.read_text(encoding="utf-8")

    assert "uvicorn main:app" in launcher_text
    assert "http://127.0.0.1:3000" in launcher_text
    assert "start_workout_app.cmd" in shortcut_text
    assert "运动提醒 App.lnk" in shortcut_text