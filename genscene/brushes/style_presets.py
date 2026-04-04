"""
brushes/style_presets.py — Named style presets that modify the LLM prompt.

Each preset is a dict with:
  prompt_suffix   : str  — appended to the user message before LLM call
  physics_frames  : int  — override for apply_physics_drop() frame count
  scatter_density : float — multiplier for spread/spacing in distribute.py

Presets map to the genscene_style EnumProperty keys defined in operators.py.
"""

from __future__ import annotations

# ── Preset catalogue ──────────────────────────────────────────────────────────

PRESETS: dict[str, dict] = {
    "none": {
        "prompt_suffix": "",
        "physics_frames": 60,
        "scatter_density": 1.0,
    },

    "post_apocalyptic": {
        "prompt_suffix": (
            "Scatter objects chaotically with irregular spacing and random Z rotation. "
            "Apply heavy physics so objects tumble and pile up realistically. "
            "Some objects may overlap slightly to suggest long-term decay."
        ),
        "physics_frames": 120,
        "scatter_density": 1.8,
    },

    "clean_interior": {
        "prompt_suffix": (
            "Align objects neatly in straight lines or grids. "
            "Minimal rotation (keep objects upright). "
            "Use consistent spacing. Do NOT apply physics."
        ),
        "physics_frames": 0,
        "scatter_density": 0.6,
    },

    "natural_outdoor": {
        "prompt_suffix": (
            "Scatter organically with slight random rotation and scale variation (±15%). "
            "Snap each object to the ground surface using place_on_ground(). "
            "Vary density — cluster loosely, leave some open areas."
        ),
        "physics_frames": 40,
        "scatter_density": 1.2,
    },
}


def get_physics_frames(style_key: str, base_frames: int) -> int:
    """Return the physics frame count for a style, falling back to base_frames."""
    preset = PRESETS.get(style_key, {})
    override = preset.get("physics_frames")
    if override is not None and override > 0:
        return override
    return base_frames


def get_scatter_density(style_key: str) -> float:
    """Return the scatter density multiplier for a style."""
    return PRESETS.get(style_key, {}).get("scatter_density", 1.0)
