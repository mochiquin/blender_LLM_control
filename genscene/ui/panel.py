"""
ui/panel.py — GenScene N-panel sidebar for Blender's 3-D Viewport.

Appears under View3D > Sidebar (N key) > GenScene tab.

Layout:
  ┌─────────────────────────────────┐
  │  GenScene                       │
  ├─────────────────────────────────┤
  │  Prompt  [___________________]  │
  │  Style   [None          ▾]      │
  │  [ Generate / AI is Thinking… ] │
  ├─────────────────────────────────┤
  │  ▸ Scene Tools                  │
  │    [ Copy Scene JSON ]          │
  │    [ Refresh Asset Index ]      │
  └─────────────────────────────────┘
"""

from __future__ import annotations

import bpy


class VIEW3D_PT_GenScene(bpy.types.Panel):
    """Main GenScene panel in the N-panel sidebar."""

    bl_label = "GenScene"
    bl_idname = "VIEW3D_PT_GenScene"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GenScene"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        scene = context.scene
        is_busy: bool = scene.genscene_busy

        # ── Prompt input ──────────────────────────────────────────────────────
        col = layout.column(align=True)
        col.label(text="Prompt:")
        col.prop(scene, "genscene_prompt", text="")

        layout.separator(factor=0.5)

        # ── Style preset ──────────────────────────────────────────────────────
        layout.prop(scene, "genscene_style", text="Style")

        layout.separator(factor=0.8)

        # ── Generate button — disabled + relabelled while busy ────────────────
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.enabled = not is_busy
        row.operator(
            "genscene.generate",
            text="AI is Thinking…" if is_busy else "Generate",
            icon="PLAY" if not is_busy else "SORTTIME",
        )


class VIEW3D_PT_GenScene_Tools(bpy.types.Panel):
    """Collapsible sub-panel with developer / diagnostic tools."""

    bl_label = "Scene Tools"
    bl_idname = "VIEW3D_PT_GenScene_Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GenScene"
    bl_parent_id = "VIEW3D_PT_GenScene"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.operator("genscene.copy_scene_json",   icon="COPYDOWN")
        layout.operator("genscene.refresh_assets",    icon="FILE_REFRESH")


# ── Registration ──────────────────────────────────────────────────────────────

_CLASSES = [
    VIEW3D_PT_GenScene,
    VIEW3D_PT_GenScene_Tools,
]


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
