from v25_catalog import V24_BUILTIN_CATALOG


def test_v24_catalog_preview_is_deterministic_and_commit_is_idempotent(client, app_modules):
    database, _main = app_modules
    db = database.SessionLocal()
    try:
        existing = database.Exercise(
            name=V24_BUILTIN_CATALOG[0]["name"],
            category="用户自定义分类",
            body_parts="自定义",
            difficulty="中",
            default_sets=9,
            notes="用户已经编辑的内容",
        )
        db.add(existing)
        db.commit()
        existing_id = existing.id
    finally:
        db.close()

    before_count = db_count(database, database.Exercise)
    preview_response = client.post("/api/migration/catalog/v24/preview")
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["status"] == "ready"
    assert preview["source_count"] == len(V24_BUILTIN_CATALOG)
    assert preview["existing_count"] == 1
    assert preview["create_count"] == len(V24_BUILTIN_CATALOG) - 1
    assert db_count(database, database.Exercise) == before_count

    payload = {
        "source_sha256": preview["source_sha256"],
        "preview_hash": preview["preview_hash"],
        "affected_fingerprint": preview["affected_fingerprint"],
    }
    committed = client.post("/api/migration/catalog/v24/commit", json=payload)
    assert committed.status_code == 200, committed.text
    body = committed.json()
    assert body["status"] == "committed"
    assert len(body["created"]) == len(V24_BUILTIN_CATALOG) - 1

    db = database.SessionLocal()
    try:
        assert db.query(database.Exercise).filter(database.Exercise.name == V24_BUILTIN_CATALOG[0]["name"]).one().id == existing_id
        assert db.query(database.Exercise).filter(database.Exercise.name == V24_BUILTIN_CATALOG[0]["name"]).one().notes == "用户已经编辑的内容"
        for item in V24_BUILTIN_CATALOG:
            assert db.query(database.Exercise).filter(database.Exercise.name == item["name"]).count() == 1
    finally:
        db.close()

    replay = client.post("/api/migration/catalog/v24/commit", json=payload)
    assert replay.status_code == 200
    assert replay.json()["status"] == "already_committed"
    assert db_count(database, database.Exercise) == before_count + len(V24_BUILTIN_CATALOG) - 1


def test_v24_catalog_duplicate_name_is_blocked(client, app_modules):
    database, _main = app_modules
    db = database.SessionLocal()
    try:
        item = V24_BUILTIN_CATALOG[0]
        db.add_all([
            database.Exercise(name=item["name"], category="a", body_parts="a", difficulty="低", default_sets=1),
            database.Exercise(name=item["name"], category="b", body_parts="b", difficulty="低", default_sets=1),
        ])
        db.commit()
    finally:
        db.close()
    response = client.post("/api/migration/catalog/v24/preview")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["blockers"][0]["code"] == "ambiguous_catalog_name"


def db_count(database, model):
    db = database.SessionLocal()
    try:
        return db.query(model).count()
    finally:
        db.close()
