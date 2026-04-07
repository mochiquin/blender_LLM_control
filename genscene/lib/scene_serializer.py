"""
lib/scene_serializer.py — Converts scene objects to a JSON snapshot for the AI.
Blender 5.0+ compatible.

Each object record includes its bounding-box extremes (x_min…z_max) in
world space so the LLM can reason about spatial relationships:
  - "place on top of table"  →  z = table["surface_z"]
  - "place underneath shelf" →  z = shelf["bbox"]["z_min"] - obj_height
  - "scatter around barrel"  →  use x_min/x_max, y_min/y_max as area bounds
  - "center on table"        →  x, y = table["center_xy"]

Blender 5.0 note:
  obj.bound_box returns local-space corners computed from the object's stored
  mesh, which ignores modifier results.  We read bound_box from the *evaluated*
  object (via depsgraph) so Boolean/Subdivision/etc. modifiers are respected.
"""

from __future__ import annotations

import json
import bpy
from mathutils import Vector


def _world_bbox(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
) -> dict[str, float]:
    """Return world-space bounding-box extremes for a mesh object.

    Uses the evaluated (modifier-applied) geometry so the bounds accurately
    reflect what is visible in the viewport.
    """
    eval_obj = obj.evaluated_get(depsgraph)

    # bound_box is 8 local-space corners; multiply by world matrix for world space.
    # Use eval_obj.matrix_world (same as obj.matrix_world for non-parented objects,
    # but correct for objects whose world matrix is driven by constraints).
    corners: list[Vector] = [
        eval_obj.matrix_world @ Vector(c) for c in eval_obj.bound_box
    ]

    xs = [v.x for v in corners]
    ys = [v.y for v in corners]
    zs = [v.z for v in corners]
    return {
        "x_min": round(min(xs), 4), "x_max": round(max(xs), 4),
        "y_min": round(min(ys), 4), "y_max": round(max(ys), 4),
        "z_min": round(min(zs), 4), "z_max": round(max(zs), 4),
    }


def _object_record(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph) -> dict:
    """Build the full record dict for one mesh object."""
    bbox = _world_bbox(obj, depsgraph)
    return {
        # identity
        "name": obj.name,
        # world origin
        "location": [round(v, 4) for v in obj.location],
        # size along each axis
        "dimensions": [round(v, 4) for v in obj.dimensions],
        # orientation
        "rotation_euler": [round(v, 6) for v in obj.rotation_euler],
        # full bounding box
        "bbox": bbox,
        # ── LLM-friendly shortcuts ──────────────────────────────────────────
        # Top surface Z — use this as the Z for "place on top of <object>"
        "surface_z": bbox["z_max"],
        # Horizontal centre — use as (x, y) for "centre on top of <object>"
        "center_xy": [
            round((bbox["x_min"] + bbox["x_max"]) / 2, 4),
            round((bbox["y_min"] + bbox["y_max"]) / 2, 4),
        ],
    }


def serialize_scene(selected_only: bool = False) -> str:
    """Serialize mesh objects in the current scene to a JSON string.

    Args:
        selected_only: If True only selected objects are included; otherwise
            all mesh objects in the active scene are serialised.

    Returns:
        A JSON array string, one element per mesh object, each containing:
        name, location, dimensions, rotation_euler (radians), bbox,
        surface_z, and center_xy.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    candidates = (
        list(bpy.context.selected_objects)
        if selected_only
        else list(bpy.context.scene.objects)
    )

    result: list[dict] = [
        _object_record(obj, depsgraph)
        for obj in candidates
        if obj.type == "MESH"
    ]
    return json.dumps(result, indent=2)


def serialize_for_prompt(selected_only: bool = False) -> str:
    """Return a compact scene description optimised for AI prompt injection.

    Compared with serialize_scene(), this format:
    - omits rotation (rarely needed for placement tasks)
    - uses a one-object-per-line layout to save tokens
    - keeps surface_z and center_xy as top-level fields for readability

    Typical usage in a system prompt::

        scene = serialize_for_prompt()
        prompt = f"Scene objects:\\n{scene}\\n\\nTask: place a bucket on the table."

    Returns a JSON array string (compact, one line per object).
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    candidates = (
        list(bpy.context.selected_objects)
        if selected_only
        else list(bpy.context.scene.objects)
    )

    compact: list[dict] = []
    for obj in candidates:
        if obj.type != "MESH":
            continue
        bbox = _world_bbox(obj, depsgraph)
        compact.append({
            "name": obj.name,
            "dimensions": [round(v, 3) for v in obj.dimensions],
            "surface_z": bbox["z_max"],
            "center_xy": [
                round((bbox["x_min"] + bbox["x_max"]) / 2, 3),
                round((bbox["y_min"] + bbox["y_max"]) / 2, 3),
            ],
            "bbox": bbox,
        })

    # One record per line — easier to read in a prompt window
    lines = [json.dumps(rec, separators=(", ", ": ")) for rec in compact]
    return "[\n" + ",\n".join(lines) + "\n]"


def serialize_selected() -> str:
    """Convenience wrapper — serialises only the currently selected objects."""
    return serialize_scene(selected_only=True)


def print_scene_json() -> None:
    """Print the full scene JSON to the Blender console (debugging aid)."""
    print(serialize_scene())


def print_prompt_json() -> None:
    """Print the compact prompt-ready JSON to the Blender console."""
    print(serialize_for_prompt())
