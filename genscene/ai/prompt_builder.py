"""
ai/prompt_builder.py — Assembles the messages list sent to the LLM.

The system prompt defines the "contract" with the model: what functions exist,
what their signatures are, and that the model must output ONLY function calls —
no prose, no markdown, no import statements.

The user message combines the artist's natural-language instruction with the
current scene JSON so the model has spatial context to resolve relative
references ("on the table", "next to the barrel", etc.).

Template substitution uses str.replace() (not str.format()) so that literal
curly braces inside the prompt — e.g. bbox field lists or JSON examples —
never need to be escaped.
"""

from __future__ import annotations

# ── System prompt ─────────────────────────────────────────────────────────────
#
# Key design decisions:
#   1. Enumerate every allowed function with its full signature.
#      Vague descriptions produce hallucinated parameter names.
#   2. Forbid prose explicitly and by example.
#   3. Include worked examples so the model learns the exact output format.
#   4. Inject the asset catalogue so the model knows valid asset_id strings.
#   5. Inject the current scene JSON so the model can resolve relative coords.
#
# NOTE: substitution is done with .replace(), NOT .format(), so single braces
# inside the template are fine and do not need to be escaped.

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

Spatial shortcuts available in the CURRENT SCENE JSON:
  surface_z   — Z of the object's top face.  Use as the Z when placing ON TOP.
  center_xy   — [cx, cy] horizontal centre.  Use as X,Y when centring ON TOP.
  bbox        — full bounds {x_min, x_max, y_min, y_max, z_min, z_max}.
                Use x_min/x_max and y_min/y_max to scatter AROUND an object.

────────────────────────── EXAMPLES ─────────────────────────────────

Example 1 — ground placement:
User: "Place three barrels in a row along the X axis"

b1 = spawn_asset("barrel", (0, 0, 0))
b2 = spawn_asset("barrel", (1.2, 0, 0))
b3 = spawn_asset("barrel", (2.4, 0, 0))
place_on_ground(b1)
place_on_ground(b2)
place_on_ground(b3)

Example 2 — place ON TOP of another object (use surface_z + center_xy):
User: "Put a cup in the centre of the table"
Scene contains: {"name": "Table", "surface_z": 0.75, "center_xy": [0.0, 0.0], ...}

cup = spawn_asset("cup", (0.0, 0.0, 0.75))

Example 3 — scatter around an object using bbox:
User: "Scatter 4 stones around the barrel"
Scene contains: {"name": "Barrel", "bbox": {"x_min": -0.2, "x_max": 0.2, "y_min": -0.2, "y_max": 0.2}, ...}

s1 = spawn_asset("stone", (-0.5, -0.5, 0))
s2 = spawn_asset("stone", ( 0.5, -0.5, 0))
s3 = spawn_asset("stone", ( 0.5,  0.5, 0))
s4 = spawn_asset("stone", (-0.5,  0.5, 0))
place_on_ground(s1)
place_on_ground(s2)
place_on_ground(s3)
place_on_ground(s4)

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
    asset_catalogue: str | list[str] = "",
    style_suffix: str = "",
) -> list[dict[str, str]]:
    """Build the messages list to send to the LLM.

    Args:
        user_prompt: The artist's natural-language instruction.
        scene_json: JSON string from serialize_scene() (Phase 3).
        asset_catalogue: Either a newline-separated string of asset names
            (as returned by AssetIndex.for_prompt()) or a plain list of
            name strings — both are accepted and normalised automatically.
        style_suffix: Optional style preset text appended to the user message
            (e.g. "Scatter densely and apply heavy physics chaos." for
            post-apocalyptic preset).

    Returns:
        List of {"role": ..., "content": ...} dicts ready for call_llm().
    """
    # Normalise asset_catalogue: accept list[str] or str
    if isinstance(asset_catalogue, list):
        asset_catalogue = "\n".join(f"- {a}" for a in asset_catalogue if a)

    # Use str.replace() — NOT str.format() — so literal braces in the template
    # (bbox field descriptions, JSON examples) never need escaping.
    system_content = _SYSTEM_TEMPLATE.replace(
        "{asset_catalogue}", asset_catalogue.strip() or _EMPTY_CATALOGUE_MSG
    ).replace(
        "{scene_json}", scene_json.strip() or _EMPTY_SCENE_MSG
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
    corrected.append({"role": "assistant", "content": bad_code})
    corrected.append({"role": "user",      "content": failure_report})
    return corrected


# ── JSON mode ─────────────────────────────────────────────────────────────────
#
# An alternative prompt strategy that asks the LLM for structured JSON instead
# of raw Python code.  More predictable for simple single-intent commands;
# use the code-gen pipeline (build_messages) for complex multi-step tasks.

_JSON_SYSTEM_TEMPLATE = """\
你是一个 Blender 专家。你必须输出 JSON 数组，格式要求如下：

【硬性规则】
1. 输出必须是 JSON 数组 [ ... ]，即使只有一条指令也必须用数组包裹。
2. 结构平铺：严禁使用 "params" 嵌套，所有字段必须与 "action" 平级。
3. 不输出任何解释文字，不使用 ```json 包裹，只输出纯 JSON。

【动作与必填字段】
- "primitive" ：创建内置几何体，必须包含 "shape" 字段
- "spawn"     ：从资产库加载模型，必须包含 "asset_id" 字段
- "scatter"   ：在圆形区域内随机散布，必须包含 "asset_id" 字段
- "physics_drop"：对已有物体执行物理掉落模拟

【shape 合法值】（仅 primitive 使用）
{valid_shapes}

【各动作完整字段参考】
{action_schema}

────────────────────── 当前场景物体 ───────────────────────────────
（surface_z = 物体顶面 Z，可用于"放在上方"；center_xy = 水平中心）

{scene_json}

────────────────────── 资产库 ──────────────────────────────────────

{asset_catalogue}

────────────────────── 示例 ────────────────────────────────────────

指令：在原点放一个正方体，然后在它上方 5 米处放一个猴头。
输出：[{{"action": "primitive", "shape": "cube", "location": [0, 0, 0]}}, {{"action": "primitive", "shape": "monkey", "location": [0, 0, 5]}}]

指令：在 (1, 2, 3) 放一个球体，放大到 2 倍。
输出：[{{"action": "primitive", "shape": "sphere", "location": [1, 2, 3], "scale": 2.0}}]

指令：在桌子（surface_z=0.75，center_xy=[0,0]）正中心放一个圆柱体。
输出：[{{"action": "primitive", "shape": "cylinder", "location": [0, 0, 0.75]}}]

指令：在地面上放一个猴头。
输出：[{{"action": "primitive", "shape": "monkey", "location": [0, 0, 10], "snap_to_ground": true}}]

指令：在场景中间的地面上放一个球体。
输出：[{{"action": "primitive", "shape": "sphere", "location": [0, 0, 10], "snap_to_ground": true}}]

【snap_to_ground 使用规则】
当用户说"放在地面上"、"落在表面"、"贴地"时：
- 将 location 的 Z 设为 10（高处起始点）
- 加上 "snap_to_ground": true
- 插件自动射线检测，底面精确贴合下方表面，无需手算 Z 值

现在请根据用户指令输出 JSON 数组：
"""


def build_json_messages(
    user_prompt: str,
    scene_json: str = "",
    asset_catalogue: str | list[str] = "",
    auto_scene: bool = True,
) -> list[dict[str, str]]:
    """Build messages for JSON-mode prompting (structured output, no code-gen).

    The LLM is instructed to return a JSON object or array that the dispatcher
    (dispatcher.py) will execute.  Use this for simple single-intent commands.
    For complex multi-step tasks, use build_messages() (code-gen mode) instead.

    The action schema in the system prompt is generated automatically from
    dispatcher.SCHEMA_REGISTRY, so adding a new action there instantly makes
    it visible to the LLM.

    Args:
        user_prompt:     The artist's natural-language instruction.
        scene_json:      JSON string from serialize_for_prompt().  When empty
                         and auto_scene=True, the live scene is serialised
                         automatically (requires bpy context).
        asset_catalogue: Asset names string or list.
        auto_scene:      If True and scene_json is empty, auto-inject the
                         current Blender scene via serialize_for_prompt().

    Returns:
        List of {"role": ..., "content": ...} dicts ready for call_llm().
    """
    # ── Auto-inject live scene context ────────────────────────────────────────
    if not scene_json and auto_scene:
        try:
            from ..lib.scene_serializer import serialize_for_prompt
            scene_json = serialize_for_prompt()
        except Exception:
            pass  # no bpy context available (e.g. unit tests); fall through

    # ── Normalise asset catalogue ──────────────────────────────────────────────
    if isinstance(asset_catalogue, list):
        asset_catalogue = "\n".join(f"- {a}" for a in asset_catalogue if a)

    # ── Pull schema docs and shape list from registry (single source of truth) ─
    from .dispatcher import schema_to_prompt, _PRIMITIVE_OPS
    action_schema = schema_to_prompt()
    valid_shapes = str(sorted(_PRIMITIVE_OPS.keys()))  # e.g. ['ball', 'box', ...]

    system_content = _JSON_SYSTEM_TEMPLATE.replace(
        "{valid_shapes}", valid_shapes
    ).replace(
        "{action_schema}", action_schema
    ).replace(
        "{scene_json}", scene_json.strip() or _EMPTY_SCENE_MSG
    ).replace(
        "{asset_catalogue}", asset_catalogue.strip() or _EMPTY_CATALOGUE_MSG
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_prompt.strip()},
    ]
