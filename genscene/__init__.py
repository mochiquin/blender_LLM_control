# bl_info is read by Blender < 4.2 (legacy add-on mode).
# Blender 4.2+ uses blender_manifest.toml instead; both can coexist safely.
bl_info = {
    "name": "GenScene",
    "author": "GenScene Contributors",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > GenScene",
    "description": "AI-driven scene builder: describe a scene in plain language and watch it appear.",
    "category": "3D View",
}

import bpy


def register() -> None:
    from .ui import panel, operators
    panel.register()
    operators.register()


def unregister() -> None:
    from .ui import panel, operators
    operators.unregister()
    panel.unregister()


if __name__ == "__main__":
    register()
