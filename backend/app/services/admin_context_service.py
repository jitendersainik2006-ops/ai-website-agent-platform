from flask import current_app

from app.services.common import object_id, serialize


def get_context(identity: dict) -> dict:
    db = current_app.extensions["mongo_db"]
    membership = db.memberships.find_one(
        {
            "tenant_id": object_id(identity["tenant"]["id"]),
            "user_id": object_id(identity["user"]["id"]),
            "role": identity["role"],
            "status": "active",
        }
    )
    return {**identity, "membership_status": membership["status"] if membership else "inactive"}


def public_identity(identity: dict) -> dict:
    return serialize(get_context(identity))
