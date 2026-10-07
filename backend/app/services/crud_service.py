from flask import current_app

from app.services.common import now, object_id, serialize

_PROTECTED_FIELDS = {"_id", "tenant_id", "created_at", "updated_at", "password_hash"}


def _safe_data(data: dict) -> dict:
    return {key: value for key, value in data.items() if key not in _PROTECTED_FIELDS}


def list_records(collection: str, tenant_id: str, query: dict | None = None) -> list:
    filter_query = {"tenant_id": object_id(tenant_id), **(query or {})}
    return [serialize(item) for item in current_app.extensions["mongo_db"][collection].find(filter_query).sort("updated_at", -1)]


def get_record(collection: str, tenant_id: str, record_id: str) -> dict | None:
    record_oid = object_id(record_id)
    if not record_oid:
        return None
    record = current_app.extensions["mongo_db"][collection].find_one(
        {"_id": record_oid, "tenant_id": object_id(tenant_id)}
    )
    return serialize(record) if record else None


def create_record(collection: str, tenant_id: str, data: dict) -> dict:
    timestamp = now()
    record = {**_safe_data(data), "tenant_id": object_id(tenant_id), "created_at": timestamp, "updated_at": timestamp}
    result = current_app.extensions["mongo_db"][collection].insert_one(record)
    record["_id"] = result.inserted_id
    return serialize(record)


def update_record(collection: str, tenant_id: str, record_id: str, data: dict) -> dict | None:
    record_oid = object_id(record_id)
    if not record_oid:
        return None
    db = current_app.extensions["mongo_db"]
    record = db[collection].find_one_and_update(
        {"_id": record_oid, "tenant_id": object_id(tenant_id)},
        {"$set": {**_safe_data(data), "updated_at": now()}},
        return_document=True,
    )
    return serialize(record) if record else None


def delete_record(collection: str, tenant_id: str, record_id: str) -> bool:
    record_oid = object_id(record_id)
    if not record_oid:
        return False
    return bool(
        current_app.extensions["mongo_db"][collection].delete_one(
            {"_id": record_oid, "tenant_id": object_id(tenant_id)}
        ).deleted_count
    )
