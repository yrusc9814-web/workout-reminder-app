from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from database import (
    Exercise,
    MigrationLog,
    SessionRecord,
    WorkoutExercise,
    WorkoutLog,
    WorkoutPlan,
    WorkoutSession,
)

MIGRATION_NAME = "v24-training-state-v1"
SOURCE_FORMAT = "qingdong-training-backup"
SOURCE_VERSION = 1


class MigrationInputError(ValueError):
    pass


class StalePreviewError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def normalize_bundle(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise MigrationInputError("迁移源必须是 JSON 对象")
    source = payload.get("source", payload)
    if isinstance(source, dict) and isinstance(source.get("bundle"), dict):
        source = source["bundle"]
    if not isinstance(source, dict):
        raise MigrationInputError("迁移 source 必须是 JSON 对象")
    if source.get("format") != SOURCE_FORMAT:
        raise MigrationInputError("不支持的 v24 导出 format")
    if source.get("version") != SOURCE_VERSION:
        raise MigrationInputError("不支持的 v24 导出 version")
    state = source.get("trainingState")
    if not isinstance(state, dict) or not isinstance(state.get("data"), dict):
        raise MigrationInputError("缺少合法 trainingState.data")
    data = state["data"]
    for key in ("calendarPlans", "customTrainingPlans", "dailySessions"):
        if key in data and (not isinstance(data[key], dict)):
            raise MigrationInputError(f"{key} 必须是对象")
    return source


def _item_name_and_spec(item: Any) -> tuple[str, str] | None:
    if isinstance(item, dict):
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        return name.strip(), str(item.get("spec") or "")
    if not isinstance(item, str) or not item.strip():
        return None
    raw = item.strip()
    name, separator, spec = raw.partition(" · ")
    return name.strip(), spec.strip() if separator else ""


def _parse_int(pattern: str, value: str) -> int | None:
    match = re.search(pattern, value or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _item_values(exercise: Exercise, spec: str) -> dict:
    sets = _parse_int(r"(\d+)\s*(?:组|sets?)", spec) or exercise.default_sets
    reps = _parse_int(r"(\d+)\s*(?:次|reps?)", spec)
    if reps is None and exercise.default_reps:
        reps = _parse_int(r"(\d+)", exercise.default_reps)
    duration = _parse_int(r"(\d+)\s*(?:秒|seconds?)", spec)
    if duration is None and "分钟" in spec:
        minutes = _parse_int(r"(\d+)\s*分钟", spec)
        duration = minutes * 60 if minutes is not None else None
    if duration is None:
        duration = exercise.duration_seconds
    return {
        "sets": sets or 1,
        "reps": reps,
        "duration_seconds": duration,
    }


def _fingerprint(db: Session) -> str:
    rows: dict[str, list[dict]] = {}
    for model, fields in (
        (Exercise, ("id", "name", "category", "default_sets", "default_reps", "duration_seconds")),
        (WorkoutPlan, ("id", "plan_date", "template_id", "title", "is_training_day", "focus", "notes")),
        (WorkoutExercise, ("id", "plan_id", "exercise_id", "sort_order", "name", "sets", "duration_seconds", "reps")),
        (WorkoutSession, ("id", "plan_id", "status", "started_at", "completed_at", "notes")),
        (SessionRecord, ("id", "session_id", "exercise_id", "status", "duration_seconds", "completed_at")),
        (WorkoutLog, ("id", "plan_id", "session_id", "log_date", "action", "status", "notes")),
    ):
        values = []
        for row in db.query(model).order_by(model.id.asc()).all():
            values.append({field: str(getattr(row, field)) if getattr(row, field) is not None else None for field in fields})
        rows[model.__tablename__] = values
    return _sha256(rows)


def _exercise_map(db: Session) -> dict[str, list[Exercise]]:
    result: dict[str, list[Exercise]] = {}
    for exercise in db.query(Exercise).order_by(Exercise.id.asc()).all():
        result.setdefault(exercise.name, []).append(exercise)
    return result


def _date_key(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _block(blockers: list[dict], code: str, **details: Any) -> None:
    blockers.append({"code": code, **details})


def build_preview(db: Session, payload: dict) -> dict:
    source = normalize_bundle(payload)
    data = source["trainingState"]["data"]
    calendar = data.get("calendarPlans") or {}
    sessions = data.get("dailySessions") or {}
    exercises = _exercise_map(db)
    blockers: list[dict] = []
    plan_actions: list[dict] = []
    session_actions: list[dict] = []

    for key in sorted(calendar):
        day = _date_key(key)
        plan = calendar[key]
        if day is None:
            _block(blockers, "invalid_plan_date", date=key)
            continue
        if not isinstance(plan, dict) or not isinstance(plan.get("items"), list):
            _block(blockers, "unresolved_plan_item", date=key, item=None, reason="items_missing")
            continue
        parsed_items = []
        for raw_item in plan["items"]:
            parsed = _item_name_and_spec(raw_item)
            if parsed is None:
                _block(blockers, "unresolved_plan_item", date=key, item=raw_item, reason="invalid_item")
                continue
            name, spec = parsed
            matches = exercises.get(name, [])
            if len(matches) != 1:
                _block(
                    blockers,
                    "unresolved_exercise" if not matches else "ambiguous_exercise",
                    date=key,
                    item=name,
                )
                continue
            parsed_items.append({"name": name, "spec": spec, "exercise_id": matches[0].id, **_item_values(matches[0], spec)})
        plan_actions.append({
            "date": key,
            "title": str(plan.get("title") or "历史训练计划"),
            "focus": str(plan.get("body") or plan.get("intensity") or ""),
            "is_training_day": plan.get("status") != "rest",
            "items": parsed_items,
        })

    for key in sorted(sessions):
        session = sessions[key]
        if not isinstance(session, dict) or not isinstance(session.get("items"), list):
            _block(blockers, "unresolved_session", date=key, reason="items_missing")
            continue
        done = bool(session.get("done"))
        started = bool(session.get("started"))
        if started and not done:
            _block(blockers, "unfinished_session", date=key)
        if not done:
            continue
        items = []
        for raw_item in session["items"]:
            parsed = _item_name_and_spec(raw_item)
            if parsed is None:
                _block(blockers, "unresolved_plan_item", date=key, item=raw_item, reason="invalid_session_item")
                continue
            name, spec = parsed
            matches = exercises.get(name, [])
            if len(matches) != 1:
                _block(blockers, "unresolved_exercise" if not matches else "ambiguous_exercise", date=key, item=name)
                continue
            items.append({"name": name, "spec": spec, "exercise_id": matches[0].id})
        if not started or not items or not isinstance(session.get("stepIndex"), int) or session["stepIndex"] != len(items) - 1:
            _block(blockers, "unverifiable_completion", date=key, reason="done_not_at_last_verified_item")
        plan_action = next((item for item in plan_actions if item["date"] == key), None)
        existing_plan = db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == _date_key(key)).one_or_none()
        if plan_action is None and existing_plan is None:
            _block(blockers, "unresolved_plan", date=key)
        existing_completion = None
        if existing_plan is not None:
            existing_completion = db.query(WorkoutLog).filter(
                WorkoutLog.plan_id == existing_plan.id,
                WorkoutLog.status == "completed",
            ).first()
        session_actions.append({
            "date": key,
            "items": items,
            "existing_completion": "skip" if existing_completion else "create",
        })

    affected = _fingerprint(db)
    summary = {
        "calendar_plans": len(plan_actions),
        "done_sessions": len(session_actions),
        "blockers": len(blockers),
        "duration_unknown_sessions": sum(1 for action in session_actions if action["existing_completion"] == "create"),
    }
    body = {
        "migration": MIGRATION_NAME,
        "source_sha256": _sha256(source),
        "affected_fingerprint": affected,
        "plans": plan_actions,
        "sessions": session_actions,
        "blockers": blockers,
        "summary": summary,
    }
    return {
        "status": "blocked" if blockers else "ready",
        "source_sha256": body["source_sha256"],
        "affected_fingerprint": affected,
        "preview_hash": _sha256(body),
        "summary": summary,
        "blockers": blockers,
        "plans": plan_actions,
        "sessions": session_actions,
    }


def _plan_has_history(db: Session, plan_id: int) -> bool:
    return db.query(WorkoutSession).filter(WorkoutSession.plan_id == plan_id).first() is not None or db.query(WorkoutLog).filter(WorkoutLog.plan_id == plan_id).first() is not None


def _source_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload
    if "source" in payload:
        return payload["source"]
    control_keys = {"source_sha256", "preview_hash", "affected_fingerprint"}
    return {key: value for key, value in payload.items() if key not in control_keys}


def commit_preview(db: Session, payload: dict) -> dict:
    source = normalize_bundle(_source_payload(payload))
    source_sha256 = _sha256(source)
    expected_source = payload.get("source_sha256") if isinstance(payload, dict) else None
    expected_preview = payload.get("preview_hash") if isinstance(payload, dict) else None
    expected_fingerprint = payload.get("affected_fingerprint") if isinstance(payload, dict) else None

    # Idempotent replay is checked before the live fingerprint comparison:
    # the first commit itself changes the affected rows.
    if expected_preview:
        existing_log = db.query(MigrationLog).filter(
            MigrationLog.migration_name == MIGRATION_NAME,
            MigrationLog.source_sha256 == source_sha256,
            MigrationLog.preview_hash == expected_preview,
            MigrationLog.status == "committed",
        ).order_by(MigrationLog.id.desc()).first()
        if existing_log is not None:
            return {"status": "already_committed", "migration_log_id": existing_log.id}

    preview = build_preview(db, source)
    for label, expected, actual in (
        ("source_sha256", expected_source, preview["source_sha256"]),
        ("preview_hash", expected_preview, preview["preview_hash"]),
        ("affected_fingerprint", expected_fingerprint, preview["affected_fingerprint"]),
    ):
        if expected and expected != actual:
            raise StalePreviewError(f"{label} 不匹配，stale_preview")
    if preview["status"] != "ready":
        raise MigrationInputError("preview 存在阻断项，不能 commit")

    existing_log = db.query(MigrationLog).filter(
        MigrationLog.migration_name == MIGRATION_NAME,
        MigrationLog.source_sha256 == preview["source_sha256"],
        MigrationLog.preview_hash == preview["preview_hash"],
        MigrationLog.affected_fingerprint == preview["affected_fingerprint"],
        MigrationLog.status == "committed",
    ).order_by(MigrationLog.id.desc()).first()
    if existing_log is not None:
        return {"status": "already_committed", "migration_log_id": existing_log.id, "preview": preview}

    created_plans = 0
    created_items = 0
    created_sessions = 0
    created_records = 0
    created_logs = 0
    for action in preview["plans"]:
        day = date.fromisoformat(action["date"])
        plan = db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == day).one_or_none()
        if plan is None:
            plan = WorkoutPlan(
                plan_date=day,
                title=action["title"],
                is_training_day=action["is_training_day"],
                focus=action["focus"],
                notes="Imported from v24 trainingState; historical timestamps are not available.",
            )
            db.add(plan)
            db.flush()
            created_plans += 1
        elif _plan_has_history(db, plan.id):
            continue
        else:
            plan.title = action["title"]
            plan.is_training_day = action["is_training_day"]
            plan.focus = action["focus"]
            for item in list(plan.exercises):
                db.delete(item)
            db.flush()
        for index, item in enumerate(action["items"], start=1):
            db.add(WorkoutExercise(
                plan_id=plan.id,
                exercise_id=item["exercise_id"],
                sort_order=index,
                name=item["name"],
                description="Imported from v24 exercise item.",
                sets=item["sets"],
                reps=item["reps"],
                duration_seconds=item["duration_seconds"],
            ))
            created_items += 1

    for action in preview["sessions"]:
        day = date.fromisoformat(action["date"])
        plan = db.query(WorkoutPlan).filter(WorkoutPlan.plan_date == day).one_or_none()
        if plan is None:
            raise MigrationInputError(f"迁移时找不到计划：{action['date']}")
        existing = db.query(WorkoutLog).filter(
            WorkoutLog.plan_id == plan.id,
            WorkoutLog.status == "completed",
        ).first()
        if existing is not None:
            continue
        session = WorkoutSession(
            plan_id=plan.id,
            status="completed",
            started_at=None,
            completed_at=None,
            notes="Imported from v24 done=true; historical timestamps and duration unknown.",
        )
        db.add(session)
        db.flush()
        # SQLAlchemy applies the legacy server default when None is inserted;
        # clear it explicitly so unknown historical time remains NULL.
        session.started_at = None
        session.completed_at = None
        db.flush()
        for item in action["items"]:
            db.add(SessionRecord(
                session_id=session.id,
                exercise_id=item["exercise_id"],
                status="completed",
                duration_seconds=None,
                notes="Completion proven by v24 done=true and final stepIndex; duration unknown.",
            ))
            created_records += 1
        db.add(WorkoutLog(
            plan_id=plan.id,
            session_id=session.id,
            log_date=day,
            action="completed",
            status="completed",
            notes="Imported from v24 done=true; historical timestamps and duration unknown.",
        ))
        created_sessions += 1
        created_logs += 1

    log = MigrationLog(
        migration_name=MIGRATION_NAME,
        source_sha256=preview["source_sha256"],
        preview_hash=preview["preview_hash"],
        affected_fingerprint=preview["affected_fingerprint"],
        status="committed",
        details=json.dumps({
            "created_plans": created_plans,
            "created_items": created_items,
            "created_sessions": created_sessions,
            "created_records": created_records,
            "created_logs": created_logs,
            "duration_unknown_sessions": created_sessions,
            "updatedAt_preserved_as_source_metadata": True,
            "historical_times_saved_as_null": True,
        }, ensure_ascii=False, sort_keys=True),
    )
    db.add(log)
    db.flush()
    return {
        "status": "committed",
        "migration_log_id": log.id,
        "created_plans": created_plans,
        "created_items": created_items,
        "created_sessions": created_sessions,
        "created_records": created_records,
        "created_logs": created_logs,
        "preview": preview,
    }
