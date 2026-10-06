"""VAN-23 production-page DOM and backup import regression gates."""
from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parents[1]
DOM_DEPS = Path(os.environ.get("VAN16_DOM_DEPS", "/private/tmp/van13-jsdom-deps/node_modules"))
NODE = os.environ.get("VAN23_NODE", "/Users/vantawork/.local/bin/node")
EVIDENCE_DIR = APP_DIR.parent / "van23-evidence"


def test_van23_formal_production_dom_backup_flow(tmp_path: Path):
    """Use the complete static page, including FileReader and API readback mocks."""
    if not (DOM_DEPS / "jsdom").exists():
        pytest.fail(f"VAN-23 JSDOM dependency is required at {DOM_DEPS}; refusing to skip the gate")
    db_path = tmp_path / "van23-isolated.sqlite"
    env = {
        **os.environ,
        "VAN16_DOM_DEPS": str(DOM_DEPS),
        "WORKOUT_DB_PATH": str(db_path),
        "WORKOUT_DISABLE_SEED": "1",
    }
    result = subprocess.run(
        [NODE, "tests/van23_real_dom_behavior.js"],
        cwd=str(APP_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "van23-executor-dom-harness.log").write_text(
        (result.stdout or "") + (result.stderr or ""), encoding="utf-8"
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert '"PASS":true' in result.stdout.replace(" ", "")


RAW_CASES = [
    ("tag", "<b>test</b>"),
    ("script", "<script>window.__van23Marker++</script>"),
    ("img", '<img src=x onerror="window.__van23Marker++">'),
    ("svg", '<svg onload="window.__van23Marker++"></svg>'),
    ("attribute", '" onmouseover="window.__van23Marker++" data-x="'),
    ("ordinary", "普通中文🧘 A & B <5kg '单双引号'"),
]


@pytest.mark.parametrize("case_name,raw", RAW_CASES, ids=[case[0] for case in RAW_CASES])
def test_van23_api_sqlite_preserves_raw_backup_text_and_history(client, app_modules, case_name, raw):
    """Canonical import keeps raw fields and historical completion facts in SQLite."""
    database, _main = app_modules
    exercises = client.get("/api/exercises").json()["exercises"]
    exercise_id = exercises[0]["id"]
    history_date = "2035-09-01"
    import_date = f"2035-09-{10 + [item[0] for item in RAW_CASES].index(case_name):02d}"

    history = client.put(
        f"/api/plans/by-date/{history_date}",
        json={
            "date": history_date,
            "title": "历史完成计划",
            "focus": "历史焦点",
            "notes": "历史备注",
            "is_training_day": True,
            "items": [{"exercise_id": exercise_id, "name": "历史动作", "sets": 1, "reps": 1, "spec": "历史规格"}],
        },
    )
    assert history.status_code == 200, history.text
    history_plan_id = history.json()["plan"]["id"]
    completed = client.post("/api/logs/complete", json={"plan_id": history_plan_id, "notes": "历史完成事实"})
    assert completed.status_code == 200, completed.text

    title = f"备份标题 {raw}"
    focus = f"备份焦点 {raw}"
    plan_notes = f"备份备注 {raw}"
    item_name = f"备份动作 {raw}"
    description = f"动作说明 {raw}"
    spec = f"动作规格 {raw}"
    imported = client.post(
        "/api/plans/import",
        json={
            "replace_months": True,
            "plans": [{
                "date": import_date,
                "title": title,
                "focus": focus,
                "notes": plan_notes,
                "is_training_day": True,
                "items": [{
                    "exercise_id": exercise_id,
                    "name": item_name,
                    "sets": 2,
                    "reps": 8,
                    "duration_seconds": 60,
                    "notes": description,
                    "spec": spec,
                }],
            }],
        },
    )
    assert imported.status_code == 200, imported.text

    fetched = client.get("/api/plans", params={"date": import_date})
    assert fetched.status_code == 200
    imported_plan = fetched.json()["plans"][0]
    assert imported_plan["title"] == title
    assert imported_plan["theme"] == focus
    assert imported_plan["notes"] == plan_notes
    imported_item = imported_plan["items"][0]
    assert imported_item["name"] == item_name
    assert imported_item["notes"] == description
    assert imported_item["spec"] == spec

    with database.SessionLocal() as db:
        stored_history = db.get(database.WorkoutPlan, history_plan_id)
        stored_history_logs = db.query(database.WorkoutLog).filter_by(plan_id=history_plan_id).all()
        stored_plan = db.query(database.WorkoutPlan).filter_by(plan_date=date.fromisoformat(import_date)).one()
        stored_item = db.query(database.WorkoutExercise).filter_by(plan_id=stored_plan.id).one()
        assert stored_history.title == "历史完成计划"
        assert len(stored_history_logs) == 1
        assert stored_history_logs[0].status == "completed"
        assert stored_plan.title == title
        assert stored_plan.focus == focus
        assert stored_plan.notes == plan_notes
        assert stored_item.name == item_name
        assert stored_item.description == description
        assert stored_item.spec == spec
