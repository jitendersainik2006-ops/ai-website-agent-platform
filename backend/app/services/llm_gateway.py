from flask import current_app

from app.services.common import object_id
from app.services.business_hours_service import format_confirmed_hours, is_hours_question
from app.services.knowledge_service import retrieve

BOOKING_GUIDANCE = (
    "I cannot book, reschedule, or confirm an appointment from this chat, and I will not invent available times. "
    "Please use the appointment booking form to choose a date and an available time, then confirm it there."
)
GREETING_MESSAGES = {"hello", "hi", "hey", "good morning", "good afternoon", "good evening", "hey there", "hello there"}
APPOINTMENT_TERMS = ("book", "booking", "appointment", "meet", "meeting", "schedule", "available slot", "consultation")


def _one_edit_away(first: str, second: str) -> bool:
    if abs(len(first) - len(second)) > 1:
        return False
    if len(first) == len(second):
        return sum(left != right for left, right in zip(first, second)) <= 1
    if len(first) > len(second):
        first, second = second, first
    first_index = second_index = changes = 0
    while first_index < len(first) and second_index < len(second):
        if first[first_index] == second[second_index]:
            first_index += 1
            second_index += 1
            continue
        changes += 1
        if changes > 1:
            return False
        second_index += 1
    return True


def _is_greeting(message: str) -> bool:
    normalized = " ".join("".join(character if character.isalpha() else " " for character in message.lower()).split())
    if normalized in GREETING_MESSAGES:
        return True
    return " " not in normalized and any(_one_edit_away(normalized, greeting) for greeting in ("hello", "hi", "hey"))


def _context_from_history(tenant_id: str, message: str, history: list[dict] | None) -> list[dict]:
    context = retrieve(tenant_id, message)
    if context or not history:
        return context

    visitor_messages = [
        item.get("content", "")
        for item in history
        if item.get("role") in {"visitor", "customer"} and isinstance(item.get("content"), str)
    ]
    # The final visitor message is the current question; use the previous one only
    # when the current wording has no independently grounded match.
    if len(visitor_messages) > 1:
        return retrieve(tenant_id, f"{visitor_messages[-2]} {message}")
    return []


def respond(
    tenant_id: str,
    message: str,
    history: list[dict] | None = None,
    customer_name: str | None = None,
) -> dict:
    """Safe local provider used until an external LLM provider is configured."""
    profile = current_app.extensions["mongo_db"].business_profiles.find_one({"tenant_id": object_id(tenant_id)}) or {}
    business_name = profile.get("name") or "Black Intel"

    context = _context_from_history(tenant_id, message, history)
    lowered = message.lower()
    intent = "general"
    if any(term in lowered for term in APPOINTMENT_TERMS):
        intent = "appointment"
    elif any(phrase in lowered for phrase in ("request a quote", "get a quote", "callback", "contact", "call me", "interested in")):
        intent = "lead"

    if is_hours_question(message):
        hours = format_confirmed_hours(tenant_id)
        if hours:
            return {"answer": hours, "citations": ["Business hours"], "intent": intent, "provider": "local"}

    if intent == "appointment":
        return {"answer": BOOKING_GUIDANCE, "citations": [], "intent": intent, "provider": "local"}

    if _is_greeting(message):
        greeting = (
            f"Hello {customer_name}. I can help with {business_name}'s approved services, FAQs, or appointment booking."
            if customer_name
            else f"Hello. I can help with {business_name}'s approved services, FAQs, or appointment booking."
        )
        return {
            "answer": greeting,
            "citations": [],
            "intent": intent,
            "provider": "local",
        }

    if context:
        source = context[0]
        answer = source["content"].strip()
        if len(answer) > 600:
            answer = answer[:597].rstrip() + "..."
        return {"answer": answer, "citations": [source["title"]], "intent": intent, "provider": "local"}

    contact = profile.get("contact_email")
    fallback = "I do not have confirmed information about that."
    if contact:
        fallback += f" Please contact the team at {contact}."
    return {"answer": fallback, "citations": [], "intent": intent, "provider": "local"}
