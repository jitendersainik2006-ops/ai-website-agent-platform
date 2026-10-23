import json
import logging
import re
import urllib.error
import urllib.request
from flask import current_app

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GROQ_API_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

# Whitelist of verified, active Google Gemini models for text generation.
# Unverified (e.g. gemini-3.8-pro), shut-down (e.g. gemini-2.0-flash), and restricted legacy
# models (e.g. gemini-1.5-flash, gemini-1.5-pro) are removed and automatically fall back
# to DEFAULT_GEMINI_MODEL (gemini-3.8-flash).
SUPPORTED_GEMINI_MODELS = {
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
}


def resolve_gemini_model(configured_model: str | None = None) -> str:
    """Resolve configured Gemini model to a currently supported model.

    Defaults to gemini-3.8-flash unless the configured model is explicitly valid.
    Shut-down, unverified, or restricted legacy models fall back to gemini-3.8-flash.
    """
    if not configured_model or not isinstance(configured_model, str):
        return DEFAULT_GEMINI_MODEL
    cleaned = configured_model.strip().lower()
    if cleaned.startswith("models/"):
        cleaned = cleaned[len("models/"):]
    if cleaned in SUPPORTED_GEMINI_MODELS:
        return cleaned
    return DEFAULT_GEMINI_MODEL


GEMINI_INTERACTIONS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GROQ_API_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


def validate_gemini_api_key(api_key: str | None) -> str:
    """Validate that the Gemini API key is configured and structurally usable.

    Accepts candidate authorization keys issued by Google AI Studio (including those
    starting with 'AQ.' or 'AIzaSy'). Does not falsely reject keys solely based on prefix.
    """
    if not api_key or not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("GEMINI_API_KEY is not configured.")
    clean = api_key.strip()
    if clean.lower().startswith("bearer "):
        clean = clean[7:].strip()
    if len(clean) < 8:
        raise ValueError("GEMINI_API_KEY is too short to be a valid API key.")
    return clean


def is_valid_gemini_api_key(api_key: str | None) -> bool:
    """Check if the key is structurally a candidate Gemini API key (not empty, min length)."""
    try:
        validate_gemini_api_key(api_key)
        return True
    except (ValueError, TypeError):
        return False


def _sanitize_text(text: str) -> str:
    """Strip potential secret tokens, keys, or bearer tokens from strings before logging."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r"key=[^\s&'\"]+", "key=[REDACTED]", text)
    text = re.sub(r"Bearer\s+[^\s&'\"]+", "Bearer [REDACTED]", text, flags=re.IGNORECASE)
    text = re.sub(r"x-goog-api-key:\s*[^\s,]+", "x-goog-api-key: [REDACTED]", text, flags=re.IGNORECASE)
    return text


def _truncate_input(text: str, max_chars: int = 4000) -> str:
    if not isinstance(text, str):
        return ""
    return text[:max_chars].strip()


def _extract_gemini_response_text(data: dict) -> str:
    """Extract text from either the official Interactions API or generateContent API response."""
    if not isinstance(data, dict):
        raise RuntimeError("Invalid response structure from Gemini API.")

    # 1. Direct output_text field from Interactions API
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()

    # 2. Official Interactions API steps format
    steps = data.get("steps", [])
    if isinstance(steps, list):
        model_texts = []
        for step in steps:
            if isinstance(step, dict) and step.get("type") in ("model_output", "output"):
                content = step.get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and "text" in item and item["text"]:
                            model_texts.append(item["text"].strip())
                        elif isinstance(item, str) and item.strip():
                            model_texts.append(item.strip())
                elif isinstance(content, str) and content.strip():
                    model_texts.append(content.strip())
        if model_texts:
            return "\n\n".join(model_texts).strip()

    # 3. Interactions API outputs array
    outputs = data.get("outputs", [])
    if isinstance(outputs, list):
        for out in outputs:
            if isinstance(out, dict):
                if isinstance(out.get("text"), str) and out["text"].strip():
                    return out["text"].strip()
                content = out.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content if isinstance(c, dict) and "text" in c]
                    combined = "\n".join(t for t in texts if t).strip()
                    if combined:
                        return combined

    # 4. Traditional generateContent candidates array
    candidates = data.get("candidates", [])
    if isinstance(candidates, list) and candidates:
        content = candidates[0].get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        if parts and isinstance(parts[0], dict) and "text" in parts[0]:
            return str(parts[0]["text"]).strip()

    raise RuntimeError("Empty response structure from Gemini API.")


def call_gemini(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    timeout: int = 10,
    is_retry: bool = False,
) -> str:
    """Call Google Gemini using the official Interactions REST API with x-goog-api-key header."""
    clean_key = validate_gemini_api_key(api_key)

    # Clean requested model. Normalize models/ prefix, reject shut-down model, default to DEFAULT_GEMINI_MODEL
    requested_model = (model or "").strip()
    if requested_model.lower().startswith("models/"):
        requested_model = requested_model[len("models/"):]

    if not requested_model or requested_model.lower() == "gemini-2.0-flash":
        model_name = DEFAULT_GEMINI_MODEL
    else:
        model_name = resolve_gemini_model(requested_model)

    # Build input prompt from conversation messages
    input_text = ""
    for msg in messages:
        role = "Assistant" if msg.get("role") in {"agent", "assistant", "model"} else "User"
        c = _truncate_input(msg.get("content", ""))
        if c:
            input_text += f"{role}: {c}\n"
    input_text = input_text.strip()
    if len(messages) == 1 and messages[0].get("role") in {"user", "visitor", "customer"}:
        input_text = _truncate_input(messages[0].get("content", ""))

    if not input_text:
        raise ValueError("No message content provided for generation.")

    payload = {
        "model": model_name,
        "input": input_text,
    }
    if system_prompt:
        payload["system_instruction"] = _truncate_input(system_prompt, max_chars=8000)

    req = urllib.request.Request(
        GEMINI_INTERACTIONS_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": clean_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"Gemini API returned status {response.status}")
            data = json.loads(response.read().decode("utf-8"))
            return _extract_gemini_response_text(data)
    except urllib.error.HTTPError as exc:
        sanitized_url = _sanitize_text(GEMINI_INTERACTIONS_ENDPOINT)
        # If a non-default model returned 404, retry at most once with DEFAULT_GEMINI_MODEL (gemini-3.8-flash)
        if exc.code == 404 and not is_retry and model_name != DEFAULT_GEMINI_MODEL:
            logger.info("Gemini model '%s' not found (404). Retrying with %s.", model_name, DEFAULT_GEMINI_MODEL)
            return call_gemini(clean_key, DEFAULT_GEMINI_MODEL, system_prompt, messages, timeout=timeout, is_retry=True)
        if exc.code in {400, 401, 403}:
            raise RuntimeError(f"Gemini authentication/credential error (HTTP {exc.code}) calling {sanitized_url}") from exc
        if exc.code == 429:
            raise RuntimeError(f"Gemini rate limit exceeded (HTTP 429) calling {sanitized_url}") from exc
        if exc.code == 503:
            raise RuntimeError(f"Gemini service unavailable (HTTP 503 - temporary high demand) calling {sanitized_url}") from exc
        raise RuntimeError(f"Gemini HTTP {exc.code} calling {sanitized_url}") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError) or "timed out" in str(exc.reason).lower():
            raise RuntimeError(f"Gemini request timed out after {timeout} seconds") from exc
        raise RuntimeError(f"Gemini connection error: {_sanitize_text(str(exc.reason))}") from exc
    except TimeoutError:
        raise RuntimeError(f"Gemini request timed out after {timeout} seconds")
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


def call_ollama(
    base_url: str | None,
    model: str | None,
    system_prompt: str,
    messages: list[dict],
    timeout: int = 15,
) -> str:
    """Call local Ollama runtime via its native /api/chat endpoint."""
    clean_base = (base_url or "http://localhost:11434").rstrip("/")
    endpoint = f"{clean_base}/api/chat"

    formatted_messages = []
    if system_prompt:
        formatted_messages.append({"role": "system", "content": _truncate_input(system_prompt, max_chars=8000)})
    for msg in messages:
        role = "assistant" if msg.get("role") in {"agent", "assistant", "model"} else "user"
        content = _truncate_input(msg.get("content", ""))
        if content:
            formatted_messages.append({"role": role, "content": content})

    payload = {
        "model": model or "qwen2.5:3b",
        "messages": formatted_messages,
        "stream": False,
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"Ollama returned HTTP status {response.status}")
            data = json.loads(response.read().decode("utf-8"))
            msg = data.get("message", {})
            content = msg.get("content", "")
            if content:
                return str(content).strip()
            raise RuntimeError("Empty message content returned from Ollama runtime.")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama local runtime connection error: {_sanitize_text(str(exc.reason))}") from exc
    except Exception as exc:
        raise RuntimeError(f"Ollama call failed: {_sanitize_text(str(exc))}") from exc


def generate_ai_completion(
    system_prompt: str,
    messages: list[dict],
) -> tuple[str | None, str | None, str | None]:
    """Execute AI completion using configured provider.

    Supports 'gemini', 'ollama' (local LLM), 'groq', 'openai_compatible', and 'local'.

    Returns:
        (generated_text, provider_name, error_reason)
    """
    config = current_app.config
    provider = str(config.get("LLM_PROVIDER") or "local").lower().strip()
    gemini_key = str(config.get("GEMINI_API_KEY") or "").strip()
    groq_key = str(config.get("GROQ_API_KEY") or "").strip()
    openai_key = str(config.get("OPENAI_COMPATIBLE_API_KEY") or "").strip()
    timeout = int(config.get("LLM_REQUEST_TIMEOUT_SECONDS") or 10)

    # When explicit local mode is set, never invoke external cloud LLMs
    if provider in {"local", "none"}:
        return None, "local", "Local-only mode active"

    # Resolve active provider
    active_provider = None
    if provider in {"ollama", "local_llm"}:
        active_provider = "ollama"
    elif provider == "gemini" and gemini_key:
        active_provider = "gemini"
    elif provider == "groq" and groq_key:
        active_provider = "groq"
    elif provider == "openai_compatible" and openai_key:
        active_provider = "openai_compatible"
    elif provider in {"auto", ""}:
        if is_valid_gemini_api_key(gemini_key):
            active_provider = "gemini"
        elif groq_key:
            active_provider = "groq"
        elif openai_key:
            active_provider = "openai_compatible"

    if not active_provider:
        return None, "local", "Local mode (no external provider configured)"

    try:
        if active_provider == "ollama":
            base_url = config.get("OLLAMA_BASE_URL") or "http://localhost:11434"
            model = config.get("OLLAMA_MODEL") or "qwen2.5:3b"
            text = call_ollama(base_url, model, system_prompt, messages, timeout=timeout)
            return text, "ollama", None
        elif active_provider == "gemini":
            try:
                clean_key = validate_gemini_api_key(gemini_key)
            except ValueError as val_err:
                logger.warning("Gemini credential validation failed: %s", _sanitize_text(str(val_err)))
                return None, "gemini", str(val_err)
            model = resolve_gemini_model(config.get("GEMINI_MODEL"))
            text = call_gemini(clean_key, model, system_prompt, messages, timeout=timeout)
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
        return None, active_provider, safe_msg

    return None, None, "Unsupported provider"
