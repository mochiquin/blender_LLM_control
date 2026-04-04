"""
lib/physics.py — One-shot physics placement via in-memory frame stepping.
Blender 5.0+ compatible.

Key API changes vs. earlier Blender versions:
  - bpy.ops.object.visual_transform_apply() was REMOVED in Blender 5.0.
    We replace it by reading eval_obj.matrix_world from the depsgraph and
    writing it directly back to the object after stripping the rigid body.
  - All bpy.ops calls that need an active object use context.temp_override()
    (the old dict-based override was deprecated in 4.0 and removed in 5.0).
  - bpy.ops.rigidbody.world_add / object_add / object_remove still exist.
"""

from __future__ import annotations

import bpy
from mathutils import Matrix

from .. import config


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_rigid_body_world() -> None:
    """Add a Rigid Body World to the scene if one does not already exist."""
    scene = bpy.context.scene
    if scene.rigidbody_world is not None:
        return
    # temp_override is required in Blender 5.0 for ops that need a window
    with bpy.context.temp_override(scene=scene):
        bpy.ops.rigidbody.world_add()


def _add_rigid_body(obj: bpy.types.Object, body_type: str = 'ACTIVE') -> None:
    """Attach a rigid body component to obj (ACTIVE or PASSIVE)."""
    if obj.rigid_body is not None:
        obj.rigid_body.type = body_type
        obj.rigid_body.collision_shape = 'CONVEX_HULL'
        return

    # Make obj active so the operator targets it
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)

    with bpy.context.temp_override(
        active_object=obj,
        selected_objects=[obj],
    ):
        bpy.ops.rigidbody.object_add()

    obj.rigid_body.type = body_type
    obj.rigid_body.collision_shape = 'CONVEX_HULL'


def _capture_and_remove_rigid_body(obj: bpy.types.Object) -> None:
    """Read the physics-driven world matrix then strip all rigid body data.

    In Blender 5.0, bpy.ops.object.visual_transform_apply() no longer exists.
    The equivalent is:
      1. Evaluate the depsgraph to get the physics-driven matrix.
      2. Remove the rigid body (so physics no longer overrides the matrix).
      3. Write the captured matrix back to obj.matrix_world.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    world_matrix: Matrix = eval_obj.matrix_world.copy()

    # Strip rigid body BEFORE writing the matrix — otherwise the physics
    # system would override the written value on the next depsgraph update.
    if obj.rigid_body is not None:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)

        with bpy.context.temp_override(
            active_object=obj,
            selected_objects=[obj],
        ):
            bpy.ops.rigidbody.object_remove()

    # Now the rigid body is gone — write the captured physics position.
    obj.matrix_world = world_matrix


# ── Public API ────────────────────────────────────────────────────────────────

def apply_physics_drop(
    objs: list[bpy.types.Object],
    frames: int | None = None,
    add_ground_plane: bool = True,
) -> None:
    """Simulate a physics drop and bake final transforms onto each object.

    Uses frame_set() stepping (no disk cache) for fast, in-memory simulation.
    All rigid body data is removed afterwards so the scene stays clean.

    Args:
        objs: Mesh objects to drop.  They should be positioned above the
            collision surface before calling this function.
        frames: Simulation length in frames.  Defaults to config.PHYSICS_FRAMES.
        add_ground_plane: Create a temporary PASSIVE ground plane if no passive
            rigid body already exists in the scene.
    """
    if not objs:
        return

    if frames is None:
        frames = config.PHYSICS_FRAMES

    scene = bpy.context.scene
    original_frame = scene.frame_current

    _ensure_rigid_body_world()
    bpy.ops.object.select_all(action='DESELECT')

    # ── Optional temporary ground plane ──────────────────────────────────────
    temp_ground: bpy.types.Object | None = None
    has_passive = any(
        o.rigid_body and o.rigid_body.type == 'PASSIVE'
        for o in scene.objects
    )
    if add_ground_plane and not has_passive:
        bpy.ops.mesh.primitive_plane_add(size=500, location=(0.0, 0.0, 0.0))
        temp_ground = bpy.context.active_object
        temp_ground.name = "_genscene_temp_ground"
        _add_rigid_body(temp_ground, body_type='PASSIVE')
        bpy.ops.object.select_all(action='DESELECT')

    # ── Attach ACTIVE rigid bodies ────────────────────────────────────────────
    for obj in objs:
        _add_rigid_body(obj, body_type='ACTIVE')
    bpy.ops.object.select_all(action='DESELECT')

    # Reset the physics cache so simulation starts from frame 1
    rbw = scene.rigidbody_world
    if rbw and rbw.point_cache:
        rbw.point_cache.frame_start = 1
        rbw.point_cache.frame_end = frames + 10

    # ── Step the simulation frame-by-frame (in-memory, no disk cache) ────────
    scene.frame_set(1)
    for f in range(2, frames + 1):
        scene.frame_set(f)

    # ── Bake transforms and strip rigid bodies ────────────────────────────────
    for obj in objs:
        _capture_and_remove_rigid_body(obj)

    # ── Tear down temporary ground ────────────────────────────────────────────
    if temp_ground is not None:
        bpy.data.objects.remove(temp_ground, do_unlink=True)

    # Restore timeline position
    scene.frame_set(original_frame)
