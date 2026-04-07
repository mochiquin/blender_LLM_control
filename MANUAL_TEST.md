# 手动测试：AI 代码生成

本文件包含三样东西，可以直接复制到 ChatGPT / Claude 网页端，
测试 AI 能否根据自然语言描述生成正确的 Blender Python 代码。

---

## 1. 可用函数签名（来自 genscene/lib/）

把以下内容作为 **系统上下文** 粘贴给 AI。

```python
# ── genscene/lib/spawn.py ─────────────────────────────────────────────────────

def spawn_asset(
    asset_id: str,
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> bpy.types.Object | None:
    """Spawn an asset by id and return the resulting Blender object.

    If the asset_id already exists in the scene it is linked-duplicated
    (shared mesh data) instead of re-appended.

    Args:
        asset_id: Logical name, absolute .blend path, or semantic label.
        location: World-space XYZ position.
        rotation: XYZ Euler rotation in radians.
        scale:    XYZ scale factors.

    Returns:
        The new (or duplicated) object, or None on failure.
    """

def place_on_ground(
    obj: bpy.types.Object,
    ground_obj: bpy.types.Object | None = None,
) -> None:
    """Move obj so that its lowest point rests on the surface below it.

    Uses ray_cast against the depsgraph; automatically handles terrain,
    tables, and any other mesh surfaces.

    Args:
        obj:        The object to snap to the ground.
        ground_obj: Reserved for future use (ignored for now).
    """

# ── genscene/lib/ground.py ────────────────────────────────────────────────────

def get_ground_z(
    x: float,
    y: float,
    start_z: float = 100.0,
    exclude_obj: bpy.types.Object | None = None,
) -> float:
    """Return the Z height of the topmost surface directly below (x, y).

    Fires a downward ray from (x, y, start_z). Returns 0.0 if nothing hit.

    Args:
        x, y:        World-space horizontal coordinates.
        start_z:     Altitude from which the ray starts (default 100 m).
        exclude_obj: Object to skip (pass the object being placed to avoid
                     self-intersection).
    """

def get_surface_normal(
    x: float,
    y: float,
    start_z: float = 100.0,
) -> tuple[float, float, float]:
    """Return the world-space surface normal at the point below (x, y).

    Useful for aligning assets flush with sloped terrain.
    Returns (0, 0, 1) if nothing is hit.
    """

# ── genscene/lib/scene_serializer.py ─────────────────────────────────────────

def serialize_for_prompt(selected_only: bool = False) -> str:
    """Return a compact scene JSON string for injection into an AI prompt.

    Each object record contains:
      name        — Blender object name
      dimensions  — [width, depth, height] in metres
      surface_z   — Z coordinate of the top surface (use for "place on top of")
      center_xy   — [cx, cy] horizontal centre of the object's bounding box
      bbox        — full bounding box {x_min, x_max, y_min, y_max, z_min, z_max}
    """
```

---

## 2. 示例场景 JSON（`serialize_for_prompt()` 的输出样例）

在 Blender 的 Python Console 里运行：

```python
from genscene.lib.scene_serializer import print_prompt_json
print_prompt_json()
```

以下是一个**假设场景**的输出示例（一张桌子 + 一个桶），供手动测试使用：

```json
[
{"name": "Table", "dimensions": [1.2, 0.8, 0.75], "surface_z": 0.75, "center_xy": [0.0, 0.0], "bbox": {"x_min": -0.6, "x_max": 0.6, "y_min": -0.4, "y_max": 0.4, "z_min": 0.0, "z_max": 0.75}},
{"name": "Bucket", "dimensions": [0.3, 0.3, 0.4], "surface_z": 0.4, "center_xy": [2.0, 1.0], "bbox": {"x_min": 1.85, "x_max": 2.15, "y_min": 0.85, "y_max": 1.15, "z_min": 0.0, "z_max": 0.4}}
]
```

---

## 3. 手动测试 Prompt 模板

把**第 1 节函数签名** + **第 2 节场景 JSON** 一起贴给 AI，然后加上你的指令。

### Prompt 结构

```
你是一个 Blender Python 脚本生成器。
只能调用以下函数（已在当前脚本作用域中 import）：
  spawn_asset, place_on_ground, get_ground_z, get_surface_normal

函数签名如下：
[粘贴第 1 节内容]

当前场景中的物体（JSON）：
[粘贴第 2 节内容]

任务：
[你的自然语言指令]

要求：
- 只输出可直接执行的 Python 代码块，不要解释。
- 不要 import bpy，不要定义新函数，直接调用上面的函数。
- 所有坐标从场景 JSON 中读取，不要瞎猜数值。
```

### 测试用例

| 编号 | 指令 | 预期关键行为 |
|------|------|-------------|
| T-01 | `把桶放在桌子的正中间` | `location=(0.0, 0.0, 0.75)` 或调用 `place_on_ground` |
| T-02 | `在桌子四个角各放一个桶` | 使用 `bbox.x_min/x_max, y_min/y_max` 计算四个角坐标 |
| T-03 | `把桶放在桌子左边 0.5 米处的地面上` | x = table.bbox.x_min - 0.5, 调用 `place_on_ground` |
| T-04 | `把桶放到地面（z=0）` | z=0 or 直接调用 `place_on_ground` |
| T-05 | `在桌子周围随机散布 5 个桶` | 在 `x_min..x_max, y_min..y_max` 范围内随机采样 |

---

## 4. 验证结果

AI 生成代码后，在 Blender 的 Scripting 工作区运行，检查：

- [ ] 物体出现在正确位置（不在地板以下）
- [ ] 没有穿模（桶底 ≥ `surface_z`）
- [ ] 多次运行结果稳定，没有累积偏移

如果 AI 的代码有误，记录下来，更新 `genscene/ai/prompt_builder.py` 中的系统提示。
