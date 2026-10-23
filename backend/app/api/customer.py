import secrets
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from app.schemas.customer import CustomerLoginRequest, CustomerRegistrationRequest
from app.security.customer_context import require_customer_auth
from app.services.common import audit, now, object_id, serialize
from app.services.customer_service import login_customer, register_customer
from app.services.llm_gateway import respond
from app.services.scheduling_service import available_slots, create_appointment, customer_cancel_appointment, customer_requested_start, customer_requested_time_status, customer_reschedule_appointment, get_customer_appointment, tenant_timezone_name


customer_bp = Blueprint("customer", __name__, url_prefix="/api/v1/customer")
INVALID_CREDENTIALS = {"error": "invalid_credentials", "message": "Invalid customer credentials."}
_auth_requests = defaultdict(deque)


def _auth_rate_limit(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        key = f"{id(current_app)}:{request.remote_addr}:{request.endpoint}"
        attempts = _auth_requests[key]
        moment = datetime.now(timezone.utc).timestamp()
        while attempts and attempts[0] < moment - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            return jsonify({"error": "rate_limited", "message": "Please try again shortly."}), 429
        attempts.append(moment)
        return view(*args, **kwargs)

    return wrapped


def _payload(model):
    try:
        return model.model_validate(request.get_json(silent=True) or {}), None
    except ValidationError as err:
        field_errors = {}
        msg = "Please check the required fields."
        for error in err.errors():
            loc = error.get("loc", ())
            if loc:
                field_errors[str(loc[0])] = error.get("msg", "Invalid value")
        if "Passwords do not match" in str(err):
            msg = "Passwords do not match."
        return None, (jsonify({"error": "validation_error", "message": msg, "fields": field_errors}), 400)


def _tenant_oid():
    return object_id(g.customer_auth["tenant"]["id"])


@customer_bp.post("/auth/register")
@_auth_rate_limit
def register():
    payload, error = _payload(CustomerRegistrationRequest)
    if error:
        return error
    result, message = register_customer(payload.model_dump())
    if not result:
        return jsonify({"error": "registration_unavailable", "message": message}), 403
    audit(_tenant_oid_from_result(result), "customer.registered", "customer", object_id(result["customer"]["id"]))
    return jsonify(result), 201


def _tenant_oid_from_result(result):
    return object_id(result["tenant"]["id"])


@customer_bp.post("/auth/login")
@_auth_rate_limit
def login():
    payload, error = _payload(CustomerLoginRequest)
    if error:
        return error
    result = login_customer(payload.model_dump())
    if not result:
        return jsonify(INVALID_CREDENTIALS), 401
    return jsonify(result)


@customer_bp.get("/me")
@require_customer_auth
def me():
    return jsonify(g.customer_auth)


@customer_bp.get("/dashboard")
@require_customer_auth
def dashboard():
    db = current_app.extensions["mongo_db"]
    customer = g.customer_auth["customer"]
    query = {"tenant_id": _tenant_oid(), "customer_id": customer["customer_id"]}
    return jsonify({
        "customer": customer,
        "timezone": tenant_timezone_name(g.customer_auth["tenant"]["id"]),
        "conversations": [serialize(item) for item in db.conversations.find(query).sort("updated_at", -1)],
        "appointments": [serialize(item) for item in db.appointments.find(query).sort("start_at", -1)],
    })


@customer_bp.get("/conversations/<conversation_id>")
@require_customer_auth
def conversation_detail(conversation_id):
    db = current_app.extensions["mongo_db"]
    conversation = db.conversations.find_one(
        {
            "_id": object_id(conversation_id),
            "tenant_id": _tenant_oid(),
            "customer_id": g.customer_auth["customer"]["customer_id"],
        }
    )
    if not conversation:
        return jsonify({"error": "not_found"}), 404
    result = serialize(conversation)
    result["messages"] = [
        serialize(message)
        for message in db.messages.find(
            {"tenant_id": _tenant_oid(), "conversation_id": conversation["_id"]}
        ).sort("created_at", 1)
    ]
    return jsonify(result)


@customer_bp.post("/conversations/<conversation_id>/messages")
@customer_bp.post("/chat")
@require_customer_auth
def chat(conversation_id=None):
    payload = request.get_json(silent=True) or {}
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        return jsonify({"error": "validation_error", "message": "A message up to 4000 characters is required."}), 400
    db = current_app.extensions["mongo_db"]
    tenant_id = _tenant_oid()
    customer = g.customer_auth["customer"]
    if conversation_id:
        conversation = db.conversations.find_one({"_id": object_id(conversation_id), "tenant_id": tenant_id, "customer_id": customer["customer_id"]})
        if not conversation:
            return jsonify({"error": "not_found"}), 404
    else:
        conversation = {"tenant_id": tenant_id, "customer_id": customer["customer_id"], "visitor_id": secrets.token_urlsafe(16), "channel": "customer_portal", "status": "open", "created_at": now(), "updated_at": now()}
        conversation["_id"] = db.conversations.insert_one(conversation).inserted_id
    from app.services.llm_gateway import _canonicalize_query
    clean_message = _canonicalize_query(message.strip())
    db.messages.insert_one({"tenant_id": tenant_id, "conversation_id": conversation["_id"], "role": "customer", "content": clean_message, "created_at": now()})
    history = list(db.messages.find({"tenant_id": tenant_id, "conversation_id": conversation["_id"]}).sort("created_at", -1).limit(8))
    answer = respond(
        str(tenant_id),
        clean_message,
        list(reversed(history)),
        customer_name=customer["full_name"],
    )
    db.messages.insert_one({"tenant_id": tenant_id, "conversation_id": conversation["_id"], "role": "agent", "content": answer["answer"], "citations": answer["citations"], "created_at": now()})
    db.conversations.update_one({"_id": conversation["_id"]}, {"$set": {"updated_at": now()}})
    return jsonify({"conversation_id": str(conversation["_id"]), **answer})


@customer_bp.get("/availability/slots")
@require_customer_auth
def availability():
    try:
        tenant_id = g.customer_auth["tenant"]["id"]
        customer_id = g.customer_auth["customer"]["customer_id"]
        appointment_id = request.args.get("appointment_id")
        exclude_id = None
        if appointment_id:
            appointment = get_customer_appointment(tenant_id, customer_id, appointment_id)
            if not appointment:
                return jsonify({"error": "appointment_not_authorized", "message": "Appointment management is not authorized."}), 403
            exclude_id = str(appointment["_id"])
        return jsonify({"slots": available_slots(tenant_id, request.args.get("date", ""), exclude_appointment_id=exclude_id), "timezone": tenant_timezone_name(tenant_id)})
    except (ValueError, KeyError):
        return jsonify({"error": "validation_error", "message": "date must be YYYY-MM-DD."}), 400


@customer_bp.get("/availability/check")
@require_customer_auth
def check_requested_time():
    tenant_id = g.customer_auth["tenant"]["id"]
    customer_id = g.customer_auth["customer"]["customer_id"]
    appointment_id = request.args.get("appointment_id")
    exclude_id = None
    if appointment_id:
        appointment = get_customer_appointment(tenant_id, customer_id, appointment_id)
        if not appointment:
            return jsonify({"error": "appointment_not_authorized", "message": "Appointment management is not authorized."}), 403
        exclude_id = str(appointment["_id"])
    start, error = customer_requested_time_status(
        tenant_id,
        request.args.get("date", ""),
        request.args.get("time", ""),
        exclude_appointment_id=exclude_id,
    )
    return jsonify({
        "available": error is None,
        "message": error or "Your requested time is currently available. Confirm to book it.",
        "start_at": start.isoformat() if start and error is None else None,
        "timezone": tenant_timezone_name(tenant_id),
    })


@customer_bp.post("/appointments")
@require_customer_auth
def book_appointment():
    payload = request.get_json(silent=True) or {}
    customer = g.customer_auth["customer"]
    start, request_error = customer_requested_start(
        g.customer_auth["tenant"]["id"], payload.get("date", ""), payload.get("time", "")
    )
    if request_error:
        return jsonify({"error": "validation_error", "message": request_error}), 400
    payload["start_at"] = start.isoformat()
    payload.update({"name": customer["full_name"], "customer_id": customer["customer_id"], "source": "customer_portal"})
    appointment, error = create_appointment(g.customer_auth["tenant"]["id"], payload, allow_customer_requested_time=True)
    if error:
        return jsonify({"error": "booking_unavailable", "message": error}), 409
    appointment.pop("manage_token", None)
    audit(_tenant_oid(), "customer.appointment_booked", "appointment", object_id(appointment["_id"]))
    return jsonify({"appointment": appointment}), 201


@customer_bp.post("/appointments/<appointment_id>/cancel")
@require_customer_auth
def cancel_appointment(appointment_id):
    appointment, error = customer_cancel_appointment(g.customer_auth["tenant"]["id"], g.customer_auth["customer"]["customer_id"], appointment_id)
    if not appointment:
        return jsonify({"error": "appointment_not_authorized", "message": error}), 403
    audit(_tenant_oid(), "customer.appointment_cancelled", "appointment", object_id(appointment_id))
    return jsonify({"appointment": appointment})


@customer_bp.post("/appointments/<appointment_id>/reschedule")
@require_customer_auth
def reschedule_appointment(appointment_id):
    payload = request.get_json(silent=True) or {}
    start, request_error = customer_requested_start(
        g.customer_auth["tenant"]["id"], payload.get("date", ""), payload.get("time", "")
    )
    if request_error:
        return jsonify({"error": "validation_error", "message": request_error}), 400
    appointment, error = customer_reschedule_appointment(
        g.customer_auth["tenant"]["id"],
        g.customer_auth["customer"]["customer_id"],
        appointment_id,
        start.isoformat(),
        allow_customer_requested_time=True,
    )
    if not appointment:
        return jsonify({"error": "reschedule_unavailable", "message": error}), 409 if error != "Appointment management is not authorized." else 403
    audit(_tenant_oid(), "customer.appointment_rescheduled", "appointment", object_id(appointment_id))
    return jsonify({"appointment": appointment})
