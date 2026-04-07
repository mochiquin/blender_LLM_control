"""
lib/spawn.py — Asset spawning and ground placement.

spawn_asset() implements instance-reuse: the first call appends the mesh from
the asset library; subsequent calls for the same asset_id create linked
duplicates that share the same mesh data block, keeping memory usage low and
avoiding the .001 / .002 name pollution that a plain wm.append produces.
"""

from __future__ import annotations

import os
import bpy
from mathutils import Euler, Vector

from .ground import get_ground_z


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resolve_asset_path(asset_id: str) -> tuple[str, str] | None:
    """Return (blend_filepath, object_name) for the given asset_id.

    asset_id may be:
      - An absolute path to a .blend file, e.g. "/path/to/barrel.blend"
      - A bare name that will be looked up via asset_index (if available)
      - A name already present in bpy.data.objects (triggering instant reuse)

    Returns None if the asset cannot be located.
    """
    from .. import config

    # Already in the scene — no file lookup needed
    if asset_id in bpy.data.objects:
        return None  # caller handles reuse

    # Absolute .blend path passed directly
    if os.path.isfile(asset_id) and asset_id.endswith(".blend"):
        obj_name = os.path.splitext(os.path.basename(asset_id))[0]
        return asset_id, obj_name

    # Try the asset index for semantic names
    try:
        from ..ai.asset_index import AssetIndex
        idx = AssetIndex.get()
        match = idx.find(asset_id)
        if match:
            obj_name = os.path.splitext(os.path.basename(match))[0]
            return match, obj_name
    except Exception:
        pass

    # Last resort: look in the configured library root for a filename match
    lib_root = config.ASSET_LIBRARY_PATH
    if lib_root and os.path.isdir(lib_root):
        for dirpath, _dirs, files in os.walk(lib_root):
            for fname in files:
                if not fname.endswith(".blend"):
                    continue
                stem = os.path.splitext(fname)[0]
                if stem.lower() == asset_id.lower():
                    return os.path.join(dirpath, fname), stem

    # #region agent log
    import json as _j, time as _t
    with open("/Users/silin/Repo/blender_LLM_control/.cursor/debug-446955.log", "a") as _f:
        _f.write(_j.dumps({"sessionId":"446955","hypothesisId":"A","location":"spawn.py:_resolve_asset_path:exit","message":"resolve result","data":{"asset_id":asset_id,"result":None,"in_objects":asset_id in bpy.data.objects},"timestamp":int(_t.time()*1000)}) + "\n")
    # #endregion
    return None


def _append_object_from_blend(blend_path: str, obj_name: str) -> bpy.types.Object | None:
    """Append the first mesh Object found in blend_path/Object/ directory."""
    with bpy.data.libraries.load(blend_path, link=False) as (src, dst):
        # Try exact name first, then fall back to first available object
        if obj_name in src.objects:
            dst.objects = [obj_name]
        elif src.objects:
            dst.objects = [src.objects[0]]
        else:
            return None

    for obj in dst.objects:
        if obj is not None:
            bpy.context.collection.objects.link(obj)
            return obj

    return None


# ── Public API ────────────────────────────────────────────────────────────────

def spawn_asset(
    asset_id: str,
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> bpy.types.Object | None:
    """Spawn an asset by id and return the resulting Blender object.

    If an object with asset_id already exists in the scene it is
    linked-duplicated (shared mesh data) instead of re-appended, which avoids
    both memory waste and the Blender naming suffix problem (.001, .002 …).

    Args:
        asset_id: Logical name, absolute .blend path, or semantic label.
        location: World-space XYZ position.
        rotation: XYZ Euler rotation in radians.
        scale: XYZ scale factors.

    Returns:
        The new (or duplicated) object, or None on failure.
    """
    # ── Instance reuse path ───────────────────────────────────────────────────
    if asset_id in bpy.data.objects:
        src = bpy.data.objects[asset_id]
        obj = src.copy()
        obj.data = src.data  # shared mesh data block
        bpy.context.collection.objects.link(obj)

    # ── Fresh append path ─────────────────────────────────────────────────────
    else:
        result = _resolve_asset_path(asset_id)
        if result is None:
            print(f"[GenScene] spawn_asset: could not locate asset '{asset_id}'")
            # #region agent log
            import json as _j, time as _t
            with open("/Users/silin/Repo/blender_LLM_control/.cursor/debug-446955.log", "a") as _f:
                _f.write(_j.dumps({"sessionId":"446955","hypothesisId":"A-B","location":"spawn.py:spawn_asset:none_return","message":"spawn_asset returning None","data":{"asset_id":asset_id},"timestamp":int(_t.time()*1000)}) + "\n")
            # #endregion
            return None

        blend_path, obj_name = result
        obj = _append_object_from_blend(blend_path, obj_name)
        if obj is None:
            print(f"[GenScene] spawn_asset: append failed for '{asset_id}'")
            return None

        # Normalize name so future calls recognise it for reuse
        obj.name = asset_id

    obj.location = location
    obj.rotation_euler = Euler(rotation)
    obj.scale = scale

    # Deselect all, then select the new object and make it active
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    return obj


def place_on_ground(
    obj: bpy.types.Object,
    ground_obj: bpy.types.Object | None = None,
) -> None:
    """Move obj so that its lowest point rests on the surface below it.

    Uses get_ground_z() to ray-cast the surface at the object's XY position,
    then offsets Z so the bounding-box bottom sits exactly on that surface.

    Implementation note: we intentionally use obj.matrix_world (not
    eval_obj.matrix_world from the depsgraph) because this function is
    frequently called immediately after spawn_asset sets obj.location.
    For objects with no parents or constraints, obj.matrix_world reflects
    the new location instantly; the depsgraph snapshot (eval_obj) can lag
    behind by one evaluation cycle and would return a stale z_bottom.

    Args:
        obj: The object to place.
        ground_obj: Reserved for future use (per-object ground override).
    """
    x, y = obj.location.x, obj.location.y

    # obj.matrix_world updates synchronously when obj.location changes
    # (no depsgraph flush needed for parentless, constraint-free objects)
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    z_bottom = min(c.z for c in corners)
    z_origin = obj.location.z

    ground_z = get_ground_z(x, y, exclude_obj=obj)
    offset = ground_z - z_bottom
    obj.location.z = z_origin + offset
