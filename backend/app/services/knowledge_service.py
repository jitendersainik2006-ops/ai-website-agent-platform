import re

from flask import current_app

from app.services.common import object_id, serialize

STOPWORDS = {
    "a", "an", "and", "are", "about", "at", "be", "can", "do", "for", "from", "how",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "our", "please", "tell", "the",
    "to", "us", "what", "when", "where", "which", "who", "with", "you", "your",
}
PRICE_TERMS = {"price", "pricing", "cost", "costs", "fee", "fees", "rate", "rates", "quote", "quotes"}
SERVICE_TERMS = {"service", "services", "offering", "offerings", "provide", "provides", "provided", "consulting"}


def _words(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[a-zA-Z0-9]+", text) if len(word) > 2}


def _meaningful_words(text: str) -> set[str]:
    return _words(text) - STOPWORDS - SERVICE_TERMS - PRICE_TERMS


def _source_terms(source: dict) -> set[str]:
    return _words(f"{source['title']} {source['content']}")


def _published_sources(tenant_id: str) -> list[dict]:
    db = current_app.extensions["mongo_db"]
    tenant = object_id(tenant_id)
    sources = []
    profile = db.business_profiles.find_one({"tenant_id": tenant})
    if profile and profile.get("description"):
        sources.append({"kind": "profile", "title": "Company profile", "content": profile["description"]})
    for service in db.services.find({"tenant_id": tenant, "status": "published"}):
        sources.append({"kind": "service", "title": service["title"], "content": service.get("description", "")})
    for faq in db.faqs.find({"tenant_id": tenant, "status": "published"}):
        sources.append({"kind": "faq", "title": faq["question"], "content": faq["answer"]})
    for item in db.knowledge.find({"tenant_id": tenant, "status": "published"}):
        sources.append({"kind": "knowledge", "title": item["title"], "content": item["content"]})
    return sources


def retrieve(tenant_id: str, question: str, limit: int = 4) -> list[dict]:
    """Return only sufficiently relevant, published content for one tenant."""
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
        if service_question and source["kind"] in {"service", "faq"}:
            if meaningful & _words(source["title"]):
                score += 2
            elif not meaningful:
                score += 1
        if pricing_question and source_words & PRICE_TERMS:
            score += 2
        if score >= (2 if meaningful else 1):
            ranked.append({**source, "score": score})

    ranked.sort(key=lambda item: (item["score"], item["kind"] == "faq"), reverse=True)
    return [serialize(item) for item in ranked[:limit]]
