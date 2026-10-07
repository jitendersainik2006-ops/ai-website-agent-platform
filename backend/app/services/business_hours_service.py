from flask import current_app

from app.services.common import object_id

HOURS_TERMS = {"hour", "hours", "open", "opening", "close", "closing", "office", "timing", "times"}
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def is_hours_question(message: str) -> bool:
    words = {word.lower() for word in message.replace("?", " ").split()}
    return bool(words & HOURS_TERMS)


def format_confirmed_hours(tenant_id: str) -> str | None:
    rules = list(current_app.extensions["mongo_db"].business_hours.find({"tenant_id": object_id(tenant_id), "enabled": True}).sort("weekday", 1))
    if not rules:
        return None
    groups: list[tuple[list[str], str]] = []
    for rule in rules:
        hours = f"{rule['start_time']} to {rule['end_time']}"
        if groups and groups[-1][1] == hours:
            groups[-1][0].append(DAY_NAMES[rule["weekday"]])
        else:
            groups.append(([DAY_NAMES[rule["weekday"]]], hours))
    parts = []
    for days, hours in groups:
        label = days[0] if len(days) == 1 else f"{days[0]} to {days[-1]}"
        parts.append(f"{label}: {hours}")
    return "Confirmed business hours are " + "; ".join(parts) + "."
