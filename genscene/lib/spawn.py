"""
lib/spawn.py — Asset spawning and ground placement.

spawn_asset() implements instance-reuse: the first call appends the object from
the asset library; subsequent calls for the same asset_id create linked
duplicates that share the same mesh data block, keeping memory usage low and
avoiding the .001 / .002 name pollution that a plain wm.append produces.

Asset resolution order
──────────────────────
1. Already in scene (bpy.data.objects) → duplicate in-place.
2. Absolute .blend path passed directly.
3. AssetIndex lookup:
   a. Exact normalised object-name match inside any .blend file.
   b. Keyword-overlap fuzzy match.
4. Filename-stem scan of ASSET_LIBRARY_PATH as last resort.

Raises RuntimeError (instead of returning None) when the asset cannot be
located, so the LLM self-correction loop receives a clear error message.
"""

from __future__ import annotations

import os
import bpy
from mathutils import Euler, Vector

from .ground import get_ground_z


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resolve_asset_path(asset_id: str) -> tuple[str, str] | None:
    """Return (blend_filepath, object_name) for the given asset_id, or None.

    object_name is the exact name of the Blender object inside the .blend file.
    """
    from .. import config

    # 1. Already in the scene — caller handles duplication, no file needed
    if asset_id in bpy.data.objects:
        return None  # handled by instance-reuse path in spawn_asset

    # 2. Absolute .blend path passed directly
    if os.path.isfile(asset_id) and asset_id.endswith(".blend"):
        obj_name = os.path.splitext(os.path.basename(asset_id))[0]
        return asset_id, obj_name

    # 3. AssetIndex: searches by object names *inside* each .blend file
    try:
        from ..ai.asset_index import AssetIndex
        match = AssetIndex.get().find(asset_id)
        if match:
            return match  # already (filepath, obj_name)
    except Exception:  # noqa: BLE001
        pass

    # 4. Last resort: filename-stem scan of the library root
    lib_root = config.ASSET_LIBRARY_PATH
    if lib_root and os.path.isdir(lib_root):
        for dirpath, _dirs, files in os.walk(lib_root):
            for fname in files:
                if not fname.endswith(".blend"):
                    continue
                stem = os.path.splitext(fname)[0]
                if stem.lower() == asset_id.lower():
                    return os.path.join(dirpath, fname), stem

    return None


def _append_object_from_blend(blend_path: str, obj_name: str) -> bpy.types.Object | None:
    """Append the named object from blend_path into the current scene."""
    with bpy.data.libraries.load(blend_path, link=False) as (src, dst):
        if obj_name in src.objects:
            dst.objects = [obj_name]
        elif src.objects:
            # Fall back to the first available object if exact name is missing
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
) -> bpy.types.Object:
    """Spawn an asset by id and return the resulting Blender object.

    Args:
        asset_id: Object name, filename stem, or absolute .blend path.
        location: World-space XYZ position.
        rotation: XYZ Euler rotation in radians.
        scale: XYZ scale factors.

    Returns:
        The spawned (or duplicated) Blender object.

    Raises:
        RuntimeError: If the asset cannot be located or appended.
    """
    # ── Instance reuse path ───────────────────────────────────────────────────
    if asset_id in bpy.data.objects:
        src = bpy.data.objects[asset_id]
        obj = src.copy()
        obj.data = src.data  # shared mesh data block — avoids memory duplication
        bpy.context.collection.objects.link(obj)

    # ── Fresh append path ─────────────────────────────────────────────────────
    else:
        result = _resolve_asset_path(asset_id)
        if result is None:
            raise RuntimeError(
                f"[GenScene] spawn_asset: asset '{asset_id}' not found.\n"
                f"Check the asset library path in the GenScene preferences, or use a "
                f"valid asset_id from the catalogue shown in the system prompt."
            )

        blend_path, obj_name = result
        obj = _append_object_from_blend(blend_path, obj_name)
        if obj is None:
            raise RuntimeError(
                f"[GenScene] spawn_asset: found '{blend_path}' for asset '{asset_id}' "
                f"but the file contains no appendable objects."
            )

        # Normalise the object name so future calls can reuse the instance
        obj.name = asset_id

    obj.location = location
    obj.rotation_euler = Euler(rotation)
    obj.scale = scale

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    return obj


def place_on_ground(
    obj: bpy.types.Object | str | None,
    ground_obj: bpy.types.Object | None = None,
) -> None:
    """Move obj so that its lowest bounding-box point rests on the ground surface.

    Uses get_ground_z() to ray-cast the surface at the object's XY position,
    then offsets Z so the bounding-box bottom sits exactly on that surface.

    Args:
        obj: The object to place.  Accepts:
               • bpy.types.Object — the normal case (return value of spawn_asset)
               • str              — object name; resolved via bpy.data.objects
               • None             — silently skipped (spawn_asset failure guard)
        ground_obj: Reserved for future use (per-object ground override).
    """
    # Guard: None means spawn_asset failed upstream
    if obj is None:
        print("[GenScene] place_on_ground: received None — skipping.")
        return

    # Tolerance: LLM sometimes passes the name string instead of the handle
    if isinstance(obj, str):
        name = obj
        obj = bpy.data.objects.get(name)
        if obj is None:
            print(f"[GenScene] place_on_ground: no object named '{name}' — skipping.")
            return

    # Final type guard in case something unexpected was passed
    if not hasattr(obj, "location"):
        print(f"[GenScene] place_on_ground: expected Object, got {type(obj).__name__} — skipping.")
        return

    x, y = obj.location.x, obj.location.y

    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    z_bottom = min(c.z for c in corners)
    z_origin = obj.location.z

    ground_z = get_ground_z(x, y, exclude_obj=obj)
    offset = ground_z - z_bottom
    obj.location.z = z_origin + offset
