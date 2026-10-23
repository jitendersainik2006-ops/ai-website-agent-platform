import logging
import re
from flask import current_app

from app.services.common import object_id
from app.services.business_hours_service import format_confirmed_hours, is_hours_question
from app.services.knowledge_service import retrieve
from app.services.general_knowledge import search_general_knowledge, synthesize_code_response
from app.services.ai_provider import generate_ai_completion, is_valid_gemini_api_key
from app.services.web_search_service import search_web, is_web_search_enabled

logger = logging.getLogger(__name__)

BOOKING_GUIDANCE = (
    "I cannot book, reschedule, or confirm an appointment from this chat, and I will not invent available times. "
    "Please use the appointment booking form to choose a date and an available time, then confirm it there."
)

GREETING_MESSAGES = {
    "hello", "hi", "hey", "good morning", "good afternoon", "good evening", "hey there", "hello there",
    "namaste", "pranam", "kese ho", "kaise ho", "kya haal hai", "kya haal",
}

_HINGLISH_WORDS = {
    "mera", "meri", "naam", "hai", "hain", "kya", "kaise", "kahan", "kab", "kyun",
    "aap", "aapka", "aapki", "hum", "main", "mujhe", "batao", "madad", "swagat",
    "namaste", "dhanyawad", "theek", "shukriya", "karo", "karein", "ho", "hoga",
    "sewa", "suvidha", "kaam", "paisa", "keemat",
}

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

OFFICIAL_BLACK_INTEL_CONTACT_EMAIL = "abhishek.managerr@gmail.com"
PLACEHOLDER_CONTACT_EMAILS = {"admin@blackintel.com"}


def _is_hinglish(message: str) -> bool:
    tokens = {w.lower() for w in re.findall(r"[a-zA-Z]+", message.lower())}
    return bool(tokens & _HINGLISH_WORDS)


def _detect_introduced_name(message: str) -> str | None:
    """Detect if the user introduced their name in English or Hindi/Hinglish."""
    text = message.strip()
    # Hindi/Hinglish pattern: "Mera naam Rahul hai", "Mera naam Rahul"
    m_hi = re.search(r"\bmera\s+naam\s+([A-Za-z]+)(?:\s+hai)?\b", text, re.IGNORECASE)
    if m_hi:
        name = m_hi.group(1).strip().capitalize()
        if name.lower() not in {"black", "intel", "kya", "bhai", "hai"}:
            return name

    # English pattern: "My name is Alice", "I am Alice", "I'm Alice", "Call me Alice"
    m_en = re.search(r"\b(?:my\s+name\s+is|i\s+am|i'm|call\s+me)\s+([A-Za-z]+)\b", text, re.IGNORECASE)
    if m_en:
        name = m_en.group(1).strip().capitalize()
        if name.lower() not in {"interested", "looking", "booking", "scheduling", "a", "an", "the"}:
            return name

    return None


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
    if _detect_introduced_name(message):
        return True
    return " " not in normalized and any(_one_edit_away(normalized, greeting) for greeting in ("hello", "hi", "hey"))


def is_appointment_intent(message: str) -> bool:
    """Disambiguate true appointment requests from technical or general language."""
    lowered = message.lower()
    if any(marker in lowered for marker in _TECH_ACADEMIC_MARKERS):
        return any(phrase in lowered for phrase in _EXPLICIT_BOOKING_PHRASES)

    if any(phrase in lowered for phrase in _EXPLICIT_BOOKING_PHRASES):
        return True

    words = set(re.findall(r"\b\w+\b", lowered))
    if any(term in words for term in ("appointment", "appointments", "reschedule", "rescheduling")):
        return True

    if any(term in words for term in ("book", "booking", "meet", "meeting", "schedule", "scheduling", "consultation")):
        return True

    return False


_CANONICAL_QUERY_MAP = {
    "what services does black intel of": "What services does Black Intel offer?",
    "what services does black intel off": "What services does Black Intel offer?",
    "what services does black intel offe": "What services does Black Intel offer?",
    "what does black intel d": "What does Black Intel do?",
    "how can i book a consult": "How can I book a consultation?",
    "how can i request a consult": "How can I request a consultation?",
    "how to book a consult": "How can I book a consultation?",
}


def _canonicalize_query(message: str) -> str:
    cleaned = message.strip()
    lowered = cleaned.lower()
    if lowered in _CANONICAL_QUERY_MAP:
        return _CANONICAL_QUERY_MAP[lowered]
    return cleaned


_CAPABILITY_PHRASES_HI = (
    "kya kar sakte ho", "kya kar sakte hain", "kya kya kar sakte ho", "kya kya kar sakte hain",
    "kya madad kar sakte", "kya kaam karte", "kya kaam kar sakte", "kya services hai",
    "kya service hai", "kya suvidha hai", "tum kya karte", "aap kya karte", "tum kya ho",
    "aap kya ho", "madad kaise kar sakte", "kya feature hai",
)

_CAPABILITY_PHRASES_EN = (
    "what can you do", "what are your capabilities", "what capabilities do you have",
    "what can this bot do", "what can you help me with", "how can you help me",
    "how can you help", "how can you assist", "what are your features",
    "what do you do", "what are you capable of", "tell me what you can do",
)


def _is_capabilities_query(message: str) -> tuple[bool, bool]:
    lowered = " ".join(message.lower().split())
    clean = re.sub(r"[^\w\s]", "", lowered)
    for p in _CAPABILITY_PHRASES_HI:
        if p in clean:
            return True, True
    for p in _CAPABILITY_PHRASES_EN:
        if p in clean:
            return True, False
    return False, False


def _build_capabilities_response(business_name: str, is_hinglish: bool) -> str:
    if is_hinglish:
        return (
            f"Main {business_name} ka AI Assistant hoon. Main aapki in mukhya cheezon mein madad kar sakta hoon:\n\n"
            "1. **Cybersecurity & Digital Forensics:** Black Intel ki verified services jaise Cyber Offense Command, "
            "Digital Investigations, Forensic Truth Extraction, aur Incident Response ke baare mein confirmed jaankari dena.\n"
            "2. **Consultation Scheduling:** Monday se Friday (09:00–17:00 IST) ke liye consultation availability check karna "
            "aur official booking form ke zariye 30-minute appointment confirm karne mein guide karna.\n"
            "3. **Client Workspace Support:** Authenticated clients ke dashboard access, case inquiries, aur meeting records mein sahayata karna.\n"
            "4. **General Technical & Programming Reference:** Python code solutions (jaise math functions, string operations, algorithms) "
            "aur science, mathematics, aur computer science ke verified concepts explain karna.\n\n"
            "Aap mujhse hamari services, consultation booking, ya technical sawaalon ke baare mein poochh sakte hain!"
        )
    return (
        f"I am the {business_name} AI Assistant. Here are the core areas I can assist you with:\n\n"
        f"1. **Cybersecurity & Forensics Expertise:** Provide verified, grounded information about {business_name}'s "
        "divisions, including Cyber Offense Command, Cybercrime & Digital Investigations, Forensic Truth Extraction & Recovery, and Incident Response.\n"
        "2. **Consultation Scheduling:** Guide you to check availability and book a 30-minute consultation during operational hours "
        "(Monday–Friday, 09:00–17:00 IST) using our official appointment form.\n"
        "3. **Client Workspace Support:** Assist registered clients with account access, past appointments, and case consultations.\n"
        "4. **General Technical & Programming Help:** Provide clean, runnable Python code implementations and explain verified "
        "concepts in computer science, mathematics, and science from our reference library.\n\n"
        "How can I assist you with your security or technical inquiry today?"
    )


def _dedupe_citations(citations: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for c in citations:
        c_clean = c.strip() if isinstance(c, str) else ""
        if c_clean and c_clean not in seen:
            seen.add(c_clean)
            deduped.append(c_clean)
    return deduped


def _context_from_history(tenant_id: str, message: str, history: list[dict] | None) -> list[dict]:
    # 1. Direct retrieval on the current message
    context = retrieve(tenant_id, message)
    if context:
        return context

    if not history:
        return []

    # 2. Follow-up context from previous turns
    past_messages = [
        item for item in history
        if not (item.get("content", "").strip() == message.strip() and item.get("role") in {"visitor", "customer", "user"})
    ]
    if not past_messages:
        return []

    prior_user_msgs = [
        item.get("content", "").strip() for item in past_messages
        if item.get("role") in {"visitor", "customer", "user"} and isinstance(item.get("content"), str) and item.get("content").strip()
    ]
    prior_agent_msgs = [
        item.get("content", "").strip() for item in past_messages
        if item.get("role") in {"agent", "assistant", "model"} and isinstance(item.get("content"), str) and item.get("content").strip()
    ]

    # Combine prior user query with current follow-up (e.g. "Tell me more about it")
    if prior_user_msgs:
        combined = f"{prior_user_msgs[-1]} {message}"
        ctx = retrieve(tenant_id, combined)
        if ctx:
            return ctx

    # Check lead terms from prior agent answer
    if prior_agent_msgs:
        ctx = retrieve(tenant_id, f"{prior_agent_msgs[-1][:120]} {message}")
        if ctx:
            return ctx

    return []


def _format_citation(item: dict) -> str:
    title = item.get("title", "")
    url = item.get("source_url") or item.get("url")
    if url and isinstance(url, str) and url.startswith("http"):
        return f"{title} ({url})" if title else url
    return title


def _resolve_contact_email(profile: dict) -> str | None:
    """Resolve a verified public contact email, avoiding placeholder demo addresses and cross-tenant leakage."""
    raw_email = (profile.get("contact_email") or "").strip()
    business_name = (profile.get("name") or "").strip()
    is_black_intel = "black intel" in business_name.lower() or not business_name

    if raw_email in PLACEHOLDER_CONTACT_EMAILS:
        return OFFICIAL_BLACK_INTEL_CONTACT_EMAIL if is_black_intel else None

    if raw_email:
        return raw_email

    if is_black_intel:
        return OFFICIAL_BLACK_INTEL_CONTACT_EMAIL

    return None


_TECH_OR_CODE_TOKENS = {
    "py", "python", "code", "coding", "coder", "script", "scripts", "scripting",
    "program", "programs", "programming", "programmer",
    "javascript", "js", "typescript", "ts", "java", "cpp", "c++", "csharp", "c#",
    "golang", "go", "rust", "ruby", "php", "swift", "kotlin", "bash", "shell", "powershell",
    "html", "css", "sql", "nosql", "database", "databases", "mongodb", "postgres", "mysql", "sqlite", "redis",
    "function", "functions", "def", "class", "classes", "loop", "loops", "array", "arrays",
    "list", "lists", "dict", "dictionary", "tuple", "set", "algorithm", "algorithms",
    "recursion", "variable", "variables", "constant", "pointer", "async", "await",
    "api", "apis", "rest", "endpoint", "endpoints", "json", "xml", "yaml", "http", "https",
    "debug", "debugging", "bug", "bugs", "exception", "exceptions", "syntax", "compiler", "runtime",
    "git", "github", "docker", "container", "containers", "kubernetes", "k8s",
    "linux", "ubuntu", "terminal", "cli",
    "math", "mathematics", "algebra", "calculus", "geometry", "physics", "chemistry", "biology",
    "photosynthesis", "science", "formula", "equation", "prime", "pythagorean", "dna",
    "thermodynamics", "solar", "planets", "continents", "oceans",
}


def _is_general_technical_query(message: str) -> bool:
    lowered = message.lower()
    words = set(re.findall(r"[a-z0-9_+#]+", lowered))
    if words & _TECH_OR_CODE_TOKENS:
        return True
    phrases = (
        "write code", "py code", "python code", "sample code", "example code",
        "program to", "write a program", "write a function", "how to code",
        "how to program", "how to write", "code do", "code snippet",
    )
    return any(phrase in lowered for phrase in phrases)


def _local_fallback_response(tenant_id: str, context: list[dict], profile: dict, intent: str, message: str = "") -> dict:
    """Deterministic local response generator supporting company knowledge, coding synthesis, and honest technical diagnostics."""
    # 1. Company knowledge context match
    if context:
        source = context[0]
        answer = source["content"].strip()
        if len(answer) > 600:
            answer = answer[:597].rstrip() + "..."
        citation = _format_citation(source)
        return {"answer": answer, "citations": [citation] if citation else [], "intent": intent, "provider": "local"}

    business_name = profile.get("name") or "Black Intel"

    # 2. General Technical / Programming query without company context
    if message and _is_general_technical_query(message):
        code_sol = synthesize_code_response(message)
        gen_rec = search_general_knowledge(message, limit=1)

        if code_sol:
            return {
                "answer": code_sol,
                "citations": ["Python 3 Standard Documentation"],
                "intent": intent,
                "provider": "local",
            }
        elif gen_rec:
            top_r = gen_rec[0]
            answer = f"**{top_r['topic']}**\n\n{top_r['content']}"
            return {
                "answer": answer,
                "citations": [top_r.get("source", "Reference Library")],
                "intent": intent,
                "provider": "local",
            }
        else:
            diagnostic_text = (
                f"I do not have a verified reference for that specific technical topic in local mode. "
                f"I can assist with {business_name}'s cybersecurity services, digital forensics, "
                f"consultation scheduling, or programming topics in our reference library."
            )
            return {
                "answer": diagnostic_text,
                "citations": [],
                "intent": intent,
                "provider": "local",
            }

    # 3. Respectful tenant contact fallback for general / unknown business inquiries
    contact = _resolve_contact_email(profile)
    fallback = "I do not have confirmed information about that."
    if contact:
        fallback += f" Please contact the team at {contact}."
    return {"answer": fallback, "citations": [], "intent": intent, "provider": "local"}


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
        for rec in knowledge_records[:6]:
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

    if not formatted or formatted[-1].get("role") != "user":
        formatted.append({"role": "user", "content": message.strip()})
    return formatted


def respond(
    tenant_id: str,
    message: str,
    history: list[dict] | None = None,
    customer_name: str | None = None,
) -> dict:
    """Intelligent response generator supporting company knowledge, general knowledge, code synthesis, and AI completions."""
    message = _canonicalize_query(message)
    profile = current_app.extensions["mongo_db"].business_profiles.find_one({"tenant_id": object_id(tenant_id)}) or {}
    business_name = profile.get("name") or "Black Intel"
    business_desc = profile.get("description") or ""
    contact_email = _resolve_contact_email(profile)

    context = _context_from_history(tenant_id, message, history)
    lowered = message.lower().strip()
    intent = "general"
    if is_appointment_intent(message):
        intent = "appointment"
    elif any(phrase in lowered for phrase in ("request a quote", "get a quote", "callback", "contact", "call me", "interested in")):
        intent = "lead"

    # 1. Business Hours
    if is_hours_question(message):
        hours = format_confirmed_hours(tenant_id)
        if hours:
            return {"answer": hours, "citations": ["Business hours"], "intent": intent, "provider": "local"}

    # 2. Personalization & Name Detection
    introduced_name = _detect_introduced_name(message)
    active_name = customer_name or introduced_name
    clean_name = active_name.strip() if (active_name and isinstance(active_name, str) and active_name.strip()) else None

    # 3. Appointment Guidance
    if intent == "appointment":
        if clean_name:
            guidance = (
                f"I cannot book, reschedule, or confirm an appointment directly from this chat, {clean_name}. "
                "Please use the appointment booking form on this page to select your preferred date and time, and confirm your appointment there."
            )
        else:
            guidance = BOOKING_GUIDANCE
        return {"answer": guidance, "citations": [], "intent": intent, "provider": "local"}

    # 4. Capabilities Query (e.g. "tum kya kya kar sakte ho?", "what can you do?")
    is_cap, is_cap_hi = _is_capabilities_query(message)
    if is_cap:
        return {
            "answer": _build_capabilities_response(business_name, is_cap_hi),
            "citations": [],
            "intent": "general",
            "provider": "local",
        }

    # 5. Greetings and Introductions
    if _is_greeting(message):
        lowered_msg = message.lower().strip()
        is_hi = _is_hinglish(message) or any(w in lowered_msg for w in ("namaste", "pranam", "namaskar", "kese ho", "kaise ho"))
        if is_hi:
            name_to_use = clean_name or introduced_name
            if name_to_use:
                greeting = f"Namaste {name_to_use}! Black Intel mein aapka swagat hai. Main aapki kya madad kar sakta hoon?"
            else:
                greeting = f"Namaste! Black Intel mein aapka swagat hai. Main aapki kya madad kar sakta hoon?"
            return {"answer": greeting, "citations": [], "intent": intent, "provider": "local"}

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

    # 6. Check AI Provider Configuration
    provider_config = str(current_app.config.get("LLM_PROVIDER") or "local").lower().strip()
    gemini_key = current_app.config.get("GEMINI_API_KEY")
    groq_key = current_app.config.get("GROQ_API_KEY")
    openai_key = current_app.config.get("OPENAI_COMPATIBLE_API_KEY")
    has_key = bool(
        is_valid_gemini_api_key(gemini_key)
        or groq_key
        or openai_key
    )

    # When explicitly disabled with "none", or in local mode without any API key or local model, use local engine
    is_local_llm = provider_config in {"ollama", "local_llm"}
    if provider_config in {"none"} or (provider_config == "local" and not has_key and not is_local_llm):
        return _local_fallback_response(tenant_id, context, profile, intent, message=message)

    # Optional web search augmentation
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
        raw_citations = [_format_citation(item) for item in context if item.get("title") or item.get("source_url")]
        if web_results:
            for wr in web_results:
                wr_cite = _format_citation(wr) if (wr.get("title") or wr.get("url")) else ""
                if wr_cite:
                    raw_citations.append(wr_cite)
        return {
            "answer": ai_answer,
            "citations": _dedupe_citations(raw_citations),
            "intent": intent,
            "provider": provider_used or "ai",
        }

    # Safe fallback if AI provider call fails or rate-limits: use local response generator
    logger.info("AI completion unavailable (%s). Falling back to local response.", err)
    return _local_fallback_response(tenant_id, context, profile, intent, message=message)
