from flask import current_app

from app.services.common import object_id
from app.services.business_hours_service import format_confirmed_hours, is_hours_question
from app.services.knowledge_service import retrieve


def respond(tenant_id: str, message: str, history: list[dict] | None = None) -> dict:
    """Safe local provider used until an external LLM provider is configured."""
    context = retrieve(tenant_id, message)
    lowered = message.lower()
    intent = "general"
    if any(word in lowered for word in ("book", "appointment", "meeting", "schedule", "available slot")):
        intent = "appointment"
    elif any(phrase in lowered for phrase in ("request a quote", "get a quote", "callback", "contact", "call me", "interested in")):
        intent = "lead"

    if is_hours_question(message):
        hours = format_confirmed_hours(tenant_id)
        if hours:
            return {"answer": hours, "citations": ["Business hours"], "intent": intent, "provider": "local"}

    if context:
        source = context[0]
        answer = source["content"].strip()
        if len(answer) > 600:
            answer = answer[:597].rstrip() + "..."
        return {"answer": answer, "citations": [source["title"]], "intent": intent, "provider": "local"}

    profile = current_app.extensions["mongo_db"].business_profiles.find_one({"tenant_id": object_id(tenant_id)})
    contact = profile.get("contact_email") if profile else None
    fallback = "I do not have confirmed information about that."
    if contact:
        fallback += f" Please contact the team at {contact}."
    return {"answer": fallback, "citations": [], "intent": intent, "provider": "local"}
