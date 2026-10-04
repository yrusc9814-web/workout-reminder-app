from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from database import Exercise, MigrationLog

CATALOG_MIGRATION_NAME = "v24-built-in-catalog-v1"

# Extracted from the frozen v24 exerciseDetails object. The frozen source has
# names and instructional facts, but not backend IDs; IDs are assigned by
# SQLite. catalog_key is the persistent identity on these same Exercise rows;
# names are used only to adopt uniquely matching legacy rows.
V24_BUILTIN_CATALOG = (
    {"catalog_key": "glute-bridge", "name": "臀桥", "category": "下肢", "body_parts": "臀部,核心", "difficulty": "低", "default_sets": 1, "default_reps": None, "duration_seconds": 240, "notes": "激活臀大肌与核心，改善久坐导致的臀肌失忆，缓解下背压力。", "benefit": "臀部发力将髋向上推至肩-髋-膝成直线。", "tips": "避免过度挺腰。"},
    {"catalog_key": "dead-bug", "name": "死虫式", "category": "核心", "body_parts": "核心", "difficulty": "低", "default_sets": 1, "default_reps": None, "duration_seconds": 300, "notes": "强化深层腹肌与核心稳定性，改善腰背疼痛。", "benefit": "对侧手脚同时缓慢下放，保持腰部贴地。", "tips": "腰部必须始终贴地。"},
    {"catalog_key": "bird-dog", "name": "Bird Dog", "category": "核心", "body_parts": "核心,背部", "difficulty": "低", "default_sets": 1, "default_reps": "8次/侧", "duration_seconds": 240, "notes": "提升核心稳定性与脊柱抗旋转能力。", "benefit": "抬对侧手臂和腿至水平，保持骨盆稳定。", "tips": "动作速度要慢，避免身体晃动。"},
    {"catalog_key": "posterior-pelvic-tilt", "name": "仰卧骨盆后倾", "category": "核心", "body_parts": "核心,骨盆", "difficulty": "低", "default_sets": 1, "default_reps": None, "duration_seconds": 300, "notes": "学习骨盆控制，改善骨盆前倾体态。", "benefit": "用腹部力量将腰部轻轻压向地面。", "tips": "不要用臀部发力猛推。"},
    {"catalog_key": "push-up", "name": "俯卧撑", "category": "上肢", "body_parts": "胸部,肩部,手臂", "difficulty": "中", "default_sets": 3, "default_reps": "8次", "duration_seconds": None, "notes": "强化胸大肌、三角肌前束和肱三头肌。", "benefit": "身体保持一直线，屈肘下降后推回。", "tips": "肘部与身体保持约45度。"},
    {"catalog_key": "wall-sit", "name": "靠墙静蹲", "category": "下肢", "body_parts": "腿部,臀部", "difficulty": "低", "default_sets": 1, "default_reps": None, "duration_seconds": 240, "notes": "安全强化股四头肌与臀部，不增加膝关节冲击。", "benefit": "背靠墙缓慢下滑并保持。", "tips": "膝盖不要超过脚尖。"},
    {"catalog_key": "cat-cow", "name": "猫牛式", "category": "核心", "body_parts": "背部,脊柱", "difficulty": "低", "default_sets": 1, "default_reps": None, "duration_seconds": 180, "notes": "温和活动整个脊柱，释放背部紧张。", "benefit": "吸气塌腰抬头，呼气弓背低头。", "tips": "动作幅度以舒适为准。"},
    {"catalog_key": "baduanjin", "name": "八段锦", "category": "养生操", "body_parts": "全身", "difficulty": "低", "default_sets": 1, "default_reps": None, "duration_seconds": 720, "notes": "通过八个舒缓式子调理脏腑、舒展筋骨。", "benefit": "动作柔和缓慢，配合自然呼吸。", "tips": "饭后一小时内不练。"},
    {"catalog_key": "tai-chi-24", "name": "太极拳 24 式", "category": "养生操", "body_parts": "全身", "difficulty": "低", "default_sets": 1, "default_reps": None, "duration_seconds": 1200, "notes": "通过缓慢动作与深呼吸提升平衡力和柔韧性。", "benefit": "动作连绵不断，重心平稳移动。", "tips": "膝盖不适者注意弓步幅度。"},
    {"catalog_key": "eye-exercises", "name": "眼保健操", "category": "养生操", "body_parts": "眼部", "difficulty": "低", "default_sets": 1, "default_reps": None, "duration_seconds": 300, "notes": "缓解眼部疲劳，适合长期盯屏幕的人群。", "benefit": "按揉攒竹、睛明、四白和太阳穴。", "tips": "手指需洁净，力度适中。"},
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _exercise_fingerprint(db: Session) -> str:
    rows = [
        {
            "id": row.id,
            "catalog_key": row.catalog_key,
            "name": row.name,
            "category": row.category,
            "body_parts": row.body_parts,
            "difficulty": row.difficulty,
            "default_sets": row.default_sets,
            "default_reps": row.default_reps,
            "duration_seconds": row.duration_seconds,
            "notes": row.notes,
            "benefit": row.benefit,
            "tips": row.tips,
            "video_url": row.video_url,
        }
        for row in db.query(Exercise).order_by(Exercise.id.asc()).all()
    ]
    return _sha(rows)


def build_catalog_preview(db: Session) -> dict:
    by_name: dict[str, list[Exercise]] = {}
    rows = db.query(Exercise).order_by(Exercise.id.asc()).all()
    by_key = {row.catalog_key: row for row in rows if row.catalog_key}
    for row in rows:
        by_name.setdefault(row.name, []).append(row)
    blockers = []
    existing = []
    create = []
    for item in V24_BUILTIN_CATALOG:
        keyed = [by_key[item["catalog_key"]]] if item["catalog_key"] in by_key else []
        matches = keyed or by_name.get(item["name"], [])
        if len(matches) > 1:
            blockers.append({"code": "ambiguous_catalog_name", "name": item["name"], "count": len(matches)})
        elif matches and matches[0].catalog_key not in (None, item["catalog_key"]):
            blockers.append({"code": "catalog_identity_conflict", "name": item["name"]})
        elif matches:
            existing.append({"name": item["name"], "exercise_id": matches[0].id, "action": "keep_existing"})
        else:
            create.append(dict(item))
    fingerprint = _exercise_fingerprint(db)
    body = {
        "migration": CATALOG_MIGRATION_NAME,
        "source_sha256": _sha(V24_BUILTIN_CATALOG),
        "affected_fingerprint": fingerprint,
        "existing": existing,
        "create": create,
        "blockers": blockers,
    }
    return {
        "status": "blocked" if blockers else "ready",
        "source_sha256": body["source_sha256"],
        "affected_fingerprint": fingerprint,
        "preview_hash": _sha(body),
        "source_count": len(V24_BUILTIN_CATALOG),
        "existing_count": len(existing),
        "create_count": len(create),
        "existing": existing,
        "create": create,
        "blockers": blockers,
    }


def reconcile_catalog(db: Session, payload: dict | None = None) -> dict:
    payload = payload or {}
    expected_preview = payload.get("preview_hash")
    expected_source = payload.get("source_sha256")
    expected_fingerprint = payload.get("affected_fingerprint")
    source_hash = _sha(V24_BUILTIN_CATALOG)
    if expected_preview:
        replay = db.query(MigrationLog).filter(
            MigrationLog.migration_name == CATALOG_MIGRATION_NAME,
            MigrationLog.source_sha256 == source_hash,
            MigrationLog.preview_hash == expected_preview,
            MigrationLog.status == "committed",
        ).order_by(MigrationLog.id.desc()).first()
        if replay:
            return {"status": "already_committed", "migration_log_id": replay.id}
    preview = build_catalog_preview(db)
    for label, expected, actual in (
        ("source_sha256", expected_source, preview["source_sha256"]),
        ("preview_hash", expected_preview, preview["preview_hash"]),
        ("affected_fingerprint", expected_fingerprint, preview["affected_fingerprint"]),
    ):
        if expected and expected != actual:
            raise ValueError(f"{label} 不匹配，stale_preview")
    if preview["status"] != "ready":
        raise ValueError("catalog preview 存在阻断项")

    for item in V24_BUILTIN_CATALOG:
        rows = db.query(Exercise).filter(Exercise.name == item["name"]).all()
        owner = db.query(Exercise).filter(Exercise.catalog_key == item["catalog_key"]).first()
        if owner is None and len(rows) == 1 and rows[0].catalog_key is None:
            rows[0].catalog_key = item["catalog_key"]
    db.flush()

    created = []
    for item in preview["create"]:
        # Recheck by name inside the same transaction; never overwrite an
        # existing row and never manufacture a second copy on replay.
        matches = db.query(Exercise).filter(Exercise.catalog_key == item["catalog_key"]).all() or db.query(Exercise).filter(Exercise.name == item["name"]).all()
        if len(matches) > 1:
            raise ValueError(f"catalog 名称冲突：{item['name']}")
        if matches:
            if matches[0].catalog_key is None:
                matches[0].catalog_key = item["catalog_key"]
            continue
        row = Exercise(**item)
        db.add(row)
        db.flush()
        created.append({"name": row.name, "exercise_id": row.id})

    log = MigrationLog(
        migration_name=CATALOG_MIGRATION_NAME,
        source_sha256=preview["source_sha256"],
        preview_hash=preview["preview_hash"],
        affected_fingerprint=preview["affected_fingerprint"],
        status="committed",
        details=json.dumps({"created": created, "source_count": len(V24_BUILTIN_CATALOG)}, ensure_ascii=False, sort_keys=True),
    )
    db.add(log)
    db.flush()
    return {"status": "committed", "migration_log_id": log.id, "created": created, "preview": preview}


if __name__ == "__main__":
    import database

    database.init_db()
    db = database.SessionLocal()
    try:
        result = reconcile_catalog(db)
        db.commit()
        print(json.dumps(result, ensure_ascii=False, default=str))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
