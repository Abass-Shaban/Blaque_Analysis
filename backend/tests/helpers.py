"""Small helpers shared by the test modules."""
from __future__ import annotations

from fastapi.testclient import TestClient

DEFAULT_PASSWORD = "Str0ngPass1"


def register(
    client: TestClient,
    email: str,
    password: str = DEFAULT_PASSWORD,
    name: str = "Test Analyst",
) -> dict:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "full_name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
