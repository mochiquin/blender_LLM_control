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


# ── Preferences helper ────────────────────────────────────────────────────────

def _prefs():
    """Return the GenScene AddonPreferences object, or None if unavailable.

    Preferences win over config.py values so users can configure everything
    from Edit > Preferences > Add-ons > GenScene without editing any files.
    """
    try:
        import bpy
        # __package__ is "genscene.ai" (dev) or "bl_ext.user_default.genscene.ai"
        # (Extension).  Strip the last component to get the parent addon ID.
        addon_id = __package__.rsplit(".", 1)[0]
        addon = bpy.context.preferences.addons.get(addon_id)
        return addon.preferences if addon else None
    except Exception:  # noqa: BLE001
        return None


# ── Internal helpers ──────────────────────────────────────────────────────────

_TIMEOUT_SECONDS = 120  # Ollama on first-run can be slow; raise from 30 s


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


def _call_openai(messages: list[dict[str, str]], model: str, api_key: str = "") -> str:
    key = api_key or config.API_KEY
    if not key:
        raise APIError(
            "API key is not set.\n"
            "Go to Edit > Preferences > Add-ons > GenScene and enter your key,\n"
            "or set the GENSCENE_API_KEY environment variable."
        )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
    }
    response = _post(config.OPENAI_ENDPOINT, headers, payload)
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise APIError(f"Unexpected OpenAI response shape: {response}") from exc


def _call_anthropic(messages: list[dict[str, str]], model: str, api_key: str = "") -> str:
    key = api_key or config.API_KEY
    if not key:
        raise APIError(
            "API key is not set.\n"
            "Go to Edit > Preferences > Add-ons > GenScene and enter your key,\n"
            "or set the GENSCENE_API_KEY environment variable."
        )
    system_content = ""
    filtered: list[dict[str, str]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_content = msg["content"]
        else:
            filtered.append(msg)

    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
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


def _call_ollama(messages: list[dict[str, str]], model: str, url: str = "") -> str:
    """Call a locally-running Ollama instance via its /api/chat endpoint.

    No API key required.  Ollama must be running:
        ollama serve          # or via the Ollama desktop app
    """
    endpoint = url or config.OLLAMA_ENDPOINT
    headers = {"Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    response = _post(endpoint, headers, payload)
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

    Priority for each setting: call argument > Blender preferences > config.py.

    Args:
        messages: List of {"role": "system"|"user"|"assistant", "content": str}.
        model: Override the model (skips preferences and config.py).
        provider: "openai", "anthropic", or "ollama".

    Returns:
        The assistant's reply as a plain string.

    Raises:
        APIError: On auth failure, network error, or unexpected response.
    """
    prefs = _prefs()

    prov = (
        provider
        or (prefs.provider if prefs else None)
        or config.API_PROVIDER
    ).lower()

    if prov == "openai":
        mdl = model or config.OPENAI_MODEL
        key = (prefs.api_key if prefs else "") or config.API_KEY
        return _call_openai(messages, mdl, api_key=key)

    elif prov == "anthropic":
        mdl = model or config.ANTHROPIC_MODEL
        key = (prefs.api_key if prefs else "") or config.API_KEY
        return _call_anthropic(messages, mdl, api_key=key)

    elif prov == "ollama":
        mdl = model or (prefs.ollama_model if prefs else None) or config.OLLAMA_MODEL
        url = (prefs.ollama_url if prefs else "") or config.OLLAMA_ENDPOINT
        return _call_ollama(messages, mdl, url=url)

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
