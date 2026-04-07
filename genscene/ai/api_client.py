"""
ai/api_client.py — Zero-dependency LLM API client.

Uses only Python's stdlib urllib.request so no pip install is required inside
Blender's bundled Python environment.  Supports OpenAI, Anthropic, and Ollama
(local) via the provider setting in config.py.

Provider quick-reference:
  "openai"    — cloud, requires GENSCENE_API_KEY
  "anthropic" — cloud, requires GENSCENE_API_KEY
  "ollama"    — local, no key needed; Ollama must be running on OLLAMA_ENDPOINT
"""

from __future__ import annotations

import json as _json
import urllib.request
import urllib.error
from typing import Any

from .. import config


# ── Exceptions ────────────────────────────────────────────────────────────────

class APIError(RuntimeError):
    """Raised when the LLM API returns an error or an unexpected response."""


# ── Internal helpers ──────────────────────────────────────────────────────────

_TIMEOUT_SECONDS = 30  # long enough for large completions; short enough to not freeze Blender


def _post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    """Make a JSON POST request and return the parsed response dict."""
    data = _json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise APIError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise APIError(f"Network error reaching {url}: {exc.reason}") from exc


def _call_openai(messages: list[dict[str, str]], model: str) -> str:
    if not config.API_KEY:
        raise APIError("GENSCENE_API_KEY is not set. Add it to config.py or your environment.")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.API_KEY}",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,  # low temperature for deterministic function calls
    }
    response = _post(config.OPENAI_ENDPOINT, headers, payload)
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise APIError(f"Unexpected OpenAI response shape: {response}") from exc


def _call_anthropic(messages: list[dict[str, str]], model: str) -> str:
    if not config.API_KEY:
        raise APIError("GENSCENE_API_KEY is not set. Add it to config.py or your environment.")

    # Anthropic expects system message separated from user/assistant turns
    system_content = ""
    filtered: list[dict[str, str]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_content = msg["content"]
        else:
            filtered.append(msg)

    headers = {
        "Content-Type": "application/json",
        "x-api-key": config.API_KEY,
        "anthropic-version": config.ANTHROPIC_VERSION,
    }
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 1024,
        "temperature": 0.2,
        "messages": filtered,
    }
    if system_content:
        payload["system"] = system_content

    response = _post(config.ANTHROPIC_ENDPOINT, headers, payload)
    try:
        return response["content"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise APIError(f"Unexpected Anthropic response shape: {response}") from exc


def _call_ollama(messages: list[dict[str, str]], model: str) -> str:
    """Call a locally-running Ollama instance via its /api/chat endpoint.

    Ollama response shape (stream=false):
        {"message": {"role": "assistant", "content": "..."}, ...}

    No API key is required.  Ollama must already be running:
        ollama serve          # in a terminal, or via the Ollama desktop app
    """
    headers = {"Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,   # get a single JSON response, not a stream
        "options": {"temperature": 0.2},
    }
    response = _post(config.OLLAMA_ENDPOINT, headers, payload)
    try:
        return response["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise APIError(f"Unexpected Ollama response shape: {response}") from exc


# ── Public API ────────────────────────────────────────────────────────────────

def call_llm(
    messages: list[dict[str, str]],
    model: str | None = None,
    provider: str | None = None,
) -> str:
    """Send a list of chat messages to the configured LLM and return its reply.

    Args:
        messages: List of {"role": "system"|"user"|"assistant", "content": str}.
        model: Override the default model from config.py.
        provider: "openai", "anthropic", or "ollama".
                  Defaults to config.API_PROVIDER.

    Returns:
        The assistant's reply as a plain string.

    Raises:
        APIError: On network failure or unexpected API response.
    """
    prov = (provider or config.API_PROVIDER).lower()

    if prov == "openai":
        mdl = model or config.OPENAI_MODEL
        return _call_openai(messages, mdl)
    elif prov == "anthropic":
        mdl = model or config.ANTHROPIC_MODEL
        return _call_anthropic(messages, mdl)
    elif prov == "ollama":
        mdl = model or config.OLLAMA_MODEL
        return _call_ollama(messages, mdl)
    else:
        raise APIError(f"Unknown provider '{prov}'. Use 'openai', 'anthropic', or 'ollama'.")


def ping_test(provider: str | None = None) -> str:
    """Send a minimal one-token request to verify API connectivity and key validity.

    This is the recommended first step before running any scene generation.
    Blender console usage::

        from genscene.ai.api_client import ping_test
        print(ping_test())

    Returns:
        A short confirmation string, e.g. ``"OK — openai replied: Hello!"``.

    Raises:
        APIError: On auth failure, network error, or unexpected response.
    """
    reply = call_llm(
        messages=[{"role": "user", "content": 'Reply with exactly the word "Hello".'}],
        provider=provider,
    )
    prov = (provider or config.API_PROVIDER).lower()
    return f"OK — {prov} replied: {reply.strip()}"
