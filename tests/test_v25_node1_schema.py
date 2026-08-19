from pathlib import Path
import sqlite3


def test_v25_schema_tables_and_version_are_committed_after_integrity(app_modules):
    database, _main = app_modules
    db_path = Path(database.DATABASE_PATH)

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"favorites", "migration_logs", "schema_version"} <= tables
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone() == (database.CURRENT_SCHEMA_VERSION,)


def test_v25_favorite_unique_constraint_is_database_enforced(app_modules):
    database, _main = app_modules
    db = database.SessionLocal()
    try:
        db.add(database.Favorite(exercise_name="Node1 测试动作"))
        db.commit()
        db.add(database.Favorite(exercise_name="Node1 测试动作"))
        try:
            db.commit()
        except Exception:
            db.rollback()
        else:
            raise AssertionError("duplicate favorite unexpectedly committed")
    finally:
        db.close()


def test_v25_migration_result_reports_integrity_and_schema_version(app_modules):
    database, _main = app_modules
    result = database.migrate_database()
    assert result["integrity"] == "ok"
    assert result["schema_version"] == database.CURRENT_SCHEMA_VERSION

    db = database.SessionLocal()
    try:
        row = db.query(database.SchemaVersion).filter_by(id=1).one()
        assert row.version == database.CURRENT_SCHEMA_VERSION
    finally:
        db.close()
