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

# ADDON_ID is the package name as Blender sees it:
#   - Dev / legacy mode:  "genscene"
#   - Extension platform: "bl_ext.user_default.genscene"
# __name__ inside __init__.py always equals the package name, regardless of
# how Blender loaded the extension.
ADDON_ID: str = __name__

# Build submodule names dynamically so they match the correct package prefix
# under both dev mode and the Extensions platform.
_SUBMODULE_SUFFIXES = [
    "config",
    "lib.ground",
    "lib.spawn",
    "lib.physics",
    "lib.scene_serializer",
    "ai.asset_index",
    "ai.api_client",
    "ai.prompt_builder",
    "ai.code_extractor",
    "ai.dispatcher",
    "brushes.distribute",
    "brushes.style_presets",
    "ui.panel",
    "ui.operators",
]
_SUBMODULES = [f"{ADDON_ID}.{s}" for s in _SUBMODULE_SUFFIXES]


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
    from .ui import operators, panel
    operators.register()
    panel.register()


def unregister() -> None:
    from .ui import operators, panel
    # operators.unregister() cancels in-flight timers and removes scene properties
    # before panel classes are torn down — order matters.
    try:
        operators.unregister()
    except Exception as exc:  # noqa: BLE001
        print(f"[GenScene] operators.unregister() error (ignored): {exc}")
    try:
        panel.unregister()
    except Exception as exc:  # noqa: BLE001
        print(f"[GenScene] panel.unregister() error (ignored): {exc}")


if __name__ == "__main__":
    register()
