"""
lib/scene_serializer.py — Converts scene objects to a JSON snapshot for the AI.
Blender 5.0+ compatible.

Each object record includes its bounding-box extremes (x_min…z_max) in
world space so the LLM can reason about spatial relationships:
  - "place on top of table"  →  z = table["bbox"]["z_max"]
  - "place underneath shelf" →  z = shelf["bbox"]["z_min"] - obj_height
  - "scatter around barrel"  →  use x_min/x_max, y_min/y_max as area bounds

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
        "x_min": min(xs), "x_max": max(xs),
        "y_min": min(ys), "y_max": max(ys),
        "z_min": min(zs), "z_max": max(zs),
    }


def serialize_scene(selected_only: bool = False) -> str:
    """Serialize mesh objects in the current scene to a JSON string.

    Args:
        selected_only: If True only selected objects are included; otherwise
            all mesh objects in the active scene are serialised.

    Returns:
        A JSON array string, one element per mesh object, each containing:
        name, location, dimensions, rotation_euler (radians), and bbox.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()

    if selected_only:
        candidates = list(bpy.context.selected_objects)
    else:
        candidates = list(bpy.context.scene.objects)

    result: list[dict] = []
    for obj in candidates:
        if obj.type != 'MESH':
            continue
        result.append({
            "name": obj.name,
            "location": [round(v, 4) for v in obj.location],
            "dimensions": [round(v, 4) for v in obj.dimensions],
            "rotation_euler": [round(v, 6) for v in obj.rotation_euler],
            "bbox": {k: round(v, 4) for k, v in _world_bbox(obj, depsgraph).items()},
        })

    return json.dumps(result, indent=2)


def serialize_selected() -> str:
    """Convenience wrapper — serialises only the currently selected objects."""
    return serialize_scene(selected_only=True)


def print_scene_json() -> None:
    """Print the full scene JSON to the Blender console (debugging aid)."""
    print(serialize_scene(selected_only=False))
