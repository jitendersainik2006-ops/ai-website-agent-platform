"""Calendar-provider boundary. The local scheduler remains the source of truth."""

from flask import current_app

from app.services.common import serialize


class LocalCalendarAdapter:
    """Local test adapter shaped like future Google/Outlook adapters."""

    def __init__(self):
        self.events: dict[str, dict] = {}

    def get_availability(self, tenant_id: str, start_at, end_at) -> list[dict]:
        """External calendars contribute no conflicts in local development."""
        return []

    def create_event(self, appointment: dict) -> None:
        self.events[str(appointment["_id"])] = self._event("created", appointment)

    def update_event(self, appointment: dict) -> None:
        self.events[str(appointment["_id"])] = self._event("updated", appointment)

    def cancel_event(self, appointment: dict) -> None:
        self.events[str(appointment["_id"])] = self._event("cancelled", appointment)

    @staticmethod
    def _event(action: str, appointment: dict) -> dict:
        return {
            "action": action,
            "appointment_id": str(appointment["_id"]),
            "tenant_id": str(appointment["tenant_id"]),
            "start_at": serialize(appointment["start_at"]),
            "end_at": serialize(appointment["end_at"]),
            "status": appointment["status"],
        }


def sync_calendar(action: str, appointment: dict) -> None:
    """Best-effort calendar sync after local state changes have been persisted."""
    try:
        adapter = current_app.extensions["calendar_adapter"]
        getattr(adapter, f"{action}_event")(appointment)
    except Exception:
        current_app.logger.warning("Appointment calendar sync failed for %s", action)
