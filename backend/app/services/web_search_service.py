import json
import logging
import urllib.parse
import urllib.request
from flask import current_app

logger = logging.getLogger(__name__)


def is_web_search_enabled() -> bool:
    try:
        return bool(current_app.config.get("WEB_SEARCH_ENABLED", False))
    except Exception:
        return False


def search_web(query: str, limit: int = 2) -> list[dict]:
    """Optional, disabled-by-default zero-cost web search using free open API.

    Returns structured results with source URLs. If disabled, times out, or fails,
    returns an empty list without affecting core response generation.
    """
    if not is_web_search_enabled():
        return []

    clean_query = query.strip()
    if not clean_query or len(clean_query) < 3:
        return []

    # Bounded query length
    encoded_query = urllib.parse.quote(clean_query[:200])
    # Wikipedia OpenSearch API is 100% free and requires no API key.
    url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={encoded_query}&limit={limit}&namespace=0&format=json"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BlackIntel-Assistant/1.0 (Website Agent Platform)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status != 200:
                return []
            payload = json.loads(response.read().decode("utf-8"))
            # Format: [query, [titles], [descriptions], [urls]]
            if not isinstance(payload, list) or len(payload) < 4:
                return []
            titles, descriptions, urls = payload[1], payload[2], payload[3]
            results = []
            for i in range(min(len(titles), limit)):
                title = titles[i] if i < len(titles) else ""
                snippet = descriptions[i] if i < len(descriptions) else ""
                link = urls[i] if i < len(urls) else ""
                if title and link:
                    results.append({"title": title, "snippet": snippet, "url": link})
            return results
    except Exception as exc:
        logger.warning("Optional web search failed gracefully: %s", type(exc).__name__)
        return []
