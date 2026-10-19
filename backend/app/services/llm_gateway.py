import logging
import re
from flask import current_app

from app.services.common import object_id
from app.services.business_hours_service import format_confirmed_hours, is_hours_question
from app.services.knowledge_service import retrieve
from app.services.ai_provider import generate_ai_completion
from app.services.web_search_service import search_web, is_web_search_enabled

logger = logging.getLogger(__name__)

BOOKING_GUIDANCE = (
    "I cannot book, reschedule, or confirm an appointment from this chat, and I will not invent available times. "
    "Please use the appointment booking form to choose a date and an available time, then confirm it there."
)
GREETING_MESSAGES = {"hello", "hi", "hey", "good morning", "good afternoon", "good evening", "hey there", "hello there"}

# Technical and academic markers where words like 'schedule' or 'meet' do NOT represent booking intent
_TECH_ACADEMIC_MARKERS = (
    "cron", "celery", "cpu", "os", "linux", "kernel", "thread", "threads", "process", "processes",
    "algorithm", "algorithms", "parallel", "perpendicular", "geometry", "intersection",
    "lines", "line", "cryptography", "crypto", "middle", "asyncio", "python", "javascript",
    "typescript", "sql", "database", "kubernetes", "k8s", "docker", "container", "code",
    "function", "programming", "math", "mathematics", "meeting minutes", "meeting notes",
    "meeting summary", "scheduling algorithm", "round robin", "priority scheduling",
    "job scheduling", "task scheduling",
)

_EXPLICIT_BOOKING_PHRASES = (
    "book an appointment", "book appointment", "booking an appointment",
    "schedule an appointment", "schedule appointment", "scheduling an appointment",
    "reschedule my appointment", "reschedule appointment", "reschedule my meeting",
    "cancel my appointment", "cancel appointment",
    "book a consultation", "schedule a consultation",
    "book a meeting", "schedule a meeting",
    "book a call", "schedule a call",
    "book a demo", "schedule a demo",
    "available slot", "available slots", "appointment slot", "appointment slots",
    "booking slot", "booking slots",
    "make an appointment", "set up an appointment",
    "book me an appointment", "schedule me an appointment",
    "appointment booking", "consultation booking",
)


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


def is_appointment_intent(message: str) -> bool:
    """Disambiguate true appointment requests from technical or general language.

    Prevents words like 'schedule' (in cron/CPU contexts) or 'meet' (in geometry/parallel lines)
    from triggering booking guidance incorrectly.
    """
    lowered = message.lower()

    # If technical or academic terms appear, only classify as appointment if there is an explicit booking phrase
    if any(marker in lowered for marker in _TECH_ACADEMIC_MARKERS):
        return any(phrase in lowered for phrase in _EXPLICIT_BOOKING_PHRASES)

    # Check high-confidence booking phrases
    if any(phrase in lowered for phrase in _EXPLICIT_BOOKING_PHRASES):
        return True

    words = set(re.findall(r"\b\w+\b", lowered))
    if any(term in words for term in ("appointment", "appointments", "reschedule", "rescheduling")):
        return True

    if any(term in words for term in ("book", "booking", "meet", "meeting", "schedule", "scheduling", "consultation")):
        return True

    return False


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


def _build_system_prompt(
    business_name: str,
    business_description: str,
    contact_email: str | None,
    knowledge_records: list[dict],
    web_results: list[dict] | None = None,
    customer_name: str | None = None,
) -> str:
    clean_name = customer_name.strip() if (customer_name and isinstance(customer_name, str) and customer_name.strip()) else None
    prompt_lines = [
        f"You are the intelligent AI assistant for {business_name}.",
        "You have two core capabilities:",
        f"1. Company Assistant: You answer questions about {business_name}'s services, expertise, FAQs, and general business information based on verified facts.",
        "2. General Knowledge & Technical Assistant: You are a highly capable assistant that answers questions about programming, science, mathematics, technology, education, writing, and general knowledge clearly, accurately, and step-by-step.",
        "",
        "CRITICAL RULES FOR BUSINESS INQUIRIES:",
        f"- When answering questions specific to {business_name} (such as services, pricing, company background, business hours, contact info, or policies), you MUST rely ONLY on the verified business information provided below.",
        "- Do NOT hallucinate, invent, or assume any company facts, prices, contact phone numbers, or unverified services.",
        f"- If a user asks a specific question about {business_name} that is NOT covered in the verified business information, clearly state that you do not have confirmed information about that and suggest contacting the team{f' at {contact_email}' if contact_email else ''}.",
        "- You cannot book, modify, or confirm appointments directly in chat. Always direct users to use the appointment booking form.",
        "",
        "RULES FOR GENERAL & TECHNICAL QUESTIONS:",
        "- When asked general questions about programming, algorithms, debugging, math, science, history, writing, or technology that are unrelated to the company's internal operations, answer directly, helpfully, and accurately.",
        "- Format responses using clean GitHub-flavored Markdown: use fenced code blocks with language tags for code snippets, bullet points or numbered lists for steps, and bold text for key terms.",
        "",
        "VERIFIED BUSINESS INFORMATION:",
        f"- Business Name: {business_name}",
    ]
    if clean_name:
        prompt_lines.append(f"- Authenticated Customer: {clean_name}")
        prompt_lines.append(f"- Greet {clean_name} politely if they say hello. Do not unnaturally repeat their name in every response.")
    else:
        prompt_lines.append("- If greeting a visitor without an authenticated account, use a polite, neutral greeting.")

    if business_description:
        prompt_lines.append(f"- Business Overview: {business_description}")
    if contact_email:
        prompt_lines.append(f"- Contact Email: {contact_email}")

    if knowledge_records:
        prompt_lines.append("")
        prompt_lines.append(f"PUBLISHED KNOWLEDGE RECORDS FOR {business_name}:")
        for rec in knowledge_records[:5]:
            title = rec.get("title", "")
            content = rec.get("content", "")
            prompt_lines.append(f"• {title}: {content}")

    if web_results:
        prompt_lines.append("")
        prompt_lines.append("SUPPLEMENTAL WEB SEARCH RESULTS (Free public reference):")
        for wr in web_results[:2]:
            prompt_lines.append(f"• {wr.get('title')}: {wr.get('snippet')} (Source: {wr.get('url')})")

    return "\n".join(prompt_lines)


def _format_conversation_messages(message: str, history: list[dict] | None) -> list[dict]:
    formatted = []
    if history:
        for item in history[-6:]:
            role = item.get("role", "")
            c = (item.get("content") or "").strip()
            if not c:
                continue
            mapped_role = "assistant" if role in {"agent", "assistant", "model"} else "user"
            formatted.append({"role": mapped_role, "content": c})

    # Ensure the last message represents the user's current query
    if not formatted or formatted[-1].get("role") != "user":
        formatted.append({"role": "user", "content": message.strip()})
    return formatted


def _format_citation(item: dict) -> str:
    title = item.get("title", "")
    url = item.get("source_url") or item.get("url")
    if url and isinstance(url, str) and url.startswith("http"):
        return f"{title} ({url})" if title else url
    return title


OFFICIAL_BLACK_INTEL_CONTACT_EMAIL = "abhishek.managerr@gmail.com"
PLACEHOLDER_CONTACT_EMAILS = {"admin@blackintel.com"}


def _resolve_contact_email(profile: dict) -> str | None:
    """Resolve a verified public contact email, avoiding placeholder demo addresses and cross-tenant leakage."""
    raw_email = (profile.get("contact_email") or "").strip()
    business_name = (profile.get("name") or "").strip()
    is_black_intel = "black intel" in business_name.lower() or not business_name

    if raw_email in PLACEHOLDER_CONTACT_EMAILS:
        # Never expose the demo operator placeholder email as a public contact
        return OFFICIAL_BLACK_INTEL_CONTACT_EMAIL if is_black_intel else None

    if raw_email:
        # Preserve genuine tenant-specific configured contact email
        return raw_email

    # If missing and this is Black Intel, fall back to the verified official email
    if is_black_intel:
        return OFFICIAL_BLACK_INTEL_CONTACT_EMAIL

    return None


def _local_fallback_response(tenant_id: str, context: list[dict], profile: dict, intent: str) -> dict:
    if context:
        source = context[0]
        answer = source["content"].strip()
        if len(answer) > 600:
            answer = answer[:597].rstrip() + "..."
        citation = _format_citation(source)
        return {"answer": answer, "citations": [citation] if citation else [], "intent": intent, "provider": "local"}

    contact = _resolve_contact_email(profile)
    fallback = "I do not have confirmed information about that."
    if contact:
        fallback += f" Please contact the team at {contact}."
    return {"answer": fallback, "citations": [], "intent": intent, "provider": "local"}


def respond(
    tenant_id: str,
    message: str,
    history: list[dict] | None = None,
    customer_name: str | None = None,
) -> dict:
    """Intelligent response generator supporting both general-purpose AI and grounded business Q&A."""
    profile = current_app.extensions["mongo_db"].business_profiles.find_one({"tenant_id": object_id(tenant_id)}) or {}
    business_name = profile.get("name") or "Black Intel"
    business_desc = profile.get("description") or ""
    contact_email = _resolve_contact_email(profile)

    context = _context_from_history(tenant_id, message, history)
    lowered = message.lower()
    intent = "general"
    if is_appointment_intent(message):
        intent = "appointment"
    elif any(phrase in lowered for phrase in ("request a quote", "get a quote", "callback", "contact", "call me", "interested in")):
        intent = "lead"

    if is_hours_question(message):
        hours = format_confirmed_hours(tenant_id)
        if hours:
            return {"answer": hours, "citations": ["Business hours"], "intent": intent, "provider": "local"}

    clean_name = customer_name.strip() if (customer_name and isinstance(customer_name, str) and customer_name.strip()) else None

    if intent == "appointment":
        if clean_name:
            guidance = (
                f"I cannot book, reschedule, or confirm an appointment directly from this chat, {clean_name}. "
                "Please use the appointment booking form on this page to select your preferred date and time, and confirm your appointment there."
            )
        else:
            guidance = BOOKING_GUIDANCE
        return {"answer": guidance, "citations": [], "intent": intent, "provider": "local"}

    if _is_greeting(message):
        greeting = (
            f"Hello {clean_name}. I can help with {business_name}'s approved services, FAQs, or appointment booking."
            if clean_name
            else f"Hello. I can help with {business_name}'s approved services, FAQs, or appointment booking."
        )
        return {
            "answer": greeting,
            "citations": [],
            "intent": intent,
            "provider": "local",
        }

    provider_config = str(current_app.config.get("LLM_PROVIDER") or "local").lower().strip()

    # When in local mode, strictly use the local deterministic engine
    if provider_config in {"local", "none", ""}:
        return _local_fallback_response(tenant_id, context, profile, intent)

    # Optional web search augmentation (disabled by default)
    web_results = []
    if is_web_search_enabled():
        web_results = search_web(message, limit=2)

    system_prompt = _build_system_prompt(
        business_name=business_name,
        business_description=business_desc,
        contact_email=contact_email,
        knowledge_records=context,
        web_results=web_results,
        customer_name=customer_name,
    )
    messages = _format_conversation_messages(message, history)

    ai_answer, provider_used, err = generate_ai_completion(system_prompt, messages)

    if ai_answer:
        citations = [_format_citation(item) for item in context if item.get("title") or item.get("source_url")]
        if web_results:
            for wr in web_results:
                wr_cite = _format_citation(wr) if (wr.get("title") or wr.get("url")) else ""
                if wr_cite and wr_cite not in citations:
                    citations.append(wr_cite)
        return {
            "answer": ai_answer,
            "citations": citations,
            "intent": intent,
            "provider": provider_used or "ai",
        }

    # Safe fallback if AI provider call fails or rate-limits: use local deterministic engine
    logger.info("AI completion unavailable (%s). Falling back to local response.", err)
    return _local_fallback_response(tenant_id, context, profile, intent)
