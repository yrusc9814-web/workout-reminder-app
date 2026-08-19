def test_favorites_list_create_duplicate_and_delete(client):
    initial = client.get("/api/favorites")
    assert initial.status_code == 200
    assert initial.json() == {"favorites": []}

    created = client.post(
        "/api/favorites",
        json={"exercise_name": "仰卧骨盆时钟"},
    )
    assert created.status_code == 200
    assert created.json()["status"] == "created"
    assert created.json()["favorite"]["exercise_name"] == "仰卧骨盆时钟"

    duplicate = client.post(
        "/api/favorites",
        json={"exerciseName": "仰卧骨盆时钟"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "already_exists"

    listed = client.get("/api/favorites")
    assert [row["exercise_name"] for row in listed.json()["favorites"]] == ["仰卧骨盆时钟"]

    deleted = client.delete("/api/favorites/%E4%BB%B0%E5%8D%A7%E9%AA%A8%E7%9B%86%E6%97%B6%E9%92%9F")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "exercise_name": "仰卧骨盆时钟"}
    assert client.get("/api/favorites").json() == {"favorites": []}


def test_favorites_reject_blank_and_missing_delete(client):
    assert client.post("/api/favorites", json={"exercise_name": "  "}).status_code == 422
    assert client.delete("/api/favorites/%E4%B8%8D%E5%AD%98%E5%9C%A8").status_code == 404
