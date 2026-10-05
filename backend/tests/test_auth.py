from datetime import datetime, timedelta, timezone

import jwt
import mongomock
import pytest

from app import create_app
from app.security.passwords import hash_password


@pytest.fixture()
def client():
    mongo_client = mongomock.MongoClient()
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret-with-at-least-32-bytes",
            "MONGODB_DATABASE": "auth_tests",
        },
        mongo_client=mongo_client,
    )
    db = app.extensions["mongo_db"]
    tenant_id = db.tenants.insert_one(
        {"name": "Tenant A", "slug": "tenant-a", "status": "active"}
    ).inserted_id
    user_id = db.users.insert_one(
        {
            "name": "Admin A",
            "email": "admin@example.com",
            "password_hash": hash_password("CorrectPass123!"),
            "status": "active",
        }
    ).inserted_id
    db.memberships.insert_one(
        {"tenant_id": tenant_id, "user_id": user_id, "role": "owner", "status": "active"}
    )
    return app.test_client()


def test_login_and_me(client):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "CorrectPass123!",
            "tenant_slug": "tenant-a",
        },
    )
    assert response.status_code == 200
    token = response.get_json()["access_token"]

    me_response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.get_json()["tenant"]["slug"] == "tenant-a"
    assert me_response.get_json()["role"] == "owner"


def test_login_rejects_invalid_credentials(client):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "WrongPass123!",
            "tenant_slug": "tenant-a",
        },
    )
    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid_credentials"


def test_me_rejects_missing_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    ("collection", "query"),
    [
        ("users", {"email": "admin@example.com"}),
        ("tenants", {"slug": "tenant-a"}),
        ("memberships", {"role": "owner"}),
    ],
)
def test_me_rejects_inactive_authentication_records(client, collection, query):
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "CorrectPass123!",
            "tenant_slug": "tenant-a",
        },
    )
    token = login_response.get_json()["access_token"]
    client.application.extensions["mongo_db"][collection].update_one(
        query, {"$set": {"status": "inactive"}}
    )

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_me_rejects_expired_token(client):
    db = client.application.extensions["mongo_db"]
    user = db.users.find_one({"email": "admin@example.com"})
    tenant = db.tenants.find_one({"slug": "tenant-a"})
    token = jwt.encode(
        {
            "sub": str(user["_id"]),
            "tenant_id": str(tenant["_id"]),
            "role": "owner",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        client.application.config["JWT_SECRET_KEY"],
        algorithm="HS256",
    )

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
