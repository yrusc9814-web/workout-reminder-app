from pathlib import Path
import re

from main import app


APP_DIR = Path(__file__).resolve().parents[1]


def test_ai_analyze_route_is_registered():
    routes = {route.path for route in app.routes}
    assert "/api/ai/analyze" in routes


def test_frontend_primary_copy_is_chinese():
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert "轻动日记·管理界面 v25" in index_html
    assert "<h1 class=\"welcome-title\">轻动日记</h1>" in index_html
    assert "今日训练" in index_html
    assert "开始训练" in index_html
    assert "动作库" in index_html
    assert "月计划" in index_html
    assert "AI健身教练" in index_html
    assert "Workout Reminder App" not in index_html
    assert "运动提醒 App" not in index_html


def test_v25_formal_page_has_no_demo_business_facts():
    """The production page starts from empty/loading state and backend data."""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert "demoPlans" not in index_html
    assert "DEMO_YEAR" not in index_html
    assert "完成度 58%" not in index_html
    assert "累计 <strong>210</strong> 分钟" not in index_html
    assert "已完成 7" not in index_html
    assert "18 组" not in index_html
    assert "v25ClearMonth" in index_html
    assert "monthRequests" in index_html
    assert "训练已由后端确认，但回读刷新失败" in index_html
    assert "monthRetryBtn" in index_html
    assert "v25RemoteDataVerified" in index_html
    assert "bootOwnsDisplay" in index_html
    assert "v25ApplyStats(v25Remote.stats, bootRangeStatus" in index_html
    assert "data-month-status" in index_html
    assert "action_stats" in index_html


def test_windows_one_click_launcher_exists():
    launcher = APP_DIR / "scripts" / "start_workout_app.cmd"
    shortcut_script = APP_DIR / "scripts" / "create_start_shortcut.ps1"

    launcher_text = launcher.read_text(encoding="utf-8")
    shortcut_text = shortcut_script.read_text(encoding="utf-8")

    assert "uvicorn main:app" in launcher_text
    assert "http://127.0.0.1:3000" in launcher_text
    assert "start_workout_app.cmd" in shortcut_text
    assert "运动提醒 App.lnk" in shortcut_text


def test_frontend_dashboard_has_all_management_entries():
    """v25 主导航覆盖日/周/月计划、动作库、训练方案、AI 与设置。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert 'data-nav="day"' in index_html
    assert 'data-nav="week"' in index_html
    assert 'data-view="month"' in index_html
    assert 'data-view="library"' in index_html
    assert 'data-view="template"' in index_html
    assert 'data-view="ai"' in index_html
    assert 'data-view="settings"' in index_html
    assert 'id="view-home"' in index_html
    assert 'id="view-month"' in index_html
    assert 'id="view-library"' in index_html
    assert 'id="view-template"' in index_html
    assert 'id="view-ai"' in index_html
    assert 'id="view-settings"' in index_html
    assert "动作库" in index_html
    assert "训练方案" in index_html
    assert "AI健身教练" in index_html


def test_light_theme_has_independent_fitness_background_layer():
    """v25 使用内置字体、天空层和欢迎屏作为正式视觉层，不再依赖旧 fitness 背景卡。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert 'src: url("/static/assets/fonts/AaTouChiKeAiChangDaDe.woff2")' in index_html
    assert 'id="welcomeScreen"' in index_html
    assert 'class="welcome-screen"' in index_html
    assert 'class="bouncy-deco deco-1"' in index_html
    assert 'class="bouncy-deco deco-4"' in index_html
    assert 'class="welcome-center"' in index_html
    assert 'class="sky-layer"' in index_html
    assert "/static/assets/images/sheep-logo.webp" in index_html
    assert "body.theme-dark" in index_html
    assert "fitness-photo-bg" not in index_html


def test_dashboard_management_cards_use_explicit_visual_layers():
    """v25 首页使用日计划 hero 与导航药丸，而不是旧管理中心分层卡片。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert 'class="topnav glass phase2-nav"' in index_html
    assert 'class="nav-pills"' in index_html
    assert 'class="nav-pill"' in index_html
    assert 'id="dayHero"' in index_html
    assert 'id="todayTitle"' in index_html
    assert ">今日训练<" in index_html
    assert 'id="startTodayBtn"' in index_html
    assert ">开始训练<" in index_html
    assert 'data-card-contract="background overlay icon content"' not in index_html


def test_sidebar_support_sections_are_collapsible_and_clean():
    """v25 用「更多」折叠菜单承载动作库、训练方案、AI 与设置。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="moreMenu"' in index_html
    assert "<summary>更多</summary>" in index_html
    assert 'data-view="library"' in index_html
    assert 'data-view="template"' in index_html
    assert 'data-view="ai"' in index_html
    assert 'data-view="settings"' in index_html
    assert "辅助工具" not in index_html
    assert "系统状态" not in index_html


def test_dashboard_only_uses_a_static_welcome_image():
    """v26 欢迎屏使用 Q 弹开屏（气泡视差 + 爱心尾迹 + 小羊 logo），点击进入日计划。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="welcomeScreen"' in index_html
    assert 'src="/static/assets/images/sheep-logo.webp"' in index_html
    assert "<h1 class=\"welcome-title\">轻动日记</h1>" in index_html
    assert 'class="welcome-btn"' in index_html
    assert "开启轻盈时刻" in index_html
    assert ".heart-trail" in index_html
    assert "welcome-sheep.png" not in index_html
    assert "WELCOME BACK" not in index_html


def test_frontend_exercise_template_crud_dialogs():
    """v25 动作库、训练方案与日计划编辑入口存在于正式页面结构中。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="view-library"' in index_html
    assert 'id="libGrid"' in index_html
    assert 'id="libSearch"' in index_html
    assert 'id="newExerciseBtn"' in index_html
    assert 'id="view-template"' in index_html
    assert 'id="todayDetailBtn"' in index_html
    assert ">编辑今日清单<" in index_html
    assert 'id="clearTodayBtn"' in index_html


def test_frontend_has_has_entry_points():
    """v25 菜单包含 AI 教练入口，并接线统一 session 完成契约。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert 'data-view="ai"' in index_html
    assert 'id="view-ai"' in index_html
    assert "AI健身教练" in index_html
    assert 'id="chatInput"' in index_html
    assert 'id="chatSendBtn"' in index_html
    assert "/api/session/start" in index_html
    assert "/api/session/update" in index_html
    assert "/api/session/complete" in index_html
    assert "/api/logs/complete" not in index_html
    assert "第二阶段开放" not in index_html


def test_frontend_no_hardcoded_youtube():
    """正式首页的有效 URL 约束默认执行，不受 legacy 开关影响。"""
    _assert_no_hardcoded_youtube((APP_DIR / "static" / "index.html").read_text(encoding="utf-8"))


def _assert_no_hardcoded_youtube(source):
    # 合法 AI 搜索中引用 YouTube 作为拒绝条件是可以的
    # 检查是否包含了非注释的 youtube.com 链接
    lines = source.split("\n")
    for i, line in enumerate(lines):
        if "youtube" in line.lower() or "youtu.be" in line.lower():
            # 只允许在函数名、注释或拒绝条件中出现
            if not ("reject" in line.lower() or "拒绝" in line or "youtube" in line.lower() and ("validate" in line.lower() or "FORBIDDEN" in line or "refuse" in line.lower())):
                # 检查是否在引号中有完整的 URL
                urls = re.findall(r'https?://(?:www\.)?youtube\.com|https?://youtu\.be', line)
                assert not urls, f"Line {i+1} contains hardcoded YouTube URL: {line.strip()}"
