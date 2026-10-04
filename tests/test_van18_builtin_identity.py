"""VAN-18 uses catalog identities on real Exercise rows, with atomic failure."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

APP_DIR = Path(__file__).resolve().parents[1]


def catalog(client):
    preview = client.post('/api/migrations/catalog/v24/preview').json()
    assert client.post('/api/migrations/catalog/v24/commit', json=preview).status_code == 200
    return {ex['catalog_key']: ex for ex in client.get('/api/exercises').json()['exercises'] if ex['catalog_key']}


def test_catalog_rename_keeps_identity_and_reconcile_does_not_duplicate(client, app_modules):
    rows = catalog(client)
    ex = rows['posterior-pelvic-tilt']
    payload = {**ex, 'name': '改名后的骨盆动作'}
    assert client.put(f"/api/exercises/{ex['id']}", json=payload).status_code == 200
    assert client.get(f"/api/exercises/{ex['id']}").json()['catalog_key'] == 'posterior-pelvic-tilt'
    preview = client.post('/api/migrations/catalog/v24/preview').json()
    assert preview['create_count'] == 0
    assert client.post('/api/migrations/catalog/v24/commit', json=preview).status_code == 200
    database, _ = app_modules
    database.migrate_database()
    assert client.get(f"/api/exercises/{ex['id']}").json()['catalog_key'] == 'posterior-pelvic-tilt'
    assert len(client.get('/api/exercises').json()['exercises']) == 15


@pytest.mark.parametrize('route', ['generate', 'by-date'])
def test_complete_identity_snapshot_api_sqlite_reload_and_start(client, app_modules, route):
    rows = catalog(client)
    ids = [rows[key]['id'] for key in ['posterior-pelvic-tilt', 'cat-cow', 'dead-bug', 'bird-dog']]
    date = '2026-12-18'
    if route == 'generate':
        response = client.post('/api/plans/generate', json={'date': date, 'exerciseIds': ids})
    else:
        response = client.put(f'/api/plans/by-date/{date}', json={'date': date, 'items': [{'exercise_id': eid, 'name': '展示文案已改变', 'sets': 3, 'reps': 8} for eid in ids]})
    assert response.status_code == 200, response.text
    plan = response.json()['plan']
    assert [item['exercise_id'] for item in plan['items']] == ids
    assert len(plan['items']) == 4
    # A new read is the authoritative source after page refresh.
    reloaded = client.get('/api/plans/month?month=2026-12').json()
    day = next(day for day in reloaded['days'] if day['date'] == date)
    assert [item['exercise_id'] for item in day['items']] == ids
    database, _ = app_modules
    with database.SessionLocal() as db:
        stored = db.execute(text('SELECT exercise_id FROM workout_exercises WHERE plan_id=:p ORDER BY sort_order'), {'p': plan['id']}).scalars().all()
    assert stored == ids
    started = client.post('/api/session/start', json={'plan_id': plan['id']})
    assert started.status_code == 200, started.text
    assert [item['exercise_id'] for item in started.json()['session']['records']] == ids


@pytest.mark.parametrize('route', ['generate', 'by-date'])
def test_missing_id_rejects_entire_request_preserving_existing_plan(client, route):
    rows = catalog(client)
    ids = [rows[k]['id'] for k in ['cat-cow', 'glute-bridge', 'wall-sit']]
    date = '2026-12-19'
    original = client.post('/api/plans/generate', json={'date': date, 'exerciseIds': ids}).json()['plan']
    bad = ids[:1] + [999999] + ids[1:]
    if route == 'generate':
        response = client.post('/api/plans/generate', json={'date': date, 'exerciseIds': bad})
    else:
        response = client.put(f'/api/plans/by-date/{date}', json={'date': date, 'items': [{'exercise_id': eid} for eid in bad]})
    assert response.status_code == 404
    assert '动作不存在' in response.json()['detail']
    day = next(x for x in client.get('/api/plans/month?month=2026-12').json()['days'] if x['date'] == date)
    assert day['id'] == original['id']
    assert [item['exercise_id'] for item in day['items']] == ids


def test_legacy_identity_adoption_is_unique_once_and_preserves_primary_ids(client, app_modules):
    database, _ = app_modules
    with database.SessionLocal() as db:
        db.query(database.Setting).filter_by(key='van18_catalog_identity_v1').delete()
        a = database.Exercise(name='猫牛式', category='核心')
        b = database.Exercise(name='臀桥', category='下肢')
        c = database.Exercise(name='臀桥', category='下肢')
        db.add_all([a, b, c]); db.commit(); aid = a.id
    database.migrate_database()
    with database.SessionLocal() as db:
        assert db.get(database.Exercise, aid).catalog_key == 'cat-cow'
        assert all(x.catalog_key is None for x in db.query(database.Exercise).filter_by(name='臀桥'))
        db.delete(db.get(database.Exercise, aid)); db.commit()
        replacement = database.Exercise(name='猫牛式', category='核心')
        db.add(replacement); db.commit(); rid = replacement.id
    database.migrate_database()
    with database.SessionLocal() as db:
        assert db.get(database.Exercise, rid).catalog_key is None


def test_real_inline_page_builtin_start_schedule_replace_refresh(client):
    rows = catalog(client)
    env = {**os.environ, 'VAN18_CATALOG': json.dumps(list(rows.values()), ensure_ascii=False)}
    result = subprocess.run(['node', 'tests/van18_inline_behavior.js'], cwd=APP_DIR, env=env, text=True, capture_output=True, timeout=40)
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"PASS":true' in result.stdout


def test_old_schema_adds_unique_catalog_key_without_changing_existing_id(tmp_path):
    """Upgrade an actual pre-VAN-18 exercises table, then restart twice."""
    import sqlite3
    import sys
    db_path = tmp_path / 'legacy.sqlite'
    with sqlite3.connect(db_path) as db:
        db.executescript('''
        CREATE TABLE exercises (
            id INTEGER PRIMARY KEY, name VARCHAR(140) NOT NULL,
            category VARCHAR(80) NOT NULL, body_parts VARCHAR(240) NOT NULL,
            difficulty VARCHAR(20) NOT NULL, default_sets INTEGER NOT NULL,
            default_reps VARCHAR(20), duration_seconds INTEGER, notes TEXT,
            benefit TEXT, tips TEXT, video_url VARCHAR(500),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME
        );
        INSERT INTO exercises(id,name,category,body_parts,difficulty,default_sets)
        VALUES(77,'仰卧骨盆后倾','核心','核心','低',1);
        ''')
    code = '''
import database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
database.create_tables()
database.migrate_database()
with database.SessionLocal() as db:
    ex = db.get(database.Exercise, 77)
    assert ex.catalog_key == 'posterior-pelvic-tilt'
    ex.name = '已改名的旧目录动作'
    db.commit()
    duplicate = database.Exercise(name='另一个动作', catalog_key=ex.catalog_key)
    db.add(duplicate)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        raise AssertionError('catalog_key must be unique')
database.migrate_database()
with database.SessionLocal() as db:
    assert db.get(database.Exercise, 77).catalog_key == 'posterior-pelvic-tilt'
    assert db.get(database.Exercise, 77).name == '已改名的旧目录动作'
    assert db.query(database.Exercise).count() == 1
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=APP_DIR, env={**os.environ, 'WORKOUT_DB_PATH': str(db_path)}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr + result.stdout
