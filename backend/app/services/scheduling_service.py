from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from pymongo.errors import DuplicateKeyError

from app.services.common import now, object_id, serialize
from app.services.calendar_adapter import sync_calendar
from app.services.notifications import emit_appointment_notification

SLOT_UNAVAILABLE = "That appointment slot is no longer available. Please choose another available time."
REQUEST_UNAVAILABLE = "That requested time is not available. It may be outside business hours, blocked, already booked, or too close to the current time."
REQUEST_CONFLICT = "That requested time is not available because it conflicts with an existing appointment or its required buffer. Choose another time."
REQUEST_BLOCKED = "That requested time is not available because it falls within a company-blocked period. Choose another time."
REQUEST_CALENDAR_BUSY = "That requested time is not available due to an external calendar conflict. Choose another time."
SLOT_INTERVAL_MISALIGNED = "That requested time does not align with the configured appointment slot intervals. Please choose an offered slot time."


def _profile(tenant_id: str) -> dict:
    return current_app.extensions["mongo_db"].business_profiles.find_one({"tenant_id": object_id(tenant_id)}) or {}


def tenant_timezone_name(tenant_id: str) -> str:
    return str(_profile(tenant_id).get("timezone") or "UTC")


def _zone(tenant_id: str) -> ZoneInfo:
    try:
        return ZoneInfo(tenant_timezone_name(tenant_id))
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _in_timezone(value: datetime, tz: ZoneInfo) -> datetime:
    """MongoDB commonly returns naive datetimes; stored values represent UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tz)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _parse_calendar_date(date_text: str) -> date:
    if not isinstance(date_text, str) or len(date_text) != 10:
        raise ValueError("date must be YYYY-MM-DD.")
    return date.fromisoformat(date_text)


def _format_slot(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def available_slots(tenant_id: str, date_text: str, exclude_appointment_id: str | None = None) -> list[str]:
    profile = _profile(tenant_id)
    tz = _zone(tenant_id)
    target = _parse_calendar_date(date_text)
    moment = now().astimezone(tz)
    if target < moment.date():
        return []
    rule = current_app.extensions["mongo_db"].business_hours.find_one(
        {"tenant_id": object_id(tenant_id), "weekday": target.weekday(), "enabled": True}
    )
    if not rule:
        return []
    start = datetime.combine(target, datetime.strptime(rule["start_time"], "%H:%M").time(), tz)
    end = datetime.combine(target, datetime.strptime(rule["end_time"], "%H:%M").time(), tz)
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
        if cursor < moment:
            cursor = finish + timedelta(minutes=buffer)
            continue
        query = {
            "tenant_id": object_id(tenant_id),
            "status": {"$in": ["confirmed", "pending", "rescheduled"]},
            "start_at": {"$lt": _aware_utc(finish + timedelta(minutes=buffer))},
            "end_at": {"$gt": _aware_utc(cursor - timedelta(minutes=buffer))},
        }
        if exclude_appointment_id and object_id(exclude_appointment_id):
            query["_id"] = {"$ne": object_id(exclude_appointment_id)}
        conflict = db.appointments.find_one(query)
        blocked = any(
            _in_timezone(block["start_at"], tz) < finish
            and _in_timezone(block["end_at"], tz) > cursor
            for block in blocks
        )
        externally_busy = any(
            _in_timezone(block["start_at"], tz) < finish
            and _in_timezone(block["end_at"], tz) > cursor
            for block in external_blocks
            if isinstance(block, dict) and block.get("start_at") and block.get("end_at")
        )
        if not conflict and not blocked and not externally_busy:
            slots.append(_format_slot(cursor))
        cursor = finish + timedelta(minutes=buffer)
    return slots


def _token_hash(token: str) -> str:
    return hmac.new(current_app.config["SECRET_KEY"].encode(), token.encode(), hashlib.sha256).hexdigest()


def _parse_start(tenant_id: str, value: str) -> tuple[datetime | None, str | None]:
    try:
        start = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None, "A valid appointment start time is required."
    if start.tzinfo is None:
        return None, "Appointment time must include a timezone."
    return start.astimezone(_zone(tenant_id)).replace(microsecond=0), None


def customer_requested_start(tenant_id: str, date_text: str, time_text: str) -> tuple[datetime | None, str | None]:
    try:
        target = _parse_calendar_date(date_text)
        requested_time = datetime.strptime(str(time_text), "%H:%M").time()
    except (TypeError, ValueError):
        return None, "Choose a valid appointment date and time."
    tz = _zone(tenant_id)
    start = datetime.combine(target, requested_time, tz)
    # Reject local wall times that do not survive a timezone round trip (DST gaps).
    round_trip = start.astimezone(timezone.utc).astimezone(tz)
    if round_trip.date() != target or round_trip.time().replace(microsecond=0) != requested_time:
        return None, "That local time does not exist in the business timezone. Choose another time."
    return start.replace(microsecond=0), None


def _requested_time_error(tenant_id: str, start: datetime, exclude_appointment_id: str | None = None) -> str | None:
    profile = _profile(tenant_id)
    tz = _zone(tenant_id)
    start = start.astimezone(tz)
    finish = start + timedelta(minutes=int(profile.get("appointment_duration_minutes", 30)))
    buffer = timedelta(minutes=int(profile.get("appointment_buffer_minutes", 0)))
    if start <= now().astimezone(tz):
        return "Requested appointment time is in the past. Choose a future time."
    rule = current_app.extensions["mongo_db"].business_hours.find_one(
        {"tenant_id": object_id(tenant_id), "weekday": start.weekday(), "enabled": True}
    )
    if not rule:
        return "The business is not available on that date. Choose another date."
    opening = datetime.combine(start.date(), datetime.strptime(rule["start_time"], "%H:%M").time(), tz)
    closing = datetime.combine(start.date(), datetime.strptime(rule["end_time"], "%H:%M").time(), tz)
    if start < opening or finish > closing:
        return "Requested time is outside business hours or does not leave enough time for the consultation."
    db = current_app.extensions["mongo_db"]
    query = {
        "tenant_id": object_id(tenant_id),
        "status": {"$in": ["confirmed", "pending", "rescheduled"]},
        "start_at": {"$lt": _aware_utc(finish + buffer)},
        "end_at": {"$gt": _aware_utc(start - buffer)},
    }
    if exclude_appointment_id and object_id(exclude_appointment_id):
        query["_id"] = {"$ne": object_id(exclude_appointment_id)}
    if db.appointments.find_one(query):
        return REQUEST_CONFLICT
    blocks = list(db.blocked_times.find({"tenant_id": object_id(tenant_id)}))
    if any(_in_timezone(block["start_at"], tz) < finish and _in_timezone(block["end_at"], tz) > start for block in blocks):
        return REQUEST_BLOCKED
    try:
        external_blocks = current_app.extensions["calendar_adapter"].get_availability(tenant_id, start, finish)
    except Exception:
        current_app.logger.warning("Calendar availability lookup failed")
        external_blocks = []
    if any(
        _in_timezone(block["start_at"], tz) < finish and _in_timezone(block["end_at"], tz) > start
        for block in external_blocks
        if isinstance(block, dict) and block.get("start_at") and block.get("end_at")
    ):
        return REQUEST_CALENDAR_BUSY
    return None


def customer_requested_time_status(tenant_id: str, date_text: str, time_text: str, exclude_appointment_id: str | None = None) -> tuple[datetime | None, str | None]:
    start, error = customer_requested_start(tenant_id, date_text, time_text)
    if error:
        return None, error
    return start, _requested_time_error(tenant_id, start, exclude_appointment_id=exclude_appointment_id)


def _slot_is_offered(tenant_id: str, start: datetime, exclude_appointment_id: str | None = None) -> bool:
    local = start.astimezone(_zone(tenant_id))
    offered = available_slots(tenant_id, local.date().isoformat(), exclude_appointment_id)
    instant = _aware_utc(start)
    return any(_aware_utc(datetime.fromisoformat(item)) == instant for item in offered)


def create_appointment(tenant_id: str, payload: dict, allow_customer_requested_time: bool = False) -> tuple[dict | None, str | None]:
    profile = _profile(tenant_id)
    start, error = _parse_start(tenant_id, payload.get("start_at"))
    if error:
        return None, error
    if allow_customer_requested_time:
        error = _requested_time_error(tenant_id, start)
        if error:
            return None, error
    elif not _slot_is_offered(tenant_id, start):
        return None, SLOT_UNAVAILABLE
    duration = int(profile.get("appointment_duration_minutes", 30))
    db = current_app.extensions["mongo_db"]
    lead = None
    if payload.get("email"):
        lead = db.leads.find_one({"tenant_id": object_id(tenant_id), "email": payload["email"].lower()})
    lead_data = {"name": payload.get("name", "Visitor"), "email": payload.get("email", ""), "phone": payload.get("phone", ""), "requirement": payload.get("requirement", "Appointment request"), "source": payload.get("source", "widget"), "status": "new", "updated_at": now()}
    if isinstance(payload.get("customer_id"), str):
        lead_data["customer_id"] = payload["customer_id"]
    if lead:
        db.leads.update_one({"_id": lead["_id"]}, {"$set": lead_data})
    else:
        lead_data.update({"tenant_id": object_id(tenant_id), "created_at": now()})
        lead_data["_id"] = db.leads.insert_one(lead_data).inserted_id
        lead = lead_data
    token = secrets.token_urlsafe(32)
    record = {"tenant_id": object_id(tenant_id), "lead_id": lead["_id"], "start_at": start, "end_at": start + timedelta(minutes=duration), "timezone": tenant_timezone_name(tenant_id), "status": "confirmed", "cancellation_token_hash": _token_hash(token), "history": [{"action": "booked", "at": now()}], "created_at": now(), "updated_at": now()}
    if isinstance(payload.get("customer_id"), str):
        record["customer_id"] = payload["customer_id"]
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


def get_managed_appointment(tenant_id: str, appointment_id: str, token: str) -> dict | None:
    return _managed_appointment(tenant_id, appointment_id, token)


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
    if not _slot_is_offered(tenant_id, start, str(appointment["_id"])):
        return None, SLOT_UNAVAILABLE
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


def _customer_appointment(tenant_id: str, customer_id: str, appointment_id: str) -> dict | None:
    identifier = object_id(appointment_id)
    if not identifier:
        return None
    return current_app.extensions["mongo_db"].appointments.find_one(
        {"_id": identifier, "tenant_id": object_id(tenant_id), "customer_id": customer_id}
    )


def get_customer_appointment(tenant_id: str, customer_id: str, appointment_id: str) -> dict | None:
    return _customer_appointment(tenant_id, customer_id, appointment_id)


def customer_cancel_appointment(tenant_id: str, customer_id: str, appointment_id: str) -> tuple[dict | None, str | None]:
    appointment = _customer_appointment(tenant_id, customer_id, appointment_id)
    if not appointment:
        return None, "Appointment management is not authorized."
    if appointment["status"] == "cancelled":
        return serialize(appointment), None
    db = current_app.extensions["mongo_db"]
    db.appointments.update_one(
        {"_id": appointment["_id"], "tenant_id": appointment["tenant_id"], "customer_id": customer_id, "status": {"$in": ["confirmed", "pending", "rescheduled"]}},
        {"$set": {"status": "cancelled", "updated_at": now()}, "$push": {"history": {"action": "customer_cancelled", "at": now()}}},
    )
    updated = db.appointments.find_one({"_id": appointment["_id"]})
    sync_calendar("cancel", updated)
    emit_appointment_notification("appointment.cancelled", updated)
    return serialize(updated), None


def customer_reschedule_appointment(tenant_id: str, customer_id: str, appointment_id: str, start_value: str, allow_customer_requested_time: bool = False) -> tuple[dict | None, str | None]:
    appointment = _customer_appointment(tenant_id, customer_id, appointment_id)
    if not appointment:
        return None, "Appointment management is not authorized."
    if appointment["status"] == "cancelled":
        return None, "Cancelled appointments cannot be rescheduled."
    start, error = _parse_start(tenant_id, start_value)
    if error:
        return None, error
    if allow_customer_requested_time:
        error = _requested_time_error(tenant_id, start, appointment_id)
        if error:
            return None, error
    elif not _slot_is_offered(tenant_id, start, appointment_id):
        return None, SLOT_UNAVAILABLE
    duration = int(_profile(tenant_id).get("appointment_duration_minutes", 30))
    db = current_app.extensions["mongo_db"]
    try:
        updated = db.appointments.find_one_and_update(
            {"_id": appointment["_id"], "tenant_id": appointment["tenant_id"], "customer_id": customer_id, "status": {"$in": ["confirmed", "pending", "rescheduled"]}},
            {"$set": {"start_at": start, "end_at": start + timedelta(minutes=duration), "status": "rescheduled", "updated_at": now()}, "$push": {"history": {"action": "customer_rescheduled", "at": now(), "previous_start_at": appointment["start_at"], "new_start_at": start}}},
            return_document=True,
        )
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
    time_error = _requested_time_error(tenant_id, start, exclude_appointment_id=appointment_id)
    if time_error:
        return None, time_error
    if not _slot_is_offered(tenant_id, start, appointment_id):
        return None, SLOT_INTERVAL_MISALIGNED
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
