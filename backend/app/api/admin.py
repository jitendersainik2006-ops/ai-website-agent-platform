from flask import Blueprint, g, jsonify, request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.security.auth_context import require_auth
from app.security.permissions import require_roles
from app.services.admin_context_service import public_identity
from app.services.common import audit, now, object_id, serialize
from app.services.crud_service import create_record, delete_record, get_record, list_records, update_record
from app.services.scheduling_service import admin_cancel_appointment, admin_reschedule_appointment

admin_bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")
WRITE_ROLES = ("owner", "admin", "manager")


def _tenant_id() -> str:
    return g.auth["tenant"]["id"]


def _payload(required=()):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify({"error": "validation_error", "message": "A JSON object is required."}), 400)
    missing = [field for field in required if not isinstance(payload.get(field), str) or not payload[field].strip()]
    if missing:
        return None, (jsonify({"error": "validation_error", "message": f"Missing required fields: {', '.join(missing)}."}), 400)
    return payload, None


@admin_bp.get("/context")
@require_auth
def context():
    return jsonify(public_identity(g.auth))


@admin_bp.route("/business", methods=["GET", "PATCH"])
@require_auth
def business():
    db = __import__("flask").current_app.extensions["mongo_db"]
    tenant_id = _tenant_id()
    if request.method == "GET":
        record = db.business_profiles.find_one({"tenant_id": object_id(tenant_id)}) or {}
        return jsonify(serialize(record))
    if g.auth["role"] not in WRITE_ROLES:
        return jsonify({"error": "forbidden", "message": "You do not have permission for this action."}), 403
    payload, error = _payload()
    if error:
        return error
    allowed = {"name", "description", "contact_email", "contact_phone", "address", "timezone", "appointment_duration_minutes", "appointment_buffer_minutes"}
    changes = {key: value for key, value in payload.items() if key in allowed}
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except (TypeError, ZoneInfoNotFoundError):
            return jsonify({"error": "validation_error", "message": "timezone must be a valid IANA timezone."}), 400
    for field, minimum in (("appointment_duration_minutes", 1), ("appointment_buffer_minutes", 0)):
        if field in changes and (not isinstance(changes[field], int) or isinstance(changes[field], bool) or changes[field] < minimum):
            return jsonify({"error": "validation_error", "message": f"{field} must be an integer of at least {minimum}."}), 400
    changes["updated_at"] = now()
    db.business_profiles.update_one({"tenant_id": object_id(tenant_id)}, {"$set": changes, "$setOnInsert": {"tenant_id": object_id(tenant_id), "created_at": now()}}, upsert=True)
    audit(object_id(tenant_id), "business.updated", "business_profile")
    return jsonify(serialize(db.business_profiles.find_one({"tenant_id": object_id(tenant_id)})))


def _crud_routes(collection: str, required_fields=()):
    def list_or_create():
        tenant_id = _tenant_id()
        if request.method == "GET":
            return jsonify(list_records(collection, tenant_id))
        payload, error = _payload(required_fields)
        if error:
            return error
        record = create_record(collection, tenant_id, payload)
        audit(object_id(tenant_id), f"{collection}.created", collection, record["_id"])
        return jsonify(record), 201

    def detail(record_id):
        tenant_id = _tenant_id()
        if request.method == "GET":
            record = get_record(collection, tenant_id, record_id)
            return (jsonify(record), 200) if record else (jsonify({"error": "not_found"}), 404)
        if request.method == "DELETE":
            if not delete_record(collection, tenant_id, record_id):
                return jsonify({"error": "not_found"}), 404
            audit(object_id(tenant_id), f"{collection}.deleted", collection, object_id(record_id))
            return "", 204
        payload, error = _payload()
        if error:
            return error
        record = update_record(collection, tenant_id, record_id, payload)
        if record:
            audit(object_id(tenant_id), f"{collection}.updated", collection, object_id(record_id))
        return (jsonify(record), 200) if record else (jsonify({"error": "not_found"}), 404)

    return list_or_create, detail


for _collection, _fields, _endpoint in (("services", ("title", "description"), "services"), ("faqs", ("question", "answer"), "faqs"), ("knowledge", ("title", "content"), "knowledge")):
    _list, _detail = _crud_routes(_collection, _fields)
    _list = require_auth(require_roles(*WRITE_ROLES)(_list)) if False else _list
    admin_bp.add_url_rule(f"/{_endpoint}", f"{_endpoint}_list", require_auth(require_roles(*WRITE_ROLES)(_list)), methods=["POST"])
    admin_bp.add_url_rule(f"/{_endpoint}", f"{_endpoint}_get", require_auth(_list), methods=["GET"])
    admin_bp.add_url_rule(f"/{_endpoint}/<record_id>", f"{_endpoint}_detail", require_auth(require_roles(*WRITE_ROLES)(_detail)), methods=["PATCH", "DELETE"])
    admin_bp.add_url_rule(f"/{_endpoint}/<record_id>", f"{_endpoint}_one", require_auth(_detail), methods=["GET"])


@admin_bp.route("/business-hours", methods=["GET", "PUT"])
@require_auth
def business_hours():
    db = __import__("flask").current_app.extensions["mongo_db"]
    tenant = object_id(_tenant_id())
    if request.method == "GET":
        return jsonify([serialize(item) for item in db.business_hours.find({"tenant_id": tenant}).sort("weekday", 1)])
    if g.auth["role"] not in WRITE_ROLES:
        return jsonify({"error": "forbidden"}), 403
    payload, error = _payload()
    if error or not isinstance(payload.get("hours"), list):
        return error or (jsonify({"error": "validation_error", "message": "hours must be a list."}), 400)
    from datetime import datetime

    records = []
    weekdays = set()
    for item in payload["hours"]:
        if not isinstance(item, dict) or not isinstance(item.get("weekday"), int) or item["weekday"] not in range(7):
            return jsonify({"error": "validation_error", "message": "Each hour entry requires a weekday from 0 to 6."}), 400
        if item["weekday"] in weekdays:
            return jsonify({"error": "validation_error", "message": "Each weekday can be configured once."}), 400
        weekdays.add(item["weekday"])
        start_time, end_time = item.get("start_time", "09:00"), item.get("end_time", "17:00")
        try:
            start = datetime.strptime(start_time, "%H:%M").time()
            end = datetime.strptime(end_time, "%H:%M").time()
        except (TypeError, ValueError):
            return jsonify({"error": "validation_error", "message": "Hours must use HH:MM times."}), 400
        if start >= end:
            return jsonify({"error": "validation_error", "message": "End time must be after start time."}), 400
        records.append({"tenant_id": tenant, "weekday": item["weekday"], "enabled": bool(item.get("enabled", True)), "start_time": start_time, "end_time": end_time, "updated_at": now()})
    db.business_hours.delete_many({"tenant_id": tenant})
    if records:
        db.business_hours.insert_many(records)
    audit(tenant, "business_hours.updated", "business_hours")
    return jsonify([serialize(item) for item in records])


@admin_bp.route("/availability/blocked", methods=["GET", "POST"])
@require_auth
def blocked_times():
    tenant_id = _tenant_id()
    if request.method == "GET":
        return jsonify(list_records("blocked_times", tenant_id))
    if g.auth["role"] not in WRITE_ROLES:
        return jsonify({"error": "forbidden", "message": "You do not have permission for this action."}), 403
    payload, error = _payload(("start_at", "end_at"))
    if error:
        return error
    from datetime import datetime
    try:
        payload["start_at"] = datetime.fromisoformat(payload["start_at"])
        payload["end_at"] = datetime.fromisoformat(payload["end_at"])
    except ValueError:
        return jsonify({"error": "validation_error", "message": "Times must be ISO 8601."}), 400
    if payload["start_at"].tzinfo is None or payload["end_at"].tzinfo is None or payload["start_at"] >= payload["end_at"]:
        return jsonify({"error": "validation_error", "message": "Times must include timezones and end after start."}), 400
    record = create_record("blocked_times", tenant_id, payload)
    audit(object_id(tenant_id), "blocked_time.created", "blocked_times", object_id(record["_id"]))
    return jsonify(record), 201


@admin_bp.delete("/availability/blocked/<record_id>")
@require_auth
@require_roles(*WRITE_ROLES)
def delete_blocked_time(record_id):
    if not delete_record("blocked_times", _tenant_id(), record_id):
        return jsonify({"error": "not_found"}), 404
    audit(object_id(_tenant_id()), "blocked_time.deleted", "blocked_times", object_id(record_id))
    return "", 204


@admin_bp.get("/leads")
@require_auth
def leads():
    return jsonify(list_records("leads", _tenant_id()))


@admin_bp.route("/leads/<record_id>", methods=["GET", "PATCH"])
@require_auth
def lead_detail(record_id):
    if request.method == "GET":
        record = get_record("leads", _tenant_id(), record_id)
        return (jsonify(record), 200) if record else (jsonify({"error": "not_found"}), 404)
    if g.auth["role"] not in WRITE_ROLES:
        return jsonify({"error": "forbidden", "message": "You do not have permission for this action."}), 403
    payload, error = _payload()
    if error:
        return error
    record = update_record("leads", _tenant_id(), record_id, payload)
    if record:
        audit(object_id(_tenant_id()), "lead.updated", "leads", object_id(record_id))
    return (jsonify(record), 200) if record else (jsonify({"error": "not_found"}), 404)


@admin_bp.get("/conversations")
@require_auth
def conversations():
    return jsonify(list_records("conversations", _tenant_id()))


@admin_bp.get("/conversations/<record_id>")
@require_auth
def conversation_detail(record_id):
    record = get_record("conversations", _tenant_id(), record_id)
    if not record:
        return jsonify({"error": "not_found"}), 404
    db = __import__("flask").current_app.extensions["mongo_db"]
    record["messages"] = [serialize(item) for item in db.messages.find({"tenant_id": object_id(_tenant_id()), "conversation_id": object_id(record_id)}).sort("created_at", 1)]
    return jsonify(record)


@admin_bp.route("/appointments", methods=["GET", "PATCH"])
@require_auth
def appointments():
    if request.method == "GET":
        return jsonify(list_records("appointments", _tenant_id()))
    if g.auth["role"] not in WRITE_ROLES:
        return jsonify({"error": "forbidden", "message": "You do not have permission for this action."}), 403
    payload, error = _payload(("id", "status"))
    if error:
        return error
    if payload["status"] != "cancelled":
        return jsonify({"error": "validation_error", "message": "Use the appointment reschedule endpoint for time changes."}), 400
    record, message = admin_cancel_appointment(_tenant_id(), payload["id"])
    if record:
        audit(object_id(_tenant_id()), "appointment.status_updated", "appointments", object_id(payload["id"]), {"status": payload["status"]})
    return (jsonify(record), 200) if record else (jsonify({"error": "not_found", "message": message}), 404)


@admin_bp.get("/appointments/<record_id>")
@require_auth
def appointment_detail(record_id):
    record = get_record("appointments", _tenant_id(), record_id)
    if not record:
        return jsonify({"error": "not_found"}), 404
    db = __import__("flask").current_app.extensions["mongo_db"]
    if record.get("lead_id"):
        lead = db.leads.find_one({"_id": object_id(record["lead_id"]), "tenant_id": object_id(_tenant_id())})
        if lead:
            record["lead"] = serialize(lead)
    return jsonify(record)


@admin_bp.post("/appointments/<record_id>/cancel")
@require_auth
@require_roles(*WRITE_ROLES)
def admin_cancel(record_id):
    record, message = admin_cancel_appointment(_tenant_id(), record_id)
    if not record:
        return jsonify({"error": "not_found", "message": message}), 404
    audit(object_id(_tenant_id()), "appointment.admin_cancelled", "appointments", object_id(record_id))
    return jsonify(record)


@admin_bp.post("/appointments/<record_id>/reschedule")
@require_auth
@require_roles(*WRITE_ROLES)
def admin_reschedule(record_id):
    payload, error = _payload(("start_at",))
    if error:
        return error
    record, message = admin_reschedule_appointment(_tenant_id(), record_id, payload["start_at"])
    if not record:
        status = 404 if message == "Appointment was not found." else 409
        return jsonify({"error": "reschedule_unavailable", "message": message}), status
    audit(object_id(_tenant_id()), "appointment.admin_rescheduled", "appointments", object_id(record_id))
    return jsonify(record)


@admin_bp.get("/analytics")
@require_auth
def analytics():
    db = __import__("flask").current_app.extensions["mongo_db"]
    tenant = object_id(_tenant_id())
    conversations_count = db.conversations.count_documents({"tenant_id": tenant})
    leads_count = db.leads.count_documents({"tenant_id": tenant})
    appointments_count = db.appointments.count_documents({"tenant_id": tenant, "status": "confirmed"})
    return jsonify({"total_conversations": conversations_count, "total_leads": leads_count, "total_appointments": appointments_count, "conversion_rate": round((leads_count / conversations_count * 100), 1) if conversations_count else 0, "recent_leads": [serialize(item) for item in db.leads.find({"tenant_id": tenant}).sort("created_at", -1).limit(5)], "recent_appointments": [serialize(item) for item in db.appointments.find({"tenant_id": tenant}).sort("start_at", -1).limit(5)]})


@admin_bp.route("/widget-config", methods=["GET", "PATCH"])
@require_auth
def widget_config():
    db = __import__("flask").current_app.extensions["mongo_db"]
    tenant = object_id(_tenant_id())
    if request.method == "GET":
        return jsonify(serialize(db.widget_configs.find_one({"tenant_id": tenant}) or {}))
    if g.auth["role"] not in WRITE_ROLES:
        return jsonify({"error": "forbidden", "message": "You do not have permission for this action."}), 403
    payload, error = _payload()
    if error:
        return error
    allowed = {"allowed_origins", "theme", "enabled", "welcome_message"}
    db.widget_configs.update_one({"tenant_id": tenant}, {"$set": {key: value for key, value in payload.items() if key in allowed}}, upsert=True)
    audit(tenant, "widget_config.updated", "widget_config")
    return jsonify(serialize(db.widget_configs.find_one({"tenant_id": tenant})))
