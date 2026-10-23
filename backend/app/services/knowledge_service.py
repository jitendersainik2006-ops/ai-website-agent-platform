import re

from flask import current_app

from app.services.common import object_id, serialize

STOPWORDS = {
    "a", "an", "and", "are", "about", "at", "be", "can", "do", "for", "from", "how",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "our", "please", "tell", "the",
    "to", "us", "what", "when", "where", "which", "who", "with", "you", "your",
    # Hindi/Hinglish common stopwords
    "kya", "hai", "hain", "ka", "ki", "ke", "ko", "se", "mein", "par", "bhi", "aur",
}

PRICE_TERMS = {
    "price", "pricing", "cost", "costs", "fee", "fees", "rate", "rates", "quote", "quotes",
    "keemat", "charges", "charge",
}

SERVICE_TERMS = {
    "service", "services", "offering", "offerings", "provide", "provides", "provided", "consulting",
    "capabilities", "solutions", "suvidha", "sewayen", "kaam",
}

SYNONYMS = {
    "forensics": {"investigation", "digital", "evidence", "recovery", "cybercrime", "disk", "memory"},
    "cybercrime": {"crime", "fraud", "breach", "incident", "investigation"},
    "offense": {"penetration", "red", "team", "pentest", "hacking", "simulation", "apt"},
    "defense": {"defensive", "soc", "siem", "monitoring", "protection", "resilience"},
    "director": {"leadership", "founder", "aryan", "kumar", "bharti", "management", "team"},
    "contact": {"email", "phone", "whatsapp", "call", "reach", "support", "address"},
    "book": {"appointment", "consultation", "schedule", "slot"},
}


def _words(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[a-zA-Z0-9_+#]+", text) if len(word) > 2}


def _meaningful_words(text: str) -> set[str]:
    raw = _words(text)
    expanded = set(raw)
    for w in raw:
        if w in SYNONYMS:
            expanded.update(SYNONYMS[w])
    return expanded - STOPWORDS - SERVICE_TERMS - PRICE_TERMS


def _source_terms(source: dict) -> set[str]:
    return _words(f"{source.get('title', '')} {source.get('content', '')}")


def _published_sources(tenant_id: str) -> list[dict]:
    db = current_app.extensions["mongo_db"]
    tenant = object_id(tenant_id)
    sources = []
    profile = db.business_profiles.find_one({"tenant_id": tenant})
    if profile and profile.get("description"):
        sources.append({
            "kind": "profile",
            "title": "Company profile",
            "content": profile["description"],
            "source_url": profile.get("website") or "https://theblackintel.com/",
        })
    for service in db.services.find({"tenant_id": tenant, "status": "published"}):
        sources.append({
            "kind": "service",
            "title": service["title"],
            "content": service.get("description", ""),
            "source_url": service.get("source_url") or "https://theblackintel.com/services",
        })
    for faq in db.faqs.find({"tenant_id": tenant, "status": "published"}):
        sources.append({
            "kind": "faq",
            "title": faq["question"],
            "content": faq["answer"],
            "source_url": faq.get("source_url") or "https://theblackintel.com/contact",
        })
    for item in db.knowledge.find({"tenant_id": tenant, "status": "published"}):
        sources.append({
            "kind": "knowledge",
            "title": item["title"],
            "content": item["content"],
            "source_url": item.get("source_url") or "https://theblackintel.com/",
            "source_title": item.get("source_title"),
            "verified": item.get("verified", True),
        })
    return sources


def retrieve(tenant_id: str, question: str, limit: int = 4) -> list[dict]:
    """Return only sufficiently relevant, published content for one tenant with enhanced scoring."""
    question_words = _words(question)
    meaningful = _meaningful_words(question)
    pricing_question = bool(question_words & PRICE_TERMS)
    service_question = bool(question_words & SERVICE_TERMS) and not pricing_question
    ranked = []

    for source in _published_sources(tenant_id):
        source_words = _source_terms(source)
        if pricing_question and not (source_words & PRICE_TERMS):
            continue
        score = len(meaningful & source_words) * 3
        title_matches = len(meaningful & _words(source.get("title", "")))
        score += title_matches * 4

        # Bonus for exact phrase occurrence in content
        if question.strip().lower() in source.get("content", "").lower():
            score += 6

        if service_question and source["kind"] in {"service", "faq", "knowledge"}:
            if source["kind"] == "service" or (_words(source.get("title", "")) & SERVICE_TERMS):
                score += 2
            if title_matches > 0:
                score += 2
            elif not meaningful and (source["kind"] == "service" or (source_words & SERVICE_TERMS)):
                score += 1
        if pricing_question and source_words & PRICE_TERMS:
            score += 2
        if score >= (2 if meaningful else 1):
            ranked.append({**source, "score": score})

    ranked.sort(key=lambda item: (item["score"], item["kind"] == "faq"), reverse=True)
    return [serialize(item) for item in ranked[:limit]]
