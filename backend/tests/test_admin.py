"""Administrator routes and permission boundaries."""
from __future__ import annotations

import pytest

from backend.tests.helpers import auth_headers, register


@pytest.fixture(autouse=True)
def _isolated(clean_users):
    yield


def _admin(client, email: str = "admin@example.com"):
    payload = register(client, email, name="Administrator")
    assert payload["user"]["role"] == "admin"
    return payload["user"], auth_headers(payload["access_token"])


def test_admin_routes_require_admin_role(client):
    _admin(client, "root@example.com")
    regular = register(client, "regular@example.com", name="Regular User")
    assert regular["user"]["role"] == "user"
    headers = auth_headers(regular["access_token"])

    for path in (
        "/api/admin/stats",
        "/api/admin/users",
        "/api/admin/settings",
        "/api/admin/sync-runs",
        "/api/admin/audit",
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 403, path

    assert client.get("/api/admin/stats").status_code == 401


def test_admin_stats(client):
    _, headers = _admin(client)
    response = client.get("/api/admin/stats", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["users"]["total"] == 1
    assert body["users"]["admins"] == 1
    assert body["data"]["teams"] == 4
    assert body["data"]["fixtures"] >= 37
    assert body["model"]["available"] is False
    assert "cache" in body


def test_admin_cannot_demote_or_disable_self(client):
    user, headers = _admin(client)

    demote = client.patch(
        f"/api/admin/users/{user['id']}", json={"role": "user"}, headers=headers
    )
    assert demote.status_code == 409

    deactivate = client.patch(
        f"/api/admin/users/{user['id']}", json={"is_active": False}, headers=headers
    )
    assert deactivate.status_code == 409

    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "admin"
    assert me.json()["is_active"] is True


def test_admin_manages_other_users(client):
    _, headers = _admin(client, "manager@example.com")
    member = register(client, "member@example.com", name="Member User")
    member_headers = auth_headers(member["access_token"])

    search = client.get("/api/admin/users", params={"q": "member"}, headers=headers)
    assert search.status_code == 200
    assert search.json()["total"] == 1

    promoted = client.patch(
        f"/api/admin/users/{member['user']['id']}", json={"role": "admin"}, headers=headers
    )
    assert promoted.status_code == 200
    assert promoted.json()["user"]["role"] == "admin"

    disabled = client.patch(
        f"/api/admin/users/{member['user']['id']}", json={"is_active": False}, headers=headers
    )
    assert disabled.status_code == 200
    assert disabled.json()["user"]["is_active"] is False

    blocked = client.get("/api/auth/me", headers=member_headers)
    assert blocked.status_code == 403

    missing = client.patch("/api/admin/users/999999", json={"role": "user"}, headers=headers)
    assert missing.status_code == 404


def test_admin_updates_runtime_settings(client):
    _, headers = _admin(client, "settings@example.com")

    updated = client.put(
        "/api/admin/settings",
        json={"model_blend_weight": 0.2, "cache_ttl_live": 60},
        headers=headers,
    )
    assert updated.status_code == 200
    runtime = updated.json()["runtime"]
    assert runtime["model_blend_weight"] == 0.2
    assert runtime["cache_ttl_live"] == 60

    settings = client.get("/api/admin/settings", headers=headers)
    assert settings.status_code == 200
    body = settings.json()
    assert body["runtime"]["model_blend_weight"] == 0.2
    assert body["defaults"]["model_blend_weight"] == 0.2
    assert body["leagues"]

    invalid = client.put(
        "/api/admin/settings", json={"model_blend_weight": 0.95}, headers=headers
    )
    assert invalid.status_code == 422


def test_admin_toggles_league_visibility(client):
    _, headers = _admin(client, "leagues@example.com")

    response = client.patch(
        "/api/admin/leagues/esp.1", json={"is_featured": True}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["league"]["slug"] == "esp.1"

    index = client.get("/api/leagues").json()["items"]
    esp = next(item for item in index if item["slug"] == "esp.1")
    assert esp["is_featured"] is True

    missing = client.patch(
        "/api/admin/leagues/nope.1", json={"is_featured": True}, headers=headers
    )
    assert missing.status_code == 404


def test_admin_cache_and_audit(client):
    _, headers = _admin(client, "cache@example.com")

    cleared = client.post("/api/admin/cache/clear", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["ok"] is True
    assert isinstance(cleared.json()["removed"], int)

    audit = client.get("/api/admin/audit", headers=headers)
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()["items"]}
    assert "auth.register" in actions
    assert "admin.cache.clear" in actions


def test_admin_sync_validates_input(client):
    _, headers = _admin(client, "sync@example.com")

    missing_league = client.post(
        "/api/admin/sync",
        json={"scope": "league", "months_back": 0, "months_ahead": 0},
        headers=headers,
    )
    assert missing_league.status_code == 422

    unknown_league = client.post(
        "/api/admin/sync",
        json={"scope": "league", "league": "nope.1", "months_back": 0, "months_ahead": 0},
        headers=headers,
    )
    assert unknown_league.status_code == 404
