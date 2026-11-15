"""Authentication, profile and password flows."""
from __future__ import annotations

from backend.tests.helpers import auth_headers, register

import pytest


@pytest.fixture(autouse=True)
def _isolated(clean_users):
    yield


def test_first_user_becomes_admin(client):
    payload = register(client, "first@example.com", name="First Admin")
    assert payload["user"]["role"] == "admin"
    assert payload["user"]["email"] == "first@example.com"
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["expires_in"] > 0


def test_registration_normalises_email_and_rejects_duplicates(client):
    register(client, "Second@Example.com", name="Second User")
    duplicate = client.post(
        "/api/auth/register",
        json={
            "email": "second@example.com",
            "password": "Str0ngPass1",
            "full_name": "Duplicate User",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"


def test_weak_password_is_rejected(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "weak@example.com", "password": "password", "full_name": "Weak Password"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"


def test_short_name_is_rejected(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "short@example.com", "password": "Str0ngPass1", "full_name": "A"},
    )
    assert response.status_code == 422


def test_login_wrong_password_and_success(client):
    register(client, "login@example.com", password="Str0ngPass1", name="Login User")

    wrong = client.post(
        "/api/auth/login", json={"email": "login@example.com", "password": "WrongPass9"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"

    ok = client.post(
        "/api/auth/login", json={"email": "login@example.com", "password": "Str0ngPass1"}
    )
    assert ok.status_code == 200
    token = ok.json()["access_token"]

    me = client.get("/api/auth/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["email"] == "login@example.com"
    assert me.json()["last_login_at"] is not None


def test_me_requires_authentication(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_profile_update(client):
    token = register(client, "profile@example.com", name="Profile User")["access_token"]
    headers = auth_headers(token)

    updated = client.patch("/api/auth/me", json={"full_name": "  Renamed   Analyst  "}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Renamed Analyst"

    invalid = client.patch("/api/auth/me", json={"full_name": "X"}, headers=headers)
    assert invalid.status_code == 422


def test_change_password(client):
    token = register(client, "rotate@example.com", password="Str0ngPass1")["access_token"]
    headers = auth_headers(token)

    wrong = client.post(
        "/api/auth/change-password",
        json={"current_password": "NotMyPass1", "new_password": "N3wStrongPass"},
        headers=headers,
    )
    assert wrong.status_code == 401

    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": "Str0ngPass1", "new_password": "N3wStrongPass"},
        headers=headers,
    )
    assert changed.status_code == 200
    assert changed.json()["ok"] is True

    old_login = client.post(
        "/api/auth/login", json={"email": "rotate@example.com", "password": "Str0ngPass1"}
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/auth/login", json={"email": "rotate@example.com", "password": "N3wStrongPass"}
    )
    assert new_login.status_code == 200


def test_logout_requires_token(client):
    token = register(client, "logout@example.com")["access_token"]
    response = client.post("/api/auth/logout", headers=auth_headers(token))
    assert response.status_code == 200
    assert response.json()["ok"] is True
