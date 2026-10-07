from datetime import datetime, timedelta
import hashlib
import hmac
import secrets
from zoneinfo import ZoneInfo

from flask import current_app
from pymongo.errors import DuplicateKeyError

from app.services.common import now, object_id, serialize
from app.services.calendar_adapter import sync_calendar
from app.services.notifications import emit_appointment_notification


def _profile(tenant_id: str) -> dict:
    return current_app.extensions["mongo_db"].business_profiles.find_one({"tenant_id": object_id(tenant_id)}) or {}


def _in_timezone(value: datetime, timezone: ZoneInfo) -> datetime:
    """MongoDB commonly returns naive datetimes; stored values represent UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(timezone)


def available_slots(tenant_id: str, date_text: str, exclude_appointment_id: str | None = None) -> list[str]:
    profile = _profile(tenant_id)
    timezone = ZoneInfo(profile.get("timezone", "UTC"))
    target = datetime.fromisoformat(date_text).date()
    rule = current_app.extensions["mongo_db"].business_hours.find_one(
        {"tenant_id": object_id(tenant_id), "weekday": target.weekday(), "enabled": True}
    )
    if not rule:
        return []
    start = datetime.combine(target, datetime.strptime(rule["start_time"], "%H:%M").time(), timezone)
    end = datetime.combine(target, datetime.strptime(rule["end_time"], "%H:%M").time(), timezone)
    duration = int(profile.get("appointment_duration_minutes", 30))
    buffer = int(profile.get("appointment_buffer_minutes", 0))
    db = current_app.extensions["mongo_db"]
    blocks = list(db.blocked_times.find({"tenant_id": object_id(tenant_id)}))
    try:
        external_blocks = current_app.extensions["calendar_adapter"].get_availability(tenant_id, start, end)
    except Exception:
        current_app.logger.warning("Calendar availability lookup failed")
        external_blocks = []
    slots = []
    cursor = start
    while cursor + timedelta(minutes=duration) <= end:
        finish = cursor + timedelta(minutes=duration)
        query = {"tenant_id": object_id(tenant_id), "status": {"$in": ["confirmed", "pending", "rescheduled"]}, "start_at": {"$lt": finish + timedelta(minutes=buffer)}, "end_at": {"$gt": cursor - timedelta(minutes=buffer)}}
        if exclude_appointment_id and object_id(exclude_appointment_id):
            query["_id"] = {"$ne": object_id(exclude_appointment_id)}
        conflict = db.appointments.find_one(query)
        blocked = any(
            _in_timezone(block["start_at"], timezone) < finish
            and _in_timezone(block["end_at"], timezone) > cursor
            for block in blocks
        )
        externally_busy = any(
            _in_timezone(block["start_at"], timezone) < finish
            and _in_timezone(block["end_at"], timezone) > cursor
            for block in external_blocks
            if isinstance(block, dict) and block.get("start_at") and block.get("end_at")
        )
        if not conflict and not blocked and not externally_busy:
            slots.append(cursor.isoformat())
        cursor = finish + timedelta(minutes=buffer)
    return slots


def _token_hash(token: str) -> str:
    return hmac.new(current_app.config["SECRET_KEY"].encode(), token.encode(), hashlib.sha256).hexdigest()


def _parse_start(tenant_id: str, value: str) -> tuple[datetime | None, str | None]:
    profile = _profile(tenant_id)
    try:
        start = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None, "A valid appointment start time is required."
    if start.tzinfo is None:
        return None, "Appointment time must include a timezone."
    return start.astimezone(ZoneInfo(profile.get("timezone", "UTC"))), None


def create_appointment(tenant_id: str, payload: dict) -> tuple[dict | None, str | None]:
    profile = _profile(tenant_id)
    start, error = _parse_start(tenant_id, payload.get("start_at"))
    if error:
        return None, error
    if start.isoformat() not in available_slots(tenant_id, start.date().isoformat()):
        return None, "That appointment slot is no longer available."
    duration = int(profile.get("appointment_duration_minutes", 30))
    db = current_app.extensions["mongo_db"]
    lead = None
    if payload.get("email"):
        lead = db.leads.find_one({"tenant_id": object_id(tenant_id), "email": payload["email"].lower()})
    lead_data = {"name": payload.get("name", "Visitor"), "email": payload.get("email", ""), "phone": payload.get("phone", ""), "requirement": payload.get("requirement", "Appointment request"), "source": "widget", "status": "new", "updated_at": now()}
    if lead:
        db.leads.update_one({"_id": lead["_id"]}, {"$set": lead_data})
    else:
        lead_data.update({"tenant_id": object_id(tenant_id), "created_at": now()})
        lead_data["_id"] = db.leads.insert_one(lead_data).inserted_id
        lead = lead_data
    token = secrets.token_urlsafe(32)
    record = {"tenant_id": object_id(tenant_id), "lead_id": lead["_id"], "start_at": start, "end_at": start + timedelta(minutes=duration), "timezone": str(start.tzinfo), "status": "confirmed", "cancellation_token_hash": _token_hash(token), "history": [{"action": "booked", "at": now()}], "created_at": now(), "updated_at": now()}
    try:
        record["_id"] = db.appointments.insert_one(record).inserted_id
    except DuplicateKeyError:
        return None, "That appointment slot was just booked. Please choose another time."
    result = serialize(record)
    result["manage_token"] = token
    sync_calendar("create", record)
    emit_appointment_notification("appointment.confirmed", record)
    return result, None


def _managed_appointment(tenant_id: str, appointment_id: str, token: str) -> dict | None:
    identifier = object_id(appointment_id)
    if not identifier or not isinstance(token, str) or len(token) < 20:
        return None
    return current_app.extensions["mongo_db"].appointments.find_one({"_id": identifier, "tenant_id": object_id(tenant_id), "cancellation_token_hash": _token_hash(token)})


def cancel_appointment(tenant_id: str, appointment_id: str, token: str) -> tuple[dict | None, str | None]:
    appointment = _managed_appointment(tenant_id, appointment_id, token)
    if not appointment:
        return None, "Appointment management is not authorized."
    if appointment["status"] == "cancelled":
        return serialize(appointment), None
    db = current_app.extensions["mongo_db"]
    db.appointments.update_one({"_id": appointment["_id"], "tenant_id": appointment["tenant_id"], "status": {"$in": ["confirmed", "pending", "rescheduled"]}}, {"$set": {"status": "cancelled", "updated_at": now()}, "$push": {"history": {"action": "cancelled", "at": now()}}})
    updated = db.appointments.find_one({"_id": appointment["_id"]})
    sync_calendar("cancel", updated)
    emit_appointment_notification("appointment.cancelled", updated)
    return serialize(updated), None


def reschedule_appointment(tenant_id: str, appointment_id: str, token: str, start_value: str) -> tuple[dict | None, str | None]:
    appointment = _managed_appointment(tenant_id, appointment_id, token)
    if not appointment:
        return None, "Appointment management is not authorized."
    if appointment["status"] == "cancelled":
        return None, "Cancelled appointments cannot be rescheduled."
    start, error = _parse_start(tenant_id, start_value)
    if error:
        return None, error
    if start.isoformat() not in available_slots(tenant_id, start.date().isoformat(), str(appointment["_id"])):
        return None, "That appointment slot is no longer available."
    duration = int(_profile(tenant_id).get("appointment_duration_minutes", 30))
    db = current_app.extensions["mongo_db"]
    try:
        updated = db.appointments.find_one_and_update({"_id": appointment["_id"], "tenant_id": appointment["tenant_id"], "status": {"$in": ["confirmed", "pending", "rescheduled"]}}, {"$set": {"start_at": start, "end_at": start + timedelta(minutes=duration), "status": "rescheduled", "updated_at": now()}, "$push": {"history": {"action": "rescheduled", "at": now(), "previous_start_at": appointment["start_at"], "new_start_at": start}}}, return_document=True)
    except DuplicateKeyError:
        return None, "That appointment slot was just booked. Please choose another time."
    if not updated:
        return None, "Appointment is no longer available for changes."
    sync_calendar("update", updated)
    emit_appointment_notification("appointment.rescheduled", updated)
    return serialize(updated), None


def admin_cancel_appointment(tenant_id: str, appointment_id: str) -> tuple[dict | None, str | None]:
    """Tenant-authorized admin cancellation; no visitor management token is involved."""
    identifier = object_id(appointment_id)
    if not identifier:
        return None, "Appointment was not found."
    db = current_app.extensions["mongo_db"]
    appointment = db.appointments.find_one({"_id": identifier, "tenant_id": object_id(tenant_id)})
    if not appointment:
        return None, "Appointment was not found."
    if appointment["status"] == "cancelled":
        return serialize(appointment), None
    updated = db.appointments.find_one_and_update(
        {"_id": identifier, "tenant_id": object_id(tenant_id), "status": {"$in": ["confirmed", "pending", "rescheduled"]}},
        {"$set": {"status": "cancelled", "updated_at": now()}, "$push": {"history": {"action": "admin_cancelled", "at": now()}}},
        return_document=True,
    )
    if not updated:
        return None, "Appointment is no longer available for changes."
    sync_calendar("cancel", updated)
    emit_appointment_notification("appointment.cancelled", updated)
    return serialize(updated), None


def admin_reschedule_appointment(tenant_id: str, appointment_id: str, start_value: str) -> tuple[dict | None, str | None]:
    """Tenant-authorized admin reschedule using the same availability checks as visitors."""
    identifier = object_id(appointment_id)
    if not identifier:
        return None, "Appointment was not found."
    db = current_app.extensions["mongo_db"]
    appointment = db.appointments.find_one({"_id": identifier, "tenant_id": object_id(tenant_id)})
    if not appointment:
        return None, "Appointment was not found."
    if appointment["status"] == "cancelled":
        return None, "Cancelled appointments cannot be rescheduled."
    start, error = _parse_start(tenant_id, start_value)
    if error:
        return None, error
    if start.isoformat() not in available_slots(tenant_id, start.date().isoformat(), appointment_id):
        return None, "That appointment slot is no longer available."
    duration = int(_profile(tenant_id).get("appointment_duration_minutes", 30))
    try:
        updated = db.appointments.find_one_and_update(
            {"_id": identifier, "tenant_id": object_id(tenant_id), "status": {"$in": ["confirmed", "pending", "rescheduled"]}},
            {"$set": {"start_at": start, "end_at": start + timedelta(minutes=duration), "status": "rescheduled", "updated_at": now()}, "$push": {"history": {"action": "admin_rescheduled", "at": now(), "previous_start_at": appointment["start_at"], "new_start_at": start}}},
            return_document=True,
        )
    except DuplicateKeyError:
        return None, "That appointment slot was just booked. Please choose another time."
    if not updated:
        return None, "Appointment is no longer available for changes."
    sync_calendar("update", updated)
    emit_appointment_notification("appointment.rescheduled", updated)
    return serialize(updated), None
