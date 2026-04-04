"""
ui/operators.py — Blender 5.0+ operators for the GenScene pipeline.

Blender 5.0 undo notes:
  Setting bl_options = {'REGISTER', 'UNDO'} on the operator is the correct
  and ONLY mechanism needed to create a single undo step.  Calling
  bpy.ops.ed.undo_push() from *inside* execute() causes a duplicate entry
  in the undo stack and was the source of a common bug in Blender 4.x add-ons.
  In Blender 5.0 this mis-use can also raise a RuntimeError.
  We rely solely on the UNDO bl_option; the operator wraps ALL changes into
  one Ctrl+Z action automatically.

Blender 5.0 context-override notes:
  The old dict-based operator override (bpy.ops.foo({'area': area, ...})) was
  removed in Blender 5.0.  All context overrides must use context.temp_override().
"""

from __future__ import annotations

import bpy
from bpy.props import StringProperty


class GENSCENE_OT_generate(bpy.types.Operator):
    """Generate Blender scene objects from a natural-language description."""

    bl_idname = "genscene.generate"
    bl_label = "Generate"
    bl_description = "Send the prompt to the AI and build the scene"
    # UNDO groups ALL changes made during execute() into one undo step.
    # Do NOT also call bpy.ops.ed.undo_push() — that would create a duplicate.
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        prompt: str = scene.genscene_prompt.strip()

        if not prompt:
            self.report({'WARNING'}, "GenScene: prompt is empty.")
            return {'CANCELLED'}

        scene.genscene_busy = True
        # Request a redraw so the "AI is Thinking…" label shows immediately.
        # (In the synchronous MVP the Blender UI blocks during the urllib call,
        # but the flag is set correctly for the async upgrade path.)
        for area in context.screen.areas:
            area.tag_redraw()

        try:
            self._run(context, prompt)
        except Exception as exc:  # noqa: BLE001
            self.report({'ERROR'}, f"GenScene: {exc}")
            return {'FINISHED'}
        finally:
            scene.genscene_busy = False
            for area in context.screen.areas:
                area.tag_redraw()

        self.report({'INFO'}, "GenScene: scene built successfully.")
        return {'FINISHED'}

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def _run(self, context: bpy.types.Context, prompt: str) -> None:
        from ..ai.api_client import call_llm
        from ..ai.prompt_builder import build_messages
        from ..ai.code_extractor import run_with_retry
        from ..ai.asset_index import AssetIndex
        from ..lib.scene_serializer import serialize_scene
        from ..brushes.style_presets import PRESETS

        scene = context.scene

        scene_json = serialize_scene(selected_only=False)
        asset_catalogue = AssetIndex.get().for_prompt()

        style_key: str = getattr(scene, "genscene_style", "none")
        style_suffix = PRESETS.get(style_key, {}).get("prompt_suffix", "")

        messages = build_messages(
            user_prompt=prompt,
            scene_json=scene_json,
            asset_catalogue=asset_catalogue,
            style_suffix=style_suffix,
        )
        raw_code = call_llm(messages)
        run_with_retry(raw_code, original_messages=messages)


class GENSCENE_OT_refresh_assets(bpy.types.Operator):
    """Re-scan the asset library and rebuild the name index."""

    bl_idname = "genscene.refresh_assets"
    bl_label = "Refresh Asset Index"
    bl_description = "Re-scan the asset library path for new .blend files"
    bl_options = {'REGISTER'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        from ..ai.asset_index import AssetIndex
        idx = AssetIndex.refresh()
        self.report({'INFO'}, f"GenScene: indexed {len(idx)} assets.")
        return {'FINISHED'}


class GENSCENE_OT_copy_scene_json(bpy.types.Operator):
    """Copy the current scene JSON to the clipboard (debugging aid)."""

    bl_idname = "genscene.copy_scene_json"
    bl_label = "Copy Scene JSON"
    bl_description = "Serialize the scene and copy the JSON to the clipboard"
    bl_options = {'REGISTER'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        from ..lib.scene_serializer import serialize_scene
        json_text = serialize_scene(selected_only=False)
        context.window_manager.clipboard = json_text
        self.report({'INFO'}, "GenScene: scene JSON copied to clipboard.")
        return {'FINISHED'}


# ── Registration ──────────────────────────────────────────────────────────────

_CLASSES = [
    GENSCENE_OT_generate,
    GENSCENE_OT_refresh_assets,
    GENSCENE_OT_copy_scene_json,
]


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.genscene_prompt = StringProperty(
        name="Prompt",
        description="Natural-language instruction for the AI",
        default="",
    )
    bpy.types.Scene.genscene_busy = bpy.props.BoolProperty(
        name="Busy",
        description="True while a GenScene API call is in-flight",
        default=False,
    )
    bpy.types.Scene.genscene_style = bpy.props.EnumProperty(
        name="Style",
        description="Scene style preset",
        items=[
            ("none",             "None",             "No style modifier"),
            ("post_apocalyptic", "Post-Apocalyptic", "Scattered, chaotic, heavy physics"),
            ("clean_interior",   "Clean Interior",   "Neat, aligned, minimal rotation"),
            ("natural_outdoor",  "Natural Outdoor",  "Organic scatter, terrain-aware"),
        ],
        default="none",
    )


def unregister() -> None:
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.genscene_prompt
    del bpy.types.Scene.genscene_busy
    del bpy.types.Scene.genscene_style
