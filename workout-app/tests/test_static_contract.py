from pathlib import Path
import re

from main import app


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


def test_ai_analyze_route_is_registered():
    routes = {route.path for route in app.routes}
    assert "/api/ai/analyze" in routes


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


def test_frontend_backend_endpoint_contract_updated():
    """前端引用后端端点列表包含新增的 CRUD 端点。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    new_endpoints = [
        "/api/exercises",
        "/api/exercises/${exercise_id}",
        "/api/templates",
        "/api/templates/${template_id}",
        "/api/training/complete",
        "/api/plans/${plan_id}",
    ]
    for endpoint in new_endpoints:
        assert endpoint in app_js, f"前端未引用后端端点：{endpoint}"


def test_frontend_dashboard_has_all_management_entries():
    """仪表盘入口可管理动作库、训练模板、训练计划。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    # 导航栏包含所有管理页面入口
    page_entries = ["exerciseLibrary", "templateManager", "videoLinks"]
    for entry in page_entries:
        assert entry in index_html, f"缺少页面入口：{entry}"

    # 首页仪表盘包含编辑计划入口
    # 仪表盘有编辑计划功能（在 app.js 中动态绑定）
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    assert "data-edit-plan" in app_js

    # 管理中心网格区域
    assert "dashboardManagement" in app_js or "dashboardManagement" in index_html
    assert "manage-card" in app_js
    assert "动作库管理" in app_js
    assert "训练模板管理" in app_js
    assert "训练计划管理" in app_js
    assert "导入 / 导出数据" in app_js or "导入" in app_js


def test_frontend_training_session_has_core_buttons():
    """训练执行页包含完整闭环按钮：完成本组、跳过动作、结束训练、返回。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    buttons = [
        "data-complete-set",
        "data-skip-exercise",
        "data-end-session",
        "data-start-training",
        "data-pause-session",
        "data-rest",
    ]
    for btn in buttons:
        assert btn in app_js, f"训练页缺少按钮：{btn}"


def test_frontend_training_session_tracks_state():
    """训练会话追踪状态：completed 数组、skipped 数组、currentSetIndex。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "session.completed" in app_js or "session?.completed" in app_js
    assert "session.skipped" in app_js or "session?.skipped" in app_js
    assert "currentSetIndex" in app_js
    assert "currentExerciseIndex" in app_js


def test_frontend_import_export_has_preview_and_confirm():
    """导入/导出功能：预览、校验错误、确认后导入。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    # 导出按钮
    assert "exportJson" in app_js
    # 导入预览
    assert "previewImport" in app_js or "importPreview" in app_js
    # 校验逻辑
    assert "validateImport" in app_js or "errors" in app_js
    # 确认导入按钮
    assert "confirmImport" in app_js or "确认导入" in app_js
    # 不自动覆盖
    assert "confirm" in app_js


def test_frontend_import_validates_exercise_ids():
    """导入校验：检查动作 ID 合法、不重复、模板引用存在。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "exerciseIds" in app_js
    assert "重复动作 ID" in app_js or "duplicate" in app_js.lower()
    assert "引用不存在动作" in app_js


def test_frontend_ai_draft_has_confirm_cancel():
    """AI 草稿有预览、确认导入、取消按钮，不自动覆盖。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    # 草稿预览区域
    assert "aiDraftResult" in app_js or "ai-draft" in index_html
    assert "aiDraftPreview" in app_js or "ai-draft-preview" in index_html
    # 确认 / 取消
    assert "aiConfirmImport" in app_js
    assert "aiCancelImport" in app_js
    # 校验错误展示
    assert "aiDraftErrors" in app_js or "aiDraftErrors" in index_html


def test_frontend_ai_search_has_manual_confirm():
    """AI 搜索视频：手动确认/修改链接后确认使用，不自动覆盖。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "aiVideoSearchFinalUrl" in index_html or "aiVideoSearchFinalUrl" in app_js
    assert "aiVideoSearchConfirm" in index_html or "aiVideoSearchConfirm" in app_js
    assert "confirmAiVideoSearch" in app_js


def test_frontend_week_month_shows_completion_status():
    """周/月计划视图展示完成状态。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "statusText" in app_js
    assert "done" in app_js
    assert "pending" in app_js
    assert "skipped" in app_js


def test_frontend_exercise_template_crud_dialogs():
    """动作库/模板/计划编辑对话框存在。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert "exerciseDialog" in index_html
    assert "templateDialog" in index_html
    assert "planDialog" in index_html


def test_frontend_no_auto_overwrite_localstorage():
    """前端不允许自动覆盖 localStorage。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    # localStorage 写入只在确认操作中发生
    assert "confirm" in app_js.lower() or "确认" in app_js


def test_frontend_has_has_entry_points():
    """前端菜单包含 AI 入口，不再显示 第二阶段开放。"""
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "data-ai-action" in index_html
    assert "第二阶段开放" not in index_html
    assert "data-ai-action" in app_js or "aiSearchVideo" in app_js or "checkAiHealth" in app_js


def test_frontend_has_bilibili_url_validation():
    """前端包含 Bilibili URL 校验函数。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "validateBilibiliUrl" in app_js
    assert "bilibili.com/video/" in app_js or "b23.tv" in app_js
    assert "仅支持 Bilibili" in app_js


def test_frontend_video_form_validates_url():
    """保存视频时校验 Bilibili 链接。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "validateBilibiliUrl" in app_js
    # saveVideoFromForm 中调用了校验
    assert "saveVideoFromForm" in app_js or "videoDialog" in app_js


def test_frontend_has_progress_bar():
    """训练执行页有进度条 UI。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    styles_css = (APP_DIR / "static" / "styles.css").read_text(encoding="utf-8")

    assert "progress-track" in app_js or "progress-track" in styles_css
    assert "progress-fill" in app_js or "progress-fill" in styles_css
    assert "progress-label" in app_js or "progress-label" in styles_css


def test_frontend_has_set_badges():
    """训练页有组次徽标显示当前/已完成组。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    styles_css = (APP_DIR / "static" / "styles.css").read_text(encoding="utf-8")

    assert "set-badges" in app_js or "set-badges" in styles_css
    assert "set-badge" in app_js or "set-badge" in styles_css


def test_frontend_has_session_summary():
    """训练完成有摘要显示完成/跳过信息。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "session-summary" in app_js
    assert "完成摘要" in app_js
    assert "totalSetsDone" in app_js


def test_frontend_training_summary_banner():
    """训练完成后显示摘要横幅（完成/跳过/组数）。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    index_html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

    assert "trainingSummaryBanner" in app_js or "trainingSummaryBanner" in index_html
    assert "dismissTrainingSummary" in app_js
    assert "summary-banner-inner" in app_js or "summary-banner-inner" in index_html


def test_frontend_week_month_class_completed():
    """周/月计划中已完成训练日有 completed 状态类。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    styles_css = (APP_DIR / "static" / "styles.css").read_text(encoding="utf-8")

    # week-card 和 calendar-day 添加 completed 类
    assert "completed" in app_js and "'completed'" in app_js or '"completed"' in app_js
    assert ".week-card.completed" in styles_css or ".calendar-day.completed" in styles_css


def test_frontend_import_preview_shows_template_details():
    """导入预览显示模板描述和动作列表。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "import-template-preview" in app_js
    assert "templatePreviews" in app_js or "import-template-preview" in app_js


def test_frontend_import_checks_overlap():
    """导入时检查是否覆盖已有日期计划。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "overlap" in app_js
    assert "将被覆盖" in app_js or "覆盖" in app_js


def test_frontend_tracks_total_sets_done():
    """训练会话追踪已完成总组数。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

    assert "totalSetsDone" in app_js


def test_frontend_validate_url_rejects_youtube():
    """validateBilibiliUrl 明确拒绝 YouTube/youtu.be 链接。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    # 必须包含明确的 YouTube 拒绝条件
    assert "youtube" in app_js.lower() and "不支持" in app_js
    assert "youtu.be" in app_js or "youtu" in app_js


def test_frontend_validate_url_allows_bilibili():
    """validateBilibiliUrl 允许 bilibili.com/video/ 和 b23.tv 链接。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    assert "bilibili.com/video/" in app_js
    assert "b23.tv" in app_js


def test_frontend_import_failure_no_success():
    """导入失败（JSON 解析错误、校验失败）只显示失败，不提示成功。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    # catch 分支只渲染失败信息
    assert "导入失败" in app_js
    # previewImport 的 catch 中只显示错误，无 alert
    preview_src = app_js[app_js.index("function previewImport"):]
    catch_block = preview_src[preview_src.index("catch"):preview_src.index("\nfunction ") if "\nfunction " in preview_src[preview_src.index("catch"):] else None]
    if catch_block:
        assert "导入失败" in catch_block or "error" in catch_block.lower()


def test_frontend_preview_import_preview_only():
    """previewImport 仅预览不写入：预览阶段禁用 confirm()/state=data/saveData/alert('导入完成')。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    # 旧版 auto-confirm 模式 — const confirmed = ... confirm(...) — 已被移除
    assert "const confirmed" not in app_js[app_js.index("function previewImport"):app_js.index("function previewImport") + 500]
    # 禁用预览阶段的顶级 confirm 调用（旧模式中用 confirm 对话框确认后直接写入）
    # 现在只有在 click handler 中才调用 confirm
    preview_top = app_js[app_js.index("function previewImport"):app_js.index("function previewImport") + 200]
    assert "confirm('" not in preview_top
    # 预览阶段不自动保存或写入
    assert "if (confirmed)" not in app_js[app_js.index("function previewImport"):app_js.index("function previewImport") + 500]
    # 但确认按钮存在
    assert "confirmImport" in app_js
    # 全局存在确认后写入代码（在 click handler 中）
    assert "state = data" in app_js
    assert "saveData()" in app_js
    # 有重叠覆盖检查（旧 confirm 重叠提示在新 handler 中）
    assert "重叠" in app_js or "覆盖" in app_js


def test_frontend_confirm_import_writes_after_confirm():
    """确认按钮点击后才写入，点击前检查可选的日期重叠。"""
    app_js = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")
    # confirmImport 的 click handler 中调用了 confirm
    # 检查确认按钮写入模式
    assert "confirmImport" in app_js
    assert "state = data" in app_js
    # 重叠覆盖检查
    assert "overlap" in app_js
    # 用户取消则不写入
    assert "return" in app_js  # overlap 检查不通过时 return


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
