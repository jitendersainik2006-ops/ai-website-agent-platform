from datetime import datetime, timezone

from bson import ObjectId
from flask import current_app, g


def now() -> datetime:
    return datetime.now(timezone.utc)


def object_id(value: str) -> ObjectId | None:
    return ObjectId(value) if isinstance(value, str) and ObjectId.is_valid(value) else None


def serialize(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items() if key != "password_hash" and not key.endswith("_token_hash")}
    return value


def audit(tenant_id, action: str, entity_type: str, entity_id=None, metadata=None) -> None:
    actor = getattr(g, "auth", None)
    current_app.extensions["mongo_db"].audit_logs.insert_one(
        {
            "tenant_id": tenant_id,
            "actor_id": actor["user"]["id"] if actor else None,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "metadata": metadata or {},
            "created_at": now(),
        }
    )
