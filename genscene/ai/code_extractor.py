"""
ai/code_extractor.py — Clean, execute, and self-correct AI-generated code.

The LLM is instructed to return only function calls, but in practice it
sometimes wraps output in markdown fences or adds a stray sentence.  The
extractor strips all non-code noise before execution.

exec() is always called with an explicit exec_globals dict that pre-loads all
lib functions so generated code can call spawn_asset(...) directly without
imports or name-error failures.
"""

from __future__ import annotations

import re
import traceback as _traceback
import bpy

from ..lib import spawn as _spawn
from ..lib import physics as _physics
from ..lib import ground as _ground
from ..brushes import distribute as _distribute
from .api_client import call_llm
from .prompt_builder import build_correction_messages
from .. import config


# ── Execution sandbox ─────────────────────────────────────────────────────────
#
# All functions the LLM is allowed to call must be present here.
# bpy is included as a safety net in case the model writes a raw bpy call.

EXEC_GLOBALS: dict = {
    # Core lib API
    "spawn_asset":           _spawn.spawn_asset,
    "place_on_ground":       _spawn.place_on_ground,
    "apply_physics_drop":    _physics.apply_physics_drop,
    "get_ground_z":          _ground.get_ground_z,
    # Phase 5 brushes
    "distribute_along_curve": _distribute.distribute_along_curve,
    "scatter_cluster":        _distribute.scatter_cluster,
    # Raw Blender access (fallback — model should not use this but may)
    "bpy":                    bpy,
    # Safe builtins only — no open(), __import__(), etc.
    "__builtins__": {
        "range": range, "len": len, "list": list, "tuple": tuple,
        "int": int, "float": float, "str": str, "bool": bool,
        "abs": abs, "round": round, "min": min, "max": max,
        "enumerate": enumerate, "zip": zip, "print": print,
        "True": True, "False": False, "None": None,
    },
}


# ── Security: explicit blocklist scan ────────────────────────────────────────
#
# These patterns are scanned BEFORE exec() — even though __builtins__ is
# sandboxed, rejecting them here gives a clean, readable error instead of a
# cryptic NameError inside exec().

_DANGEROUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bos\s*\.\s*(remove|unlink|rmdir|system|popen|exec)\b"),
     "filesystem/shell access via `os`"),
    (re.compile(r"\bsubprocess\b"),
     "subprocess execution"),
    (re.compile(r"\b__import__\s*\("),
     "dynamic import via __import__"),
    (re.compile(r"\bimport\s+os\b"),
     "import os"),
    (re.compile(r"\bimport\s+subprocess\b"),
     "import subprocess"),
    (re.compile(r"\bopen\s*\("),
     "file open()"),
    (re.compile(r"\beval\s*\("),
     "nested eval()"),
    (re.compile(r"\bexec\s*\("),
     "nested exec()"),
    (re.compile(r"\bshutil\b"),
     "shutil filesystem operations"),
    (re.compile(r"\bsocket\b"),
     "raw socket access"),
]


def check_safety(code: str) -> None:
    """Scan code for dangerous patterns and raise ValueError if any are found.

    Called automatically by run_with_retry() before exec().  Can also be used
    standalone for pre-flight validation.

    Args:
        code: The cleaned Python code string to inspect.

    Raises:
        ValueError: With a description of the matched dangerous pattern.
    """
    for pattern, description in _DANGEROUS_PATTERNS:
        if pattern.search(code):
            raise ValueError(
                f"[GenScene] Security check failed: code contains {description}.\n"
                f"Blocked before execution."
            )


# ── Code cleaning ─────────────────────────────────────────────────────────────

# Allowed call tokens (anything the LLM is supposed to output)
_ALLOWED_CALLS = {
    "spawn_asset", "place_on_ground", "apply_physics_drop", "get_ground_z",
    "distribute_along_curve", "scatter_cluster",
}


def clean_code(raw: str) -> str:
    """Strip markdown, blank lines, and non-code debris from LLM output.

    Lines that don't start with an allowed function name or a variable
    assignment are removed so stray prose cannot reach exec().

    Args:
        raw: The raw string returned by the LLM.

    Returns:
        A cleaned multi-line string of pure Python statements.
    """
    # Remove markdown fences first
    text = re.sub(r"```[a-zA-Z]*\n?", "", raw)
    text = re.sub(r"```", "", text)

    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Keep variable assignments (e.g. "b1 = spawn_asset(...)") and
        # direct function calls, and list literals for apply_physics_drop
        if (
            re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*", stripped)
            or any(stripped.startswith(fn) for fn in _ALLOWED_CALLS)
            or stripped.startswith("[")
        ):
            kept.append(line)

    return "\n".join(kept).strip()


# ── Execution with retry ──────────────────────────────────────────────────────

def run_with_retry(
    raw_code: str,
    original_messages: list[dict[str, str]] | None = None,
    max_retries: int | None = None,
) -> str:
    """Clean and execute AI-generated code, retrying on failure.

    On the first successful execution returns an empty string.
    On each failure the traceback is sent back to the LLM (if
    original_messages is provided) to request a corrected version.

    Args:
        raw_code: The unprocessed string from the LLM.
        original_messages: The conversation messages that produced raw_code.
            Required for self-correction; if None retries without LLM help.
        max_retries: Override config.MAX_EXEC_RETRIES.

    Returns:
        Empty string on success, or the last error message if all retries fail.

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    if max_retries is None:
        max_retries = config.MAX_EXEC_RETRIES

    code = clean_code(raw_code)
    messages = list(original_messages) if original_messages else None
    last_error = ""

    # Security gate — runs once on the cleaned code; raises immediately if
    # dangerous patterns are detected so we never reach exec().
    check_safety(code)

    for attempt in range(max_retries + 1):
        try:
            exec(code, EXEC_GLOBALS)  # noqa: S102
            return ""  # success
        except Exception:
            last_error = _traceback.format_exc()
            print(f"[GenScene] exec error (attempt {attempt + 1}/{max_retries + 1}):\n{last_error}")

            if attempt == max_retries or messages is None:
                break

            # Ask the LLM to fix its own code
            try:
                correction_messages = build_correction_messages(
                    messages, code, last_error
                )
                raw_correction = call_llm(correction_messages)
                code = clean_code(raw_correction)
                messages = correction_messages  # extend for next iteration
            except Exception as api_exc:
                print(f"[GenScene] correction API call failed: {api_exc}")
                break

    raise RuntimeError(
        f"GenScene: code execution failed after {max_retries + 1} attempt(s).\n\n"
        f"Last error:\n{last_error}\n\n"
        f"Last code:\n{code}"
    )
