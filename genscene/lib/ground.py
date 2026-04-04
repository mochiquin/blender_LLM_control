"""
lib/ground.py — Surface detection via ray_cast.
Blender 5.0+ compatible.

Blender 5.0 ray_cast signature (unchanged from 3.x / 4.x):
    Scene.ray_cast(depsgraph, origin, direction, distance=1.70141e+38)
    → (result: bool, location: Vector, normal: Vector,
       index: int, object: Object, matrix: Matrix)

The depsgraph must be passed explicitly (the old implicit form was removed
in Blender 3.2 and is gone in 5.0).
"""

from __future__ import annotations

import bpy
from mathutils import Vector


def get_ground_z(
    x: float,
    y: float,
    start_z: float = 100.0,
    exclude_obj: bpy.types.Object | None = None,
) -> float:
    """Return the Z height of the topmost surface directly below (x, y).

    Fires a downward ray from (x, y, start_z).  The ray is evaluated against
    the depsgraph so modifiers, Boolean operations, and shape keys are all
    respected.

    Args:
        x: World-space X coordinate.
        y: World-space Y coordinate.
        start_z: Altitude from which the ray is fired.  Should be above the
            tallest object in the scene (default 100 m).
        exclude_obj: Optional object to skip (e.g. the object being placed,
            to avoid it hitting itself).

    Returns:
        World-space Z of the first surface hit, or 0.0 if nothing was hit.
    """
    # Blender 5.0: depsgraph must be provided explicitly
    depsgraph = bpy.context.evaluated_depsgraph_get()

    origin    = Vector((x, y, start_z))
    direction = Vector((0.0, 0.0, -1.0))

    # ray_cast returns: (hit, location, normal, face_index, object, matrix)
    result, location, _normal, _face_idx, hit_obj, _matrix = (
        bpy.context.scene.ray_cast(depsgraph, origin, direction)
    )

    if not result:
        return 0.0

    # hit_obj is the *evaluated* copy from the depsgraph, not the original
    # data-block.  Compare via .original to match the caller's exclude_obj.
    actual_hit_obj = hit_obj.original if hasattr(hit_obj, "original") else hit_obj

    if exclude_obj is not None and actual_hit_obj == exclude_obj:
        # Step just below the hit point and keep excluding the same object
        # so the ray doesn't catch its underside on the next pass.
        new_start = location.z - 0.0001
        return get_ground_z(x, y, start_z=new_start, exclude_obj=exclude_obj)

    return float(location.z)


def get_surface_normal(
    x: float,
    y: float,
    start_z: float = 100.0,
) -> tuple[float, float, float]:
    """Return the world-space surface normal at the point directly below (x, y).

    Useful for aligning spawned assets flush with sloped terrain.

    Returns:
        (nx, ny, nz) world-space normal, or (0.0, 0.0, 1.0) if nothing hit.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()

    origin    = Vector((x, y, start_z))
    direction = Vector((0.0, 0.0, -1.0))

    result, _location, normal, _face_idx, _obj, _matrix = (
        bpy.context.scene.ray_cast(depsgraph, origin, direction)
    )

    if not result:
        return (0.0, 0.0, 1.0)

    return (float(normal.x), float(normal.y), float(normal.z))
