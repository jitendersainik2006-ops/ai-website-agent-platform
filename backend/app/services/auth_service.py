from bson import ObjectId
from flask import current_app

from app.security.passwords import verify_password
from app.security.tokens import create_access_token, decode_access_token


def _is_valid_id(value: str) -> bool:
    return ObjectId.is_valid(value)


def login(email: str, password: str, tenant_slug: str) -> dict | None:
    db = current_app.extensions["mongo_db"]
    tenant = db.tenants.find_one({"slug": tenant_slug, "status": "active"})
    user = db.users.find_one({"email": email.lower(), "status": "active"})

    if not tenant or not user or not verify_password(password, user["password_hash"]):
        return None

    membership = db.memberships.find_one(
        {
            "tenant_id": tenant["_id"],
            "user_id": user["_id"],
            "status": "active",
        }
    )
    if not membership:
        return None

    return {
        "access_token": create_access_token(
            user_id=str(user["_id"]),
            tenant_id=str(tenant["_id"]),
            role=membership["role"],
        ),
        "token_type": "Bearer",
        "user": _public_user(user),
        "tenant": _public_tenant(tenant),
        "role": membership["role"],
    }


def get_authenticated_identity(token: str) -> dict | None:
    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    role = payload.get("role")
    if not all(isinstance(value, str) and value for value in (user_id, tenant_id, role)):
        return None
    if not _is_valid_id(user_id) or not _is_valid_id(tenant_id):
        return None

    db = current_app.extensions["mongo_db"]
    user = db.users.find_one({"_id": ObjectId(user_id), "status": "active"})
    tenant = db.tenants.find_one({"_id": ObjectId(tenant_id), "status": "active"})
    if not user or not tenant:
        return None

    membership = db.memberships.find_one(
        {
            "tenant_id": tenant["_id"],
            "user_id": user["_id"],
            "role": role,
            "status": "active",
        }
    )
    if not membership:
        return None

    return {"user": _public_user(user), "tenant": _public_tenant(tenant), "role": role}


def _public_user(user: dict) -> dict:
    return {"id": str(user["_id"]), "email": user["email"], "name": user["name"]}


def _public_tenant(tenant: dict) -> dict:
    return {"id": str(tenant["_id"]), "name": tenant["name"], "slug": tenant["slug"]}
