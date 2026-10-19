import json
import logging
import re
import urllib.error
import urllib.request
from flask import current_app

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GROQ_API_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


def _sanitize_text(text: str) -> str:
    """Strip potential secret tokens, keys, or bearer tokens from strings before logging."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r"key=[a-zA-Z0-9_\-]+", "key=[REDACTED]", text)
    text = re.sub(r"Bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [REDACTED]", text, flags=re.IGNORECASE)
    return text


def _truncate_input(text: str, max_chars: int = 4000) -> str:
    if not isinstance(text, str):
        return ""
    return text[:max_chars].strip()


def call_gemini(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    timeout: int = 10,
) -> str:
    """Call Google Gemini generateContent REST API using Python standard library."""
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")

    model_name = model or "gemini-2.0-flash"
    url = f"{GEMINI_API_BASE}/{model_name}:generateContent?key={api_key}"

    # Build Gemini-formatted contents
    contents = []
    for msg in messages:
        role = "model" if msg.get("role") in {"agent", "assistant", "model"} else "user"
        content = _truncate_input(msg.get("content", ""))
        if content:
            contents.append({"role": role, "parts": [{"text": content}]})

    if not contents:
        raise ValueError("No message content provided for generation.")

    payload = {
        "system_instruction": {
            "parts": [{"text": _truncate_input(system_prompt, max_chars=8000)}]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1024,
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"Gemini API returned status {response.status}")
            data = json.loads(response.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("No candidates returned from Gemini API.")
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts or "text" not in parts[0]:
                raise RuntimeError("Empty response structure from Gemini API.")
            return str(parts[0]["text"]).strip()
    except urllib.error.HTTPError as exc:
        sanitized_url = _sanitize_text(url)
        raise RuntimeError(f"Gemini HTTP {exc.code} calling {sanitized_url}") from exc
    except Exception as exc:
        raise RuntimeError(f"Gemini call failed: {_sanitize_text(str(exc))}") from exc


def call_groq(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    timeout: int = 10,
) -> str:
    """Call Groq OpenAI-compatible chat completions REST API using standard library."""
    return call_openai_compatible(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
        model=model or "llama-3.3-70b-versatile",
        system_prompt=system_prompt,
        messages=messages,
        timeout=timeout,
    )


def call_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    timeout: int = 10,
) -> str:
    """Generic OpenAI-compatible chat completion caller."""
    if not api_key:
        raise ValueError("API key is required for external chat completion provider.")

    clean_base = (base_url or "https://api.groq.com/openai/v1").rstrip("/")
    endpoint = f"{clean_base}/chat/completions"

    formatted_messages = [
        {"role": "system", "content": _truncate_input(system_prompt, max_chars=8000)}
    ]
    for msg in messages:
        role = "assistant" if msg.get("role") in {"agent", "assistant", "model"} else "user"
        content = _truncate_input(msg.get("content", ""))
        if content:
            formatted_messages.append({"role": role, "content": content})

    payload = {
        "model": model or "llama-3.3-70b-versatile",
        "messages": formatted_messages,
        "temperature": 0.7,
        "max_tokens": 1024,
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"Provider API returned status {response.status}")
            data = json.loads(response.read().decode("utf-8"))
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("No choices returned from provider API.")
            content = choices[0].get("message", {}).get("content", "")
            return str(content).strip()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Provider HTTP {exc.code} calling {endpoint}") from exc
    except Exception as exc:
        raise RuntimeError(f"Provider call failed: {_sanitize_text(str(exc))}") from exc


def generate_ai_completion(
    system_prompt: str,
    messages: list[dict],
) -> tuple[str | None, str | None, str | None]:
    """Execute AI completion using configured provider.

    Returns:
        (generated_text, provider_name, error_reason)
    """
    config = current_app.config
    provider = str(config.get("LLM_PROVIDER") or "local").lower().strip()
    gemini_key = str(config.get("GEMINI_API_KEY") or "").strip()
    groq_key = str(config.get("GROQ_API_KEY") or "").strip()
    openai_key = str(config.get("OPENAI_COMPATIBLE_API_KEY") or "").strip()
    timeout = int(config.get("LLM_REQUEST_TIMEOUT_SECONDS") or 10)

    # Resolve active provider
    active_provider = None
    if provider == "gemini" and gemini_key:
        active_provider = "gemini"
    elif provider == "groq" and groq_key:
        active_provider = "groq"
    elif provider == "openai_compatible" and openai_key:
        active_provider = "openai_compatible"
    elif provider in {"auto", "local", ""}:
        # Auto-detect if a key is present and not explicitly set to local
        if provider != "local":
            if gemini_key:
                active_provider = "gemini"
            elif groq_key:
                active_provider = "groq"
            elif openai_key:
                active_provider = "openai_compatible"

    if not active_provider:
        return None, None, "Local mode (no external provider configured)"

    try:
        if active_provider == "gemini":
            model = config.get("GEMINI_MODEL") or "gemini-2.0-flash"
            text = call_gemini(gemini_key, model, system_prompt, messages, timeout=timeout)
            return text, "gemini", None
        elif active_provider == "groq":
            model = config.get("GROQ_MODEL") or "llama-3.3-70b-versatile"
            text = call_groq(groq_key, model, system_prompt, messages, timeout=timeout)
            return text, "groq", None
        elif active_provider == "openai_compatible":
            base_url = config.get("OPENAI_COMPATIBLE_BASE_URL") or "https://api.groq.com/openai/v1"
            model = config.get("OPENAI_COMPATIBLE_MODEL") or "llama-3.3-70b-versatile"
            text = call_openai_compatible(base_url, openai_key, model, system_prompt, messages, timeout=timeout)
            return text, "openai_compatible", None
    except Exception as exc:
        safe_msg = _sanitize_text(str(exc))
        logger.warning("AI provider %s failed gracefully: %s", active_provider, safe_msg)
        return None, None, safe_msg

    return None, None, "Unsupported provider"
