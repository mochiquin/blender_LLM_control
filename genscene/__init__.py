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

import importlib
import sys

import bpy

# Submodules that must be reloaded when "Reload Scripts" is triggered so that
# source edits are picked up without restarting Blender.
_SUBMODULES = [
    "genscene.config",
    "genscene.lib.ground",
    "genscene.lib.spawn",
    "genscene.lib.physics",
    "genscene.lib.scene_serializer",
    "genscene.ai.asset_index",
    "genscene.ai.api_client",
    "genscene.ai.prompt_builder",
    "genscene.ai.code_extractor",
    "genscene.ai.dispatcher",
    "genscene.brushes.distribute",
    "genscene.brushes.style_presets",
    "genscene.ui.panel",
    "genscene.ui.operators",
]


def _reload_submodules() -> None:
    for name in _SUBMODULES:
        if name in sys.modules:
            importlib.reload(sys.modules[name])


def reload_all() -> None:
    """Force-reload all genscene submodules from disk.

    Call this at the top of any Blender text-editor script after editing
    source files, so Python picks up the latest code without restarting
    Blender or toggling the add-on::

        import genscene; genscene.reload_all()
        from genscene.ai.api_client import ping_test
        print(ping_test("ollama"))
    """
    _reload_submodules()


def register() -> None:
    _reload_submodules()
    from .ui import panel, operators
    panel.register()
    operators.register()


def unregister() -> None:
    from .ui import panel, operators
    operators.unregister()
    panel.unregister()


if __name__ == "__main__":
    register()
