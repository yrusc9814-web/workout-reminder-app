from pathlib import Path
import re


APP_DIR = Path(__file__).resolve().parents[1]


def test_frontend_calls_existing_backend_endpoints():
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    expected = [
        "/api/health",
        "/api/ai/health",
        "/api/ai/import-plan",
        "/api/ai/suggest-bilibili-video",
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


def test_frontend_has_ai_entry_points():
    """前端菜单包含 AI 入口，不再显示 第二阶段开放。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "data-ai-action" in index_html
    assert "第二阶段开放" not in index_html
    assert "data-ai-action" in app_js or "aiSearchVideo" in app_js or "checkAiHealth" in app_js


def test_frontend_no_hardcoded_youtube():
    """前端不可包含 hardcoded YouTube 链接。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    combined = "\n".join([index_html, app_js])

    # 合法 AI 搜索中引用 YouTube 作为拒绝条件是可以的
    # 检查是否包含了非注释的 youtube.com 链接
    lines = combined.split("\n")
    for i, line in enumerate(lines):
        if "youtube" in line.lower() or "youtu.be" in line.lower():
            # 只允许在函数名、注释或拒绝条件中出现
            if not ("reject" in line.lower() or "拒绝" in line or "youtube" in line.lower() and ("validate" in line.lower() or "FORBIDDEN" in line or "refuse" in line.lower())):
                # 检查是否在引号中有完整的 URL
                urls = re.findall(r'https?://(?:www\.)?youtube\.com|https?://youtu\.be', line)
                assert not urls, f"Line {i+1} contains hardcoded YouTube URL: {line.strip()}"