"""
ai/prompt_builder.py — Assembles the messages list sent to the LLM.

The system prompt is the most iterated part of the whole tool.  It defines
the "contract" with the model: what functions exist, what their signatures are,
and that the model must output ONLY function calls — no prose, no markdown,
no import statements.

The user message combines the artist's natural-language instruction with the
current scene JSON so the model has spatial context to resolve relative
references ("on the table", "next to the barrel", etc.).
"""

from __future__ import annotations

# ── System prompt ─────────────────────────────────────────────────────────────
#
# Key design decisions:
#   1. Enumerate every allowed function with its full signature and docstring.
#      Vague descriptions produce hallucinated parameter names.
#   2. Forbid prose explicitly and by example.
#   3. Include a worked example so the model learns the exact output format.
#   4. Inject the asset catalogue so the model knows valid asset_id strings.
#   5. Inject the current scene JSON so the model can resolve relative coords.

_SYSTEM_TEMPLATE = """\
You are GenScene, a Blender scene-building assistant.
Your ONLY output must be valid Python function calls — nothing else.

────────────────────────── ALLOWED FUNCTIONS ──────────────────────────

spawn_asset(asset_id, location, rotation=(0,0,0), scale=(1,1,1))
  Spawn an asset into the scene.
  asset_id  : str  — exact name from the ASSET CATALOGUE below
  location  : (x, y, z) float tuple — world-space position in metres
  rotation  : (rx, ry, rz) float tuple — XYZ Euler in RADIANS (optional)
  scale     : (sx, sy, sz) float tuple (optional, default (1,1,1))
  Returns the created object (you can ignore the return value).

place_on_ground(obj)
  Move obj so its lowest point rests on the surface directly beneath it.
  Call this AFTER spawn_asset when you want ground-snapping.
  obj : the return value of spawn_asset()

apply_physics_drop(objs, frames=60)
  Run a short rigid-body simulation so objs fall and settle naturally.
  objs   : list of objects returned by spawn_asset()
  frames : int — simulation length (default 60)

get_ground_z(x, y)
  Return the world-space Z height of the surface at (x, y).
  Use this to compute Z offsets relative to terrain.

distribute_along_curve(asset_id, curve_obj, count=10, spacing_variance=0.1, snap_to_ground=True, style="none")
  Spawn `count` instances of asset_id evenly spaced along a Blender curve.
  curve_obj : a bpy.data.objects["CurveName"] reference
  Returns list of spawned objects.

scatter_cluster(asset_id, center=(0,0,0), count=8, radius=3.0, snap_to_ground=True, style="none")
  Scatter `count` instances randomly within a circle of `radius` at `center`.
  Returns list of spawned objects.

────────────────────────── OUTPUT RULES ──────────────────────────────

• Output ONLY Python function calls, one per line.
• Do NOT write: imports, comments, markdown (no ```), variable declarations,
  print(), class/def blocks, or ANY prose.
• You MAY use temporary variables to pass objects between calls, e.g.:
      b = spawn_asset("barrel", (1, 2, 0))
      place_on_ground(b)
• If placing multiple objects with physics, collect them and call
  apply_physics_drop once at the end.
• Coordinates are in Blender world units (metres).  The scene Y axis points
  into the screen; Z is up.
• To place an object ON TOP of another, use bbox["z_max"] from the scene JSON.
• To scatter around an object, use its bbox x_min/x_max and y_min/y_max.

────────────────────────── EXAMPLE ──────────────────────────────────

User: "Place three barrels in a row along the X axis"

Correct output:
b1 = spawn_asset("barrel", (0, 0, 0))
b2 = spawn_asset("barrel", (1.2, 0, 0))
b3 = spawn_asset("barrel", (2.4, 0, 0))
place_on_ground(b1)
place_on_ground(b2)
place_on_ground(b3)

────────────────────────── ASSET CATALOGUE ───────────────────────────

{asset_catalogue}

────────────────────────── CURRENT SCENE ─────────────────────────────

{scene_json}

──────────────────────────────────────────────────────────────────────
Remember: output ONLY function calls.  No explanations.  No markdown.
"""

_EMPTY_SCENE_MSG = "[Scene is empty — no objects yet]"
_EMPTY_CATALOGUE_MSG = "[No asset library configured — use absolute .blend paths as asset_id]"


# ── Public API ────────────────────────────────────────────────────────────────

def build_messages(
    user_prompt: str,
    scene_json: str = "",
    asset_catalogue: str = "",
    style_suffix: str = "",
) -> list[dict[str, str]]:
    """Build the messages list to send to the LLM.

    Args:
        user_prompt: The artist's natural-language instruction.
        scene_json: JSON string from serialize_scene() (Phase 3).
        asset_catalogue: Newline-separated asset names from asset_index.py.
        style_suffix: Optional style preset text appended to the user message
            (e.g. "Scatter densely and apply heavy physics chaos." for
            post-apocalyptic preset).

    Returns:
        List of {"role": ..., "content": ...} dicts ready for call_llm().
    """
    system_content = _SYSTEM_TEMPLATE.format(
        asset_catalogue=asset_catalogue.strip() or _EMPTY_CATALOGUE_MSG,
        scene_json=scene_json.strip() or _EMPTY_SCENE_MSG,
    )

    user_content = user_prompt.strip()
    if style_suffix:
        user_content += f"\n\nStyle guidance: {style_suffix.strip()}"

    return [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_content},
    ]


def build_correction_messages(
    original_messages: list[dict[str, str]],
    bad_code: str,
    traceback_text: str,
) -> list[dict[str, str]]:
    """Build a follow-up conversation asking the LLM to fix an error.

    Appends the failed code and its Python traceback to the conversation
    history so the model has full context for a correction attempt.

    Args:
        original_messages: The messages list used in the failing call.
        bad_code: The code string that raised an exception.
        traceback_text: The full Python traceback as a string.

    Returns:
        Extended messages list with the failure context appended.
    """
    failure_report = (
        "The code you generated caused a Python exception in Blender.\n"
        "Fix it and output ONLY the corrected function calls — no explanations.\n\n"
        f"Failed code:\n{bad_code}\n\n"
        f"Error:\n{traceback_text}"
    )

    corrected = list(original_messages)
    # Include the assistant's previous (bad) attempt so the model sees what failed
    corrected.append({"role": "assistant", "content": bad_code})
    corrected.append({"role": "user",      "content": failure_report})
    return corrected
