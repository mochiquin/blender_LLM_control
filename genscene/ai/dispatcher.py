"""
ai/dispatcher.py — JSON action dispatcher.

Bridges the gap between structured LLM output (JSON) and the genscene lib API.
The LLM is asked to return a single JSON object (or a JSON array of objects for
multi-step tasks).  Each object must have an "action" field.  The dispatcher
maps that action to the appropriate lib function.

Supported actions
─────────────────
  spawn          → spawn_asset(asset_id, location, rotation, scale)
  place_on_ground→ place_on_ground(obj)
  scatter        → scatter_cluster(asset_id, center, count, radius, ...)
  physics_drop   → apply_physics_drop(objs, frames)

Why JSON instead of raw code generation?
  • The LLM can't hallucinate unknown function names — it must pick from the
    fixed "action" vocabulary defined in the prompt.
  • No exec() needed for the dispatch itself; the dispatcher is plain Python.
  • Easier to unit-test: just pass a dict, check what lib function was called.

The code-generation pipeline (code_extractor.py) still exists for complex
multi-step tasks.  Use JSON mode for single-intent commands; use code-gen mode
for "scatter barrels, drop them with physics, then put a crate on the table."
"""

from __future__ import annotations

import json
import re
from typing import Any

import bpy

from ..lib import spawn as _spawn
from ..lib import physics as _physics
from ..lib import ground as _ground
from ..lib import scene_serializer as _ser
from ..brushes import distribute as _distribute


# ── Schema Registry ───────────────────────────────────────────────────────────
#
# Single source of truth for every action the dispatcher supports.
# Used for:
#   1. Runtime validation in dispatch_one()
#   2. Auto-generating the AI prompt docs via schema_to_prompt()
#
# Field descriptor keys:
#   type        human-readable type string shown in the prompt
#   required    bool — dispatcher raises ValueError if missing
#   default     value used when the LLM omits the field (None = no default)
#   description one-line explanation shown in the prompt

SCHEMA_REGISTRY: dict[str, dict] = {
    "primitive": {
        "description": "Create a built-in Blender mesh — no asset file needed. Use for cubes, spheres, monkeys, etc.",
        "aliases": ["primitive", "new", "builtin", "new_primitive"],
        "fields": {
            "shape": {
                "type": "str", "required": True, "default": None,
                "description": "cube | sphere | monkey | cylinder | cone | plane | torus",
            },
            "location": {
                "type": "[x, y, z]", "required": False, "default": [0.0, 0.0, 0.0],
                "description": "World-space position in metres",
            },
            "height": {
                "type": "float", "required": False, "default": None,
                "description": "Shorthand for location[2] — omit location when only Z matters",
            },
            "scale": {
                "type": "float", "required": False, "default": 1.0,
                "description": "Uniform scale factor",
            },
            "snap_to_ground": {
                "type": "bool", "required": False, "default": False,
                "description": "Ray-cast downward and align the object's bottom face to the surface below it. Set location Z high (e.g. 10) and enable this for automatic ground placement.",
            },
        },
    },
    "spawn": {
        "description": "Place a .blend asset from the library into the scene",
        "aliases": ["spawn", "place", "add", "create", "put"],
        "fields": {
            "asset_id": {
                "type": "str", "required": True, "default": None,
                "description": "Exact name from the ASSET CATALOGUE",
            },
            "location": {
                "type": "[x, y, z]", "required": False, "default": [0.0, 0.0, 0.0],
                "description": "World-space position in metres",
            },
            "height": {
                "type": "float", "required": False, "default": None,
                "description": "Shorthand for location[2]",
            },
            "rotation": {
                "type": "[rx, ry, rz]", "required": False, "default": [0.0, 0.0, 0.0],
                "description": "XYZ Euler rotation in radians",
            },
            "scale": {
                "type": "[sx, sy, sz]", "required": False, "default": [1.0, 1.0, 1.0],
                "description": "Scale per axis",
            },
        },
    },
    "place_on_ground": {
        "description": "Snap an existing object downward to the surface below it (ray-cast, Z auto-computed)",
        "aliases": ["place_on_ground", "snap_to_ground", "ground"],
        "fields": {
            "asset_id": {
                "type": "str", "required": True, "default": None,
                "description": "Name of the object that already exists in the scene",
            },
        },
    },
    "scatter": {
        "description": "Randomly distribute multiple instances of an asset within a circle",
        "aliases": ["scatter", "distribute", "spread", "cluster"],
        "fields": {
            "asset_id": {
                "type": "str", "required": True, "default": None,
                "description": "Asset to scatter (from catalogue or scene)",
            },
            "center": {
                "type": "[x, y, z]", "required": False, "default": [0.0, 0.0, 0.0],
                "description": "Centre of the scatter circle; use center_xy from SCENE CONTEXT",
            },
            "count": {
                "type": "int", "required": False, "default": 8,
                "description": "Number of instances",
            },
            "radius": {
                "type": "float", "required": False, "default": 3.0,
                "description": "Scatter radius in metres",
            },
            "snap_to_ground": {
                "type": "bool", "required": False, "default": True,
                "description": "Snap each instance to the surface below it",
            },
        },
    },
    "physics_drop": {
        "description": "Run a short rigid-body simulation so objects fall and settle naturally",
        "aliases": ["physics_drop", "drop", "physics", "fall"],
        "fields": {
            "asset_ids": {
                "type": "[str, ...]", "required": False, "default": [],
                "description": "Object names to simulate; omit to use currently selected objects",
            },
            "frames": {
                "type": "int", "required": False, "default": 60,
                "description": "Simulation length in frames (24 fps = 2.5 s at default 60)",
            },
        },
    },
}

# Primitive shape → bpy.ops.mesh operator name
_PRIMITIVE_OPS: dict[str, str] = {
    "cube":     "primitive_cube_add",
    "box":      "primitive_cube_add",
    "sphere":   "primitive_uv_sphere_add",
    "ball":     "primitive_uv_sphere_add",
    "monkey":   "primitive_monkey_add",
    "suzanne":  "primitive_monkey_add",
    "cylinder": "primitive_cylinder_add",
    "cone":     "primitive_cone_add",
    "plane":    "primitive_plane_add",
    "torus":    "primitive_torus_add",
    "circle":   "primitive_circle_add",
}

# Reverse map: alias → canonical action name (derived from SCHEMA_REGISTRY)
_ALIAS_MAP: dict[str, str] = {
    alias: canonical
    for canonical, defn in SCHEMA_REGISTRY.items()
    for alias in defn["aliases"]
}

# Derived helpers (kept for dispatch_one compatibility)
def _required_fields(canonical: str) -> list[str]:
    return [f for f, d in SCHEMA_REGISTRY[canonical]["fields"].items() if d["required"]]

def _defaults(canonical: str) -> dict:
    return {
        f: d["default"]
        for f, d in SCHEMA_REGISTRY[canonical]["fields"].items()
        if not d["required"] and d["default"] is not None
    }


# ── Prompt generation ─────────────────────────────────────────────────────────

def schema_to_prompt(registry: dict | None = None) -> str:
    """Generate compact action documentation from SCHEMA_REGISTRY.

    Produces a tight format suited for small/local models: one action per block,
    required fields marked with *, optional fields with their default value.
    Adding a new action to SCHEMA_REGISTRY automatically makes it appear here.

    Example output line:
      primitive  — Create a built-in Blender mesh — no asset file needed.
        *shape (str): cube | sphere | monkey | cylinder | cone | plane | torus
        location ([x,y,z], default [0,0,0]): World-space position in metres
    """
    reg = registry or SCHEMA_REGISTRY
    blocks: list[str] = []

    for canonical, defn in reg.items():
        header = f'{canonical}  — {defn["description"]}'
        field_lines: list[str] = []
        for fname, fdef in defn["fields"].items():
            if fdef["required"]:
                prefix = f"  *{fname} ({fdef['type']})"
            else:
                prefix = f"  {fname} ({fdef['type']}, default {fdef['default']})"
            field_lines.append(f"{prefix}: {fdef['description']}")
        blocks.append(header + "\n" + "\n".join(field_lines))

    return "\n\n".join(blocks)


# ── JSON cleaning ─────────────────────────────────────────────────────────────

def extract_json(raw: str) -> Any:
    """Strip markdown fences and parse JSON from an LLM response string.

    Handles both single objects and arrays.  Raises ValueError on parse failure.
    """
    # Remove ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"```[a-zA-Z]*\n?", "", raw)
    text = re.sub(r"```", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"[Dispatcher] Could not parse LLM response as JSON.\n"
            f"Raw text: {text!r}\nError: {exc}"
        ) from exc


# ── Dispatch logic ────────────────────────────────────────────────────────────

def _resolve_action(raw_action: str) -> str | None:
    """Return the canonical action name for a raw action string, or None."""
    return _ALIAS_MAP.get(raw_action.lower().strip())


def dispatch_one(cmd: dict[str, Any]) -> bpy.types.Object | list | None:
    """Execute a single JSON command dict and return the result object(s).

    Args:
        cmd: Dict with at least an "action" key and action-specific fields.

    Returns:
        The spawned/modified object(s), or None.

    Raises:
        ValueError: If the action is unknown or a required field is missing.
    """
    raw_action = cmd.get("action", "")
    canonical = _resolve_action(str(raw_action))

    if canonical is None:
        known = sorted(_ALIAS_MAP.keys())
        raise ValueError(
            f"[Dispatcher] Unknown action '{raw_action}'.\n"
            f"Valid actions: {known}"
        )

    for field in _required_fields(canonical):
        if field not in cmd:
            raise ValueError(
                f"[Dispatcher] Action '{canonical}' requires field '{field}'."
            )

    # Merge defaults with provided values
    params = {**_defaults(canonical), **{k: v for k, v in cmd.items() if k != "action"}}

    # ── primitive ──────────────────────────────────────────────────────────────
    if canonical == "primitive":
        shape = str(params["shape"]).lower().strip()
        op_name = _PRIMITIVE_OPS.get(shape)
        if op_name is None:
            known = sorted(_PRIMITIVE_OPS.keys())
            raise ValueError(
                f"[Dispatcher] Unknown primitive shape '{shape}'. "
                f"Valid shapes: {known}"
            )

        loc = params["location"]
        if isinstance(loc, dict):
            loc = [loc.get("x", 0), loc.get("y", 0), loc.get("z", 0)]
        if "height" in params:
            loc = [loc[0], loc[1], params["height"]]

        scale = params["scale"]
        scale_val = scale if isinstance(scale, (int, float)) else 1.0

        op_fn = getattr(bpy.ops.mesh, op_name)
        op_fn(location=tuple(float(v) for v in loc), scale=(scale_val, scale_val, scale_val))

        obj = bpy.context.active_object
        print(f"[Dispatcher] Created primitive '{shape}' → '{obj.name}' at {list(loc)}")

        if params.get("snap_to_ground", False):
            _spawn.place_on_ground(obj)
            print(f"[Dispatcher] '{obj.name}' ray_cast 精确贴地 → Z={obj.location.z:.4f}")

        return obj

    # ── spawn ──────────────────────────────────────────────────────────────────
    if canonical == "spawn":
        loc = params["location"]
        # Accept {"location": {"x":0,"y":0,"z":5}} as well as [0,0,5]
        if isinstance(loc, dict):
            loc = [loc.get("x", 0), loc.get("y", 0), loc.get("z", 0)]
        # Support "height" shorthand: {"height": 5} → location z override
        if "height" in params and not isinstance(params.get("location"), list):
            loc[2] = params["height"]
        elif "height" in params:
            loc = [loc[0], loc[1], params["height"]]

        obj = _spawn.spawn_asset(
            asset_id=params["asset_id"],
            location=tuple(loc),
            rotation=tuple(params["rotation"]),
            scale=tuple(params["scale"]),
        )
        if obj is None:
            raise RuntimeError(
                f"[Dispatcher] spawn_asset failed for asset_id='{params['asset_id']}'."
            )
        print(f"[Dispatcher] Spawned '{obj.name}' at {list(obj.location)}")
        return obj

    # ── place_on_ground ────────────────────────────────────────────────────────
    if canonical == "place_on_ground":
        asset_id = params["asset_id"]
        obj = bpy.data.objects.get(asset_id)
        if obj is None:
            raise ValueError(
                f"[Dispatcher] place_on_ground: object '{asset_id}' not found in scene."
            )
        _spawn.place_on_ground(obj)
        print(f"[Dispatcher] Snapped '{obj.name}' to ground.")
        return obj

    # ── scatter ────────────────────────────────────────────────────────────────
    if canonical == "scatter":
        import math as _math
        import random as _random

        center = params["center"]
        if isinstance(center, dict):
            center = [center.get("x", 0), center.get("y", 0), center.get("z", 0)]
        asset_id   = params["asset_id"]
        count      = int(params["count"])
        radius     = float(params["radius"])
        snap       = bool(params["snap_to_ground"])
        cx, cy, cz = float(center[0]), float(center[1]), float(center[2])

        # If asset_id is a known primitive shape, scatter via bpy.ops directly
        # (no .blend file needed) — fixes the "could not locate asset" failure.
        prim_op = _PRIMITIVE_OPS.get(asset_id.lower())
        if prim_op is not None:
            op_fn = getattr(bpy.ops.mesh, prim_op)
            objs: list[bpy.types.Object] = []
            for _ in range(count):
                angle = _random.uniform(0, 2 * _math.pi)
                r     = radius * _math.sqrt(_random.random())
                x     = cx + r * _math.cos(angle)
                y     = cy + r * _math.sin(angle)
                op_fn(location=(x, y, cz))
                obj = bpy.context.active_object
                if snap:
                    _spawn.place_on_ground(obj)
                objs.append(obj)
            # #region agent log
            import json as _j, time as _t
            with open("/Users/silin/Repo/blender_LLM_control/.cursor/debug-446955.log", "a") as _f:
                _f.write(_j.dumps({"sessionId":"446955","hypothesisId":"FIX","location":"dispatcher.py:scatter:primitive_path","message":"primitive scatter result","data":{"asset_id":asset_id,"prim_op":prim_op,"count":len(objs)},"timestamp":int(_t.time()*1000)}) + "\n")
            # #endregion
            print(f"[Dispatcher] Scattered {len(objs)} × primitive '{asset_id}'")
            return objs

        # asset_id is a library asset — use the original scatter_cluster path
        objs = _distribute.scatter_cluster(
            asset_id=asset_id,
            center=tuple(center),
            count=count,
            radius=radius,
            snap_to_ground=snap,
        )
        print(f"[Dispatcher] Scattered {len(objs)} × '{asset_id}'")
        return objs

    # ── physics_drop ───────────────────────────────────────────────────────────
    if canonical == "physics_drop":
        asset_ids = params.get("asset_ids") or []
        objs = [bpy.data.objects[aid] for aid in asset_ids if aid in bpy.data.objects]
        if not objs:
            # Fall back: run physics on all recently selected objects
            objs = list(bpy.context.selected_objects)
        _physics.apply_physics_drop(objs, frames=int(params["frames"]))
        print(f"[Dispatcher] Physics drop applied to {len(objs)} object(s).")
        return objs

    return None  # unreachable


def dispatch(raw: str | dict | list) -> list:
    """Parse and execute one or more JSON commands from an LLM response.

    Args:
        raw: Either a raw LLM response string, a single command dict, or a
             list of command dicts.

    Returns:
        List of results from each dispatched command.

    Raises:
        ValueError: On JSON parse failure or unknown action.
    """
    if isinstance(raw, str):
        data = extract_json(raw)
    else:
        data = raw

    commands = data if isinstance(data, list) else [data]
    results = []
    for cmd in commands:
        results.append(dispatch_one(cmd))
    return results
