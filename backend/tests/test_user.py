"""Authenticated user features: favourites and saved predictions."""
from __future__ import annotations

from backend.tests.helpers import auth_headers, register


def _token(client, email: str) -> dict[str, str]:
    return auth_headers(register(client, email)["access_token"])


def test_favourite_teams_require_auth(client):
    assert client.get("/api/favorites/teams").status_code == 401
    assert client.post("/api/favorites/teams/101").status_code == 401


def test_favourite_team_lifecycle(client):
    headers = _token(client, "fav-teams@example.com")

    added = client.post("/api/favorites/teams/101", headers=headers)
    assert added.status_code == 201
    assert added.json()["team"]["id"] == 101

    duplicate = client.post("/api/favorites/teams/101", headers=headers)
    assert duplicate.status_code == 201
    assert duplicate.json()["already"] is True

    listed = client.get("/api/favorites/teams", headers=headers).json()["items"]
    assert [team["id"] for team in listed] == [101]

    removed = client.delete("/api/favorites/teams/101", headers=headers)
    assert removed.status_code == 200
    assert client.get("/api/favorites/teams", headers=headers).json()["items"] == []

    missing = client.post("/api/favorites/teams/999999", headers=headers)
    assert missing.status_code == 404


def test_favourite_fixture_lifecycle(client, scheduled_fixture_id):
    headers = _token(client, "fav-fixtures@example.com")

    added = client.post(f"/api/favorites/fixtures/{scheduled_fixture_id}", headers=headers)
    assert added.status_code == 201
    assert added.json()["fixture"]["id"] == scheduled_fixture_id

    listed = client.get("/api/favorites/fixtures", headers=headers).json()["items"]
    assert [fixture["id"] for fixture in listed] == [scheduled_fixture_id]

    removed = client.delete(f"/api/favorites/fixtures/{scheduled_fixture_id}", headers=headers)
    assert removed.status_code == 200
    assert client.get("/api/favorites/fixtures", headers=headers).json()["items"] == []


def test_saved_prediction_lifecycle(client, scheduled_fixture_id):
    headers = _token(client, "saved-lifecycle@example.com")

    created = client.post(
        "/api/predictions/saved",
        json={"fixture_id": scheduled_fixture_id, "window": 10, "note": "Back the home side"},
        headers=headers,
    )
    assert created.status_code == 201
    item = created.json()["item"]
    saved_id = item["id"]
    assert item["fixture_id"] == scheduled_fixture_id
    assert item["note"] == "Back the home side"
    assert item["model_version"] == "poisson-dc"
    assert set(item["prediction"]["probabilities"]) == {"home", "draw", "away"}
    assert item["settlement"] is None

    listing = client.get("/api/predictions/saved", headers=headers).json()
    assert listing["total"] == 1

    detail = client.get(f"/api/predictions/saved/{saved_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == saved_id

    refreshed = client.post(f"/api/predictions/saved/{saved_id}/refresh", headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["item"]["id"] == saved_id

    summary = client.get("/api/predictions/summary", headers=headers).json()
    assert summary["saved"] == 1
    assert summary["generated"] >= 2
    assert summary["settled"] == 0

    deleted = client.delete(f"/api/predictions/saved/{saved_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/predictions/saved", headers=headers).json()["total"] == 0


def test_saved_prediction_settles_against_final_score(client, finished_fixture_id):
    headers = _token(client, "saved-settlement@example.com")
    created = client.post(
        "/api/predictions/saved",
        json={"fixture_id": finished_fixture_id, "window": 5},
        headers=headers,
    )
    assert created.status_code == 201
    settlement = created.json()["item"]["settlement"]
    assert settlement is not None
    assert settlement["actual"] in {"home", "draw", "away"}
    assert settlement["actual_label"]
    assert isinstance(settlement["hit"], bool)
    assert settlement["scoreline"]

    summary = client.get("/api/predictions/summary", headers=headers).json()
    assert summary["settled"] == 1
    assert summary["accuracy"] in {0.0, 1.0}


def test_saved_predictions_are_private(client, scheduled_fixture_id):
    owner = _token(client, "owner@example.com")
    other = _token(client, "intruder@example.com")

    created = client.post(
        "/api/predictions/saved",
        json={"fixture_id": scheduled_fixture_id, "window": 10},
        headers=owner,
    )
    assert created.status_code == 201
    saved_id = created.json()["item"]["id"]

    assert client.get(f"/api/predictions/saved/{saved_id}", headers=other).status_code == 404
    assert client.delete(f"/api/predictions/saved/{saved_id}", headers=other).status_code == 404
    assert client.get("/api/predictions/saved", headers=other).json()["total"] == 0


def test_authenticated_analysis_is_recorded(client, scheduled_fixture_id):
    headers = _token(client, "analysis-history@example.com")

    before = client.get("/api/predictions/history", headers=headers).json()["total"]
    response = client.get(f"/api/analysis/{scheduled_fixture_id}", headers=headers)
    assert response.status_code == 200

    history = client.get("/api/predictions/history", headers=headers).json()
    assert history["total"] == before + 1
    latest = history["items"][0]
    assert latest["fixture_id"] == scheduled_fixture_id
    assert latest["probabilities"]
    assert latest["most_likely"]["outcome"] in {"home", "draw", "away"}


def test_history_requires_auth(client):
    assert client.get("/api/predictions/history").status_code == 401
    assert client.get("/api/predictions/summary").status_code == 401
