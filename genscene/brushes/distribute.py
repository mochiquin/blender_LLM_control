"""
brushes/distribute.py — High-level spatial distribution helpers.

These functions are called by the AI (available in EXEC_GLOBALS) or directly
from user scripts.  They implement the "semantic brushes" of Phase 5:

  distribute_along_curve(asset_id, curve_obj, count)
      — spawn assets at evenly-spaced points along a Bezier/NURBS curve

  scatter_cluster(asset_id, center, count, radius)
      — random organic scatter within a circle, with optional ground-snap

Both functions return the list of spawned objects so the caller can pass them
to apply_physics_drop() if desired.
"""

from __future__ import annotations

import math
import random

import bpy
from mathutils import Vector

from ..lib.spawn import spawn_asset, place_on_ground
from .style_presets import get_scatter_density


# ── Curve distribution ────────────────────────────────────────────────────────

def _sample_curve_points(
    curve_obj: bpy.types.Object,
    count: int,
) -> list[Vector]:
    """Return `count` evenly-spaced world-space points along curve_obj."""
    if curve_obj.type != 'CURVE':
        raise ValueError(f"Object '{curve_obj.name}' is not a curve.")

    # Evaluate the curve to a mesh so we get actual geometry
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = curve_obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()

    if not mesh or not mesh.vertices:
        raise ValueError(f"Curve '{curve_obj.name}' produced no geometry.")

    # Collect edge-chain points in order
    verts = [curve_obj.matrix_world @ v.co for v in mesh.vertices]
    eval_obj.to_mesh_clear()

    if len(verts) < 2:
        return verts * count

    # Build cumulative arc-length lookup
    arc_lengths = [0.0]
    for i in range(1, len(verts)):
        arc_lengths.append(arc_lengths[-1] + (verts[i] - verts[i - 1]).length)

    total_length = arc_lengths[-1]
    if total_length < 1e-6:
        return [verts[0]] * count

    # Sample at uniform arc-length intervals
    samples: list[Vector] = []
    for i in range(count):
        t = (i / max(count - 1, 1)) * total_length
        # Find segment
        for j in range(1, len(arc_lengths)):
            if arc_lengths[j] >= t or j == len(arc_lengths) - 1:
                seg_len = arc_lengths[j] - arc_lengths[j - 1]
                if seg_len < 1e-8:
                    samples.append(verts[j].copy())
                else:
                    alpha = (t - arc_lengths[j - 1]) / seg_len
                    samples.append(verts[j - 1].lerp(verts[j], alpha))
                break

    return samples


def distribute_along_curve(
    asset_id: str,
    curve_obj: bpy.types.Object,
    count: int = 10,
    spacing_variance: float = 0.1,
    snap_to_ground: bool = True,
    style: str = "none",
) -> list[bpy.types.Object]:
    """Spawn `count` instances of asset_id along a curve object.

    Args:
        asset_id: Asset name / path passed to spawn_asset().
        curve_obj: A Blender curve object defining the distribution path.
        count: Number of assets to place.
        spacing_variance: Random position jitter as a fraction of spacing (0–1).
        snap_to_ground: If True, call place_on_ground() on each spawned object.
        style: Style preset key from style_presets.PRESETS.

    Returns:
        List of spawned objects.
    """
    density_mult = get_scatter_density(style)
    effective_count = max(1, int(count * density_mult))

    points = _sample_curve_points(curve_obj, effective_count)
    spawned: list[bpy.types.Object] = []

    for pt in points:
        # Optional jitter
        if spacing_variance > 0:
            jitter_scale = spacing_variance * 0.5
            dx = random.gauss(0, jitter_scale)
            dy = random.gauss(0, jitter_scale)
            loc = (pt.x + dx, pt.y + dy, pt.z)
        else:
            loc = (pt.x, pt.y, pt.z)

        rz = random.uniform(0, 2 * math.pi) if style != "clean_interior" else 0.0
        obj = spawn_asset(asset_id, location=loc, rotation=(0.0, 0.0, rz))
        if obj is None:
            continue
        if snap_to_ground:
            place_on_ground(obj)
        spawned.append(obj)

    return spawned


# ── Cluster scatter ───────────────────────────────────────────────────────────

def scatter_cluster(
    asset_id: str,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    count: int = 8,
    radius: float = 3.0,
    snap_to_ground: bool = True,
    style: str = "none",
) -> list[bpy.types.Object]:
    """Spawn a random organic cluster of assets within a circular area.

    Args:
        asset_id: Asset name / path passed to spawn_asset().
        center: World-space XYZ centre of the cluster.
        count: Number of assets to place.
        radius: Radius of the scatter disc in Blender units.
        snap_to_ground: If True, call place_on_ground() on each spawned object.
        style: Style preset key from style_presets.PRESETS.

    Returns:
        List of spawned objects.
    """
    density_mult = get_scatter_density(style)
    effective_count = max(1, int(count * density_mult))

    spawned: list[bpy.types.Object] = []
    cx, cy, cz = center

    for _ in range(effective_count):
        # Uniform distribution within a circle (not just on the edge)
        angle = random.uniform(0, 2 * math.pi)
        r = radius * math.sqrt(random.random())
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        z = cz

        rz = random.uniform(0, 2 * math.pi) if style != "clean_interior" else 0.0

        scale_var = 1.0
        if style in ("post_apocalyptic", "natural_outdoor"):
            scale_var = random.uniform(0.85, 1.15)

        obj = spawn_asset(
            asset_id,
            location=(x, y, z),
            rotation=(0.0, 0.0, rz),
            scale=(scale_var, scale_var, scale_var),
        )
        if obj is None:
            continue
        if snap_to_ground:
            place_on_ground(obj)
        spawned.append(obj)

    return spawned
