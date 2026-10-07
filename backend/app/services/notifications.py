"""Server-side notification boundary for appointment lifecycle events."""

from flask import current_app

from app.services.common import serialize


class LocalNotificationProvider:
    """Development provider that records only safe event metadata in memory."""

    def __init__(self):
        self.events: list[dict] = []

    def send(self, event_type: str, appointment: dict, lead: dict | None = None) -> None:
        self.events.append(
            {
                "event_type": event_type,
                "appointment_id": str(appointment["_id"]),
                "tenant_id": str(appointment["tenant_id"]),
                "status": appointment["status"],
                "start_at": serialize(appointment["start_at"]),
                "recipient": (lead or {}).get("email"),
            }
        )


def emit_appointment_notification(event_type: str, appointment: dict) -> None:
    """Deliver a lifecycle notification after persistence; never affect the booking."""
    try:
        db = current_app.extensions["mongo_db"]
        lead = db.leads.find_one(
            {"_id": appointment.get("lead_id"), "tenant_id": appointment["tenant_id"]}
        )
        current_app.extensions["notification_provider"].send(event_type, appointment, lead)
    except Exception:
        # Do not include appointment data or exception text, which could contain provider secrets.
        current_app.logger.warning("Appointment notification delivery failed for %s", event_type)
