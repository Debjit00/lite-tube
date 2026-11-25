"""Authentication endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_register_login_logout_flow(client: TestClient) -> None:
    # Initially browsing as guest
    assert client.get("/api/auth/me").json() == {"user": None}

    # Register new account
    reg = client.post(
        "/api/auth/register",
        json={
            "username": "Alice_Dev",
            "display_name": "Alice Channel",
            "password": "password123",
        },
    )
    assert reg.status_code == 201
    user = reg.json()["user"]
    assert user["username"] == "Alice_Dev"
    assert user["display_name"] == "Alice Channel"

    # Session cookie persists across /api/auth/me
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["id"] == user["id"]

    # Case-insensitive duplicate username rejected
    dup = client.post(
        "/api/auth/register",
        json={"username": "alice_dev", "password": "password123"},
    )
    assert dup.status_code == 409

    # Logout clears cookie
    out = client.post("/api/auth/logout")
    assert out.status_code == 200
    assert client.get("/api/auth/me").json() == {"user": None}

    # Wrong password rejected
    bad_login = client.post(
        "/api/auth/login",
        json={"username": "alice_dev", "password": "wrongpassword"},
    )
    assert bad_login.status_code == 401

    # Valid login restores session
    ok_login = client.post(
        "/api/auth/login",
        json={"username": "alice_dev", "password": "password123"},
    )
    assert ok_login.status_code == 200
    assert client.get("/api/auth/me").json()["user"]["username"] == "Alice_Dev"


def test_register_validation_errors(client: TestClient) -> None:
    bad_user = client.post(
        "/api/auth/register",
        json={"username": "x!", "password": "password123"},
    )
    assert bad_user.status_code == 400

    bad_pw = client.post(
        "/api/auth/register",
        json={"username": "validuser", "password": "123"},
    )
    assert bad_pw.status_code == 400
