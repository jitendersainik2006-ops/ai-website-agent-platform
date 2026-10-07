from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps
import secrets

from flask import Blueprint, current_app, g, jsonify, request

from app.services.common import now, object_id, serialize
from app.services.llm_gateway import respond
from app.services.scheduling_service import available_slots, cancel_appointment, create_appointment, reschedule_appointment

public_bp = Blueprint("public", __name__, url_prefix="/api/v1")
_requests = defaultdict(deque)


def _rate_limit(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        key = f"{request.remote_addr}:{request.headers.get('X-Widget-Key', '')}"
        queue = _requests[key]
        moment = datetime.now(timezone.utc).timestamp()
        while queue and queue[0] < moment - 60:
            queue.popleft()
        if len(queue) >= 30:
            return jsonify({"error": "rate_limited", "message": "Please try again shortly."}), 429
        queue.append(moment)
        return view(*args, **kwargs)
    return wrapped


def require_widget(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        key = request.headers.get("X-Widget-Key") or request.args.get("widget_key")
        if not key and request.is_json:
            key = (request.get_json(silent=True) or {}).get("widget_key")
        config = current_app.extensions["mongo_db"].widget_configs.find_one({"public_key": key, "enabled": {"$ne": False}})
        if not config:
            return jsonify({"error": "invalid_widget", "message": "Widget access is not available."}), 401
        origin = request.headers.get("Origin")
        allowed = config.get("allowed_origins", [])
        if origin and allowed and origin not in allowed:
            return jsonify({"error": "origin_not_allowed", "message": "Widget origin is not allowed."}), 403
        g.widget = config
        return view(*args, **kwargs)
    return wrapped


def _tenant_id() -> str:
    return str(g.widget["tenant_id"])


def _json() -> dict:
    return request.get_json(silent=True) or {}


@public_bp.get("/public/widget-config")
@require_widget
def widget_config():
    profile = current_app.extensions["mongo_db"].business_profiles.find_one({"tenant_id": g.widget["tenant_id"]}) or {}
    return jsonify({"business_name": profile.get("name", "Support"), "welcome_message": g.widget.get("welcome_message", "How can I help today?"), "theme": g.widget.get("theme", {}), "timezone": profile.get("timezone", "UTC")})


@public_bp.post("/public/conversations")
@require_widget
@_rate_limit
def create_conversation():
    payload = _json()
    visitor_id = str(payload.get("visitor_id") or secrets.token_urlsafe(16))
    record = {"tenant_id": g.widget["tenant_id"], "visitor_id": visitor_id, "channel": "widget", "status": "open", "created_at": now(), "updated_at": now()}
    record["_id"] = current_app.extensions["mongo_db"].conversations.insert_one(record).inserted_id
    return jsonify({"conversation": serialize(record)}), 201


@public_bp.post("/public/conversations/<conversation_id>/messages")
@public_bp.post("/chat")
@require_widget
@_rate_limit
def send_message(conversation_id=None):
    payload = _json()
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        return jsonify({"error": "validation_error", "message": "A message up to 4000 characters is required."}), 400
    db = current_app.extensions["mongo_db"]
    tenant_id = _tenant_id()
    if conversation_id:
        if not object_id(conversation_id):
            return jsonify({"error": "not_found"}), 404
        conversation = db.conversations.find_one({"_id": object_id(conversation_id), "tenant_id": g.widget["tenant_id"]})
        if not conversation:
            return jsonify({"error": "not_found"}), 404
    else:
        conversation = {"tenant_id": g.widget["tenant_id"], "visitor_id": str(payload.get("visitor_id") or secrets.token_urlsafe(16)), "channel": "widget", "status": "open", "created_at": now(), "updated_at": now()}
        conversation["_id"] = db.conversations.insert_one(conversation).inserted_id
    db.messages.insert_one({"tenant_id": g.widget["tenant_id"], "conversation_id": conversation["_id"], "role": "visitor", "content": message.strip(), "created_at": now()})
    answer = respond(tenant_id, message.strip())
    db.messages.insert_one({"tenant_id": g.widget["tenant_id"], "conversation_id": conversation["_id"], "role": "agent", "content": answer["answer"], "citations": answer["citations"], "created_at": now()})
    db.conversations.update_one({"_id": conversation["_id"]}, {"$set": {"updated_at": now()}})
    return jsonify({"conversation_id": str(conversation["_id"]), **answer})


@public_bp.post("/public/leads")
@require_widget
@_rate_limit
def create_lead():
    payload = _json()
    email = payload.get("email", "").strip().lower()
    if not email and not payload.get("phone"):
        return jsonify({"error": "validation_error", "message": "Email or phone is required."}), 400
    db = current_app.extensions["mongo_db"]
    existing = db.leads.find_one({"tenant_id": g.widget["tenant_id"], "email": email}) if email else None
    changes = {"name": str(payload.get("name", "Visitor"))[:120], "email": email, "phone": str(payload.get("phone", ""))[:50], "requirement": str(payload.get("requirement", ""))[:2000], "source": "widget", "status": "new", "updated_at": now()}
    if existing:
        db.leads.update_one({"_id": existing["_id"]}, {"$set": changes})
        lead = db.leads.find_one({"_id": existing["_id"]})
    else:
        changes.update({"tenant_id": g.widget["tenant_id"], "created_at": now()})
        changes["_id"] = db.leads.insert_one(changes).inserted_id
        lead = changes
    return jsonify({"lead": serialize(lead)}), 201


@public_bp.get("/public/availability/slots")
@require_widget
def slots():
    date = request.args.get("date", "")
    try:
        return jsonify({"slots": available_slots(_tenant_id(), date)})
    except (ValueError, KeyError):
        return jsonify({"error": "validation_error", "message": "date must be YYYY-MM-DD."}), 400


@public_bp.post("/public/appointments")
@require_widget
@_rate_limit
def book():
    appointment, error = create_appointment(_tenant_id(), _json())
    if error:
        return jsonify({"error": "booking_unavailable", "message": error}), 409
    return jsonify({"appointment": appointment}), 201


@public_bp.post("/public/appointments/<appointment_id>/cancel")
@require_widget
@_rate_limit
def cancel(appointment_id):
    appointment, error = cancel_appointment(_tenant_id(), appointment_id, _json().get("manage_token", ""))
    if error:
        return jsonify({"error": "appointment_not_authorized", "message": error}), 403
    return jsonify({"appointment": appointment})


@public_bp.post("/public/appointments/<appointment_id>/reschedule")
@require_widget
@_rate_limit
def reschedule(appointment_id):
    payload = _json()
    appointment, error = reschedule_appointment(_tenant_id(), appointment_id, payload.get("manage_token", ""), payload.get("start_at"))
    if error:
        status = 403 if error == "Appointment management is not authorized." else 409
        return jsonify({"error": "reschedule_unavailable", "message": error}), status
    return jsonify({"appointment": appointment})
