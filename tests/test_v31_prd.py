from pathlib import Path
import sqlite3

APP_DIR = Path(__file__).resolve().parents[1]


def test_v31_required_sqlite_tables_exist(app_modules):
    database, _main = app_modules
    db_path = Path(database.DATABASE_PATH)
    assert db_path.exists()

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert {"exercises", "workout_plans", "workout_sessions", "session_records"} <= tables


def test_v31_plan_session_record_ai_feedback_closed_loop(client, app_modules, monkeypatch):
    _database, main = app_modules

    monkeypatch.setattr(
        main,
        "call_openai_compatible",
        lambda *args, **kwargs: {
            "score": 86,
            "summary": "训练完成度良好",
            "adjustments": ["下次肩颈动作减少耸肩", "保持低强度循序渐进"],
        },
    )
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "test-key")
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("WORKOUT_AI_MODEL", "test-model")

    exercise = client.post(
        "/api/exercises",
        json={
            "name": "肩颈放松拉伸",
            "category": "肩颈",
            "bodyParts": ["肩部", "颈部"],
            "difficulty": "低",
            "defaultSets": 2,
            "defaultReps": "8次",
            "durationSeconds": 45,
            "notes": "动作慢，不耸肩",
            "tips": ["保持呼吸"],
            "videos": [{"title": "B站搜索", "url": "https://search.bilibili.com/all?keyword=肩颈放松", "isDefault": True}],
        },
    )
    assert exercise.status_code == 201
    exercise_id = exercise.json()["id"]

    generated = client.post(
        "/api/plans/generate",
        json={
            "date": "2026-06-18",
            "title": "办公室肩颈放松",
            "theme": "久坐恢复",
            "exerciseIds": [exercise_id],
            "notes": "12 分钟低强度",
        },
    )
    assert generated.status_code == 200
    plan = generated.json()["plan"]
    assert plan["date"] == "2026-06-18"
    assert plan["items"][0]["exercise_id"] == exercise_id

    plans = client.get("/api/plans", params={"date": "2026-06-18"})
    assert plans.status_code == 200
    assert plans.json()["plans"][0]["id"] == plan["id"]

    started = client.post("/api/session/start", json={"plan_id": plan["id"]})
    assert started.status_code == 200
    session = started.json()["session"]
    assert session["status"] == "in_progress"
    assert session["plan_id"] == plan["id"]

    updated = client.post(
        "/api/session/update",
        json={
            "session_id": session["id"],
            "exercise_id": exercise_id,
            "status": "completed",
            "sets_completed": 2,
            "reps_completed": "8次",
            "duration_seconds": 90,
            "notes": "完成，无疼痛",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["record"]["status"] == "completed"

    completed = client.post(
        "/api/session/complete",
        json={"session_id": session["id"], "notes": "整体轻松", "rating": 5},
    )
    assert completed.status_code == 200
    assert completed.json()["session"]["status"] == "completed"
    assert completed.json()["summary"]["completed_records"] == 1

    analysis = client.post("/api/ai/analyze", json={"session_id": session["id"]})
    assert analysis.status_code == 200
    assert analysis.json()["status"] == "analysis"
    assert analysis.json()["analysis"]["score"] == 86

    feedback = client.post(
        "/api/ai/feedback",
        json={"session_id": session["id"], "rating": 4, "comment": "建议保持低强度"},
    )
    assert feedback.status_code == 200
    assert feedback.json()["status"] == "feedback_recorded"

    with sqlite3.connect(Path(_database.DATABASE_PATH)) as conn:
        sessions = conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0]
        records = conn.execute("SELECT COUNT(*) FROM session_records").fetchone()[0]
    assert sessions == 1
    assert records == 1


def test_v31_ai_analyze_does_not_write_database(client, app_modules, monkeypatch):
    database, main = app_modules
    monkeypatch.setattr(main, "call_openai_compatible", lambda *args, **kwargs: {"score": 75, "summary": "只读分析", "adjustments": []})
    monkeypatch.setenv("WORKOUT_AI_API_KEY", "test-key")
    monkeypatch.setenv("WORKOUT_AI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("WORKOUT_AI_MODEL", "test-model")

    exercise = client.post("/api/exercises", json={"name": "低强度拉伸", "category": "恢复"}).json()
    plan = client.post("/api/plans/generate", json={"date": "2026-06-19", "exerciseIds": [exercise["id"]]}).json()["plan"]
    session = client.post("/api/session/start", json={"plan_id": plan["id"]}).json()["session"]
    client.post("/api/session/update", json={"session_id": session["id"], "exercise_id": exercise["id"], "status": "completed"})
    client.post("/api/session/complete", json={"session_id": session["id"]})

    with sqlite3.connect(Path(database.DATABASE_PATH)) as conn:
        before_sessions = conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0]
        before_records = conn.execute("SELECT COUNT(*) FROM session_records").fetchone()[0]
        before_plans = conn.execute("SELECT COUNT(*) FROM workout_plans").fetchone()[0]

    response = client.post("/api/ai/analyze", json={"session_id": session["id"]})
    assert response.status_code == 200

    with sqlite3.connect(Path(database.DATABASE_PATH)) as conn:
        after_sessions = conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0]
        after_records = conn.execute("SELECT COUNT(*) FROM session_records").fetchone()[0]
        after_plans = conn.execute("SELECT COUNT(*) FROM workout_plans").fetchone()[0]

    assert (after_sessions, after_records, after_plans) == (before_sessions, before_records, before_plans)



def test_v31_static_pages_exist():
    static_dir = APP_DIR / "static"
    for name in ["dashboard.html", "exercises.html", "plans.html", "session.html", "stats.html"]:
        assert (static_dir / name).exists()


def test_v31_session_page_has_execution_controls():
    session_html = (APP_DIR / "static" / "session.html").read_text(encoding="utf-8")
    assert "当前动作卡片" in session_html
    assert "Bilibili 视频 iframe" in session_html
    assert "progressbar" in session_html
    assert "完成按钮" in session_html
    assert "自动切换下一个动作" in session_html
