from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from flask import current_app

from app.security.passwords import hash_password, verify_password
from app.security.tokens import create_customer_access_token, decode_access_token
from app.services.common import now, serialize


def _tenant_for_widget_key(widget_key: str) -> dict | None:
    if not isinstance(widget_key, str) or not widget_key:
        return None
    db = current_app.extensions["mongo_db"]
    config = db.widget_configs.find_one({"public_key": widget_key, "enabled": {"$ne": False}})
    if not config:
        return None
    return db.tenants.find_one({"_id": config["tenant_id"], "status": "active"})


def _next_customer_id(tenant_id: ObjectId) -> str:
    counter = current_app.extensions["mongo_db"].counters.find_one_and_update(
        {"_id": f"customer_id:{tenant_id}"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"BI-{counter['value']:06d}"


def _public_customer(customer: dict) -> dict:
    return serialize({
        "id": customer["_id"],
        "customer_id": customer["customer_id"],
        "full_name": customer["full_name"],
        "age": customer["age"],
        "reason": customer["reason"],
        "status": customer["status"],
        "created_at": customer["created_at"],
        "last_login_at": customer.get("last_login_at"),
    })


def register_customer(payload: dict) -> tuple[dict | None, str | None]:
    tenant = _tenant_for_widget_key(payload["widget_key"])
    if not tenant:
        return None, "Customer registration is not available for this site."
    db = current_app.extensions["mongo_db"]
    # A counter gives a stable ID without using a Mongo ObjectId as public identity.
    for _ in range(3):
        customer = {
            "tenant_id": tenant["_id"],
            "customer_id": _next_customer_id(tenant["_id"]),
            "full_name": payload["full_name"],
            "full_name_normalized": payload["full_name"].casefold(),
            "age": payload["age"],
            "reason": payload["reason"],
            "password_hash": hash_password(payload["password"]),
            "status": "active",
            "created_at": now(),
            "updated_at": now(),
        }
        try:
            customer["_id"] = db.customers.insert_one(customer).inserted_id
            return _customer_login_result(customer, tenant), None
        except DuplicateKeyError:
            continue
    return None, "Unable to allocate a customer ID. Please try again."


def login_customer(payload: dict) -> dict | None:
    tenant = _tenant_for_widget_key(payload["widget_key"])
    if not tenant:
        return None
    customer = current_app.extensions["mongo_db"].customers.find_one(
        {
            "tenant_id": tenant["_id"],
            "customer_id": payload["customer_id"],
            "full_name_normalized": payload["full_name"].casefold(),
            "status": "active",
        }
    )
    if not customer or not verify_password(payload["password"], customer["password_hash"]):
        return None
    current_app.extensions["mongo_db"].customers.update_one(
        {"_id": customer["_id"]}, {"$set": {"last_login_at": now(), "updated_at": now()}}
    )
    customer["last_login_at"] = now()
    return _customer_login_result(customer, tenant)


def _customer_login_result(customer: dict, tenant: dict) -> dict:
    return {
        "access_token": create_customer_access_token(str(customer["_id"]), str(tenant["_id"])),
        "token_type": "Bearer",
        "customer": _public_customer(customer),
        "tenant": {"id": str(tenant["_id"]), "name": tenant["name"], "slug": tenant["slug"]},
    }


def get_customer_identity(token: str) -> dict | None:
    payload = decode_access_token(token)
    if not payload or payload.get("subject_type") != "customer" or payload.get("role") != "customer":
        return None
    customer_id, tenant_id = payload.get("sub"), payload.get("tenant_id")
    if not ObjectId.is_valid(customer_id) or not ObjectId.is_valid(tenant_id):
        return None
    db = current_app.extensions["mongo_db"]
    tenant = db.tenants.find_one({"_id": ObjectId(tenant_id), "status": "active"})
    customer = db.customers.find_one({"_id": ObjectId(customer_id), "tenant_id": ObjectId(tenant_id), "status": "active"})
    if not tenant or not customer:
        return None
    return {"customer": _public_customer(customer), "tenant": {"id": str(tenant["_id"]), "name": tenant["name"], "slug": tenant["slug"]}, "role": "customer"}
