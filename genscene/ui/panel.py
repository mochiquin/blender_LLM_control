"""
ui/panel.py — GenScene N-panel sidebar for Blender's 3-D Viewport.

Appears under View3D > Sidebar (N key) > GenScene tab.

Layout:
  ┌─────────────────────────────────────────┐
  │  GenScene                               │
  ├─────────────────────────────────────────┤
  │  ● Thinking… / Done ✓ / Error: …       │  ← live status (only when set)
  ├─────────────────────────────────────────┤
  │  Prompt  [_____________________________]│
  │  Style   [None                       ▾]│
  │  [ ⏵  Generate  /  AI is Thinking…   ] │
  ├─────────────────────────────────────────┤
  │  Quick Presets                          │
  │  [⊕ Random Scatter] [✕ Clear Scene]    │
  ├─────────────────────────────────────────┤
  │  ▸ Scene Tools                          │
  │    [ Copy Scene JSON ]                  │
  │    [ Refresh Asset Index ]              │
  └─────────────────────────────────────────┘
"""

from __future__ import annotations

import bpy


# Status icon mapping keyed on first characters of genscene_status
_STATUS_ICONS: tuple[tuple[str, str], ...] = (
    ("Thinking",     "SORTTIME"),
    ("Dispatching",  "PLAY"),
    ("Done",         "CHECKMARK"),
    ("Error",        "ERROR"),
)

_DEFAULT_STATUS_ICON = "INFO"


def _status_icon(status: str) -> str:
    for prefix, icon in _STATUS_ICONS:
        if status.startswith(prefix):
            return icon
    return _DEFAULT_STATUS_ICON


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
        status: str = getattr(scene, "genscene_status", "")

        # ── Live status bar ───────────────────────────────────────────────────
        if status:
            row = layout.row(align=True)
            row.alert = status.startswith("Error")
            row.label(text=status, icon=_status_icon(status))
            layout.separator(factor=0.4)

        # ── Prompt input ──────────────────────────────────────────────────────
        col = layout.column(align=True)
        col.label(text="Prompt:")
        col.prop(scene, "genscene_prompt", text="")

        layout.separator(factor=0.5)

        # ── Style preset ──────────────────────────────────────────────────────
        layout.prop(scene, "genscene_style", text="Style")

        layout.separator(factor=0.8)

        # ── Generate button ───────────────────────────────────────────────────
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.enabled = not is_busy
        row.operator(
            "genscene.generate",
            text="AI is Thinking…" if is_busy else "Generate",
            icon="SORTTIME" if is_busy else "PLAY",
        )

        # ── Settings shortcut ─────────────────────────────────────────────────
        layout.separator(factor=0.4)
        row2 = layout.row(align=True)
        row2.operator(
            "screen.userpref_show",
            text="Settings",
            icon="PREFERENCES",
        ).section = 'ADDONS'


class VIEW3D_PT_GenScene_Presets(bpy.types.Panel):
    """Quick preset shortcuts for common scene operations."""

    bl_label = "Quick Presets"
    bl_idname = "VIEW3D_PT_GenScene_Presets"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GenScene"
    bl_parent_id = "VIEW3D_PT_GenScene"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        is_busy: bool = context.scene.genscene_busy

        # ── Scatter modifier ──────────────────────────────────────────────────
        col = layout.column(align=True)
        col.label(text="Append to prompt & run:")

        row = col.row(align=True)
        row.enabled = not is_busy

        op = row.operator(
            "genscene.quick_preset",
            text="Random Scatter",
            icon="PARTICLES",
        )
        op.suffix = "随机旋转和微调比例，让物体显得自然散落"

        op2 = row.operator(
            "genscene.quick_preset",
            text="Ground Snap",
            icon="TRIA_DOWN",
        )
        op2.suffix = "将所有物体贴合地面"

        layout.separator(factor=0.5)

        # ── Destructive actions ───────────────────────────────────────────────
        col2 = layout.column(align=True)
        col2.label(text="Scene management:")
        col2.operator(
            "genscene.clear_scene",
            text="Clear Scene",
            icon="TRASH",
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
        layout.operator("genscene.copy_scene_json",  icon="COPYDOWN")
        layout.operator("genscene.refresh_assets",   icon="FILE_REFRESH")


# ── Registration ──────────────────────────────────────────────────────────────

_CLASSES = [
    VIEW3D_PT_GenScene,
    VIEW3D_PT_GenScene_Presets,
    VIEW3D_PT_GenScene_Tools,
]


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
