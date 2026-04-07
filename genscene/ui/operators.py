"""
ui/operators.py — Blender 5.0+ operators for the GenScene pipeline.

Async design
────────────
Clicking "Generate" no longer freezes Blender.

1. execute() gathers scene data on the main thread (bpy reads are instant),
   builds the message list, then launches a background thread that does ONLY
   the network round-trip (call_llm).

2. A bpy.app.timers callback polls for the result at 0.1-second intervals.
   When the LLM responds, the timer runs run_with_retry() (which dispatches
   bpy operations) on the main thread — the only safe place for bpy writes.

3. genscene_status on the scene gives the panel a live status string to
   display: "Thinking…", "Dispatching…", "Done ✓", or an error message.

Undo note
─────────
Because the actual bpy writes happen inside a timer callback (not inside
operator.execute), they form individual undo steps rather than one grouped
step.  This is a known trade-off of the async approach.  For a single-undo
grouped experience switch back to the synchronous _run() path.
"""

from __future__ import annotations

import threading
import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty

# ADDON_ID is "genscene" in dev mode and "bl_ext.user_default.genscene" when
# installed via the Extensions platform.  Derive it from __package__ so it is
# always correct regardless of how Blender loaded the add-on.
# __package__ here is "genscene.ui" or "bl_ext.user_default.genscene.ui";
# strip the last component to get the parent package name.
_ADDON_ID: str = __package__.rsplit(".", 1)[0]


# ── Module-level state ────────────────────────────────────────────────────────
# _pending maps scene.name → result dict (or None while worker is still running).
# Clearing _pending during unregister() causes every active timer to self-cancel
# on its next tick — the only safe way to stop bpy.app.timers closures.
_pending: dict[str, dict | None] = {}


def _tag_redraw_all() -> None:
    """Request a redraw of all areas; safe to call from a timer callback."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:  # noqa: BLE001
        pass


# ── Addon Preferences ─────────────────────────────────────────────────────────

class GENSCENE_Preferences(bpy.types.AddonPreferences):
    """Persistent settings stored in Blender's user preferences (.userpref.blend).

    Access via: Edit > Preferences > Add-ons > GenScene (expand ▾).
    """

    bl_idname = _ADDON_ID

    provider: EnumProperty(  # type: ignore[assignment]
        name="AI Provider",
        description="Which LLM backend to use for scene generation",
        items=[
            ("ollama",    "Ollama (Local)",  "Local LLM via Ollama — no API key required"),
            ("openai",    "OpenAI",          "GPT-4o via OpenAI API — requires an API key"),
            ("anthropic", "Anthropic",       "Claude via Anthropic API — requires an API key"),
        ],
        default="ollama",
    )
    api_key: StringProperty(  # type: ignore[assignment]
        name="API Key",
        description="OpenAI or Anthropic secret key (sk-…)",
        subtype="PASSWORD",
        default="",
    )
    ollama_model: StringProperty(  # type: ignore[assignment]
        name="Model",
        description="Ollama model tag to use (must be pulled first: ollama pull <model>)",
        default="gemma3:4b",
    )
    ollama_url: StringProperty(  # type: ignore[assignment]
        name="Ollama URL",
        description="Ollama API endpoint (change if Ollama runs on a remote machine)",
        default="http://localhost:11434/api/chat",
    )
    asset_library_path: StringProperty(  # type: ignore[assignment]
        name="Asset Library Path",
        description="Folder containing your .blend asset files (sub-folders are scanned recursively)",
        default="",
        subtype="DIR_PATH",
    )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout

        # ── LLM provider ──────────────────────────────────────────────────────
        row = layout.row(align=True)
        row.label(text="Provider:")
        row.prop(self, "provider", text="")

        layout.separator(factor=0.6)

        if self.provider == "ollama":
            box = layout.box()
            box.label(text="Ollama Settings", icon="NETWORK_DRIVE")
            box.prop(self, "ollama_model")
            box.prop(self, "ollama_url")
            box.separator(factor=0.4)
            box.operator("genscene.ping_test", text="Test Connection", icon="PLAY")
        else:
            provider_label = "OpenAI" if self.provider == "openai" else "Anthropic"
            box = layout.box()
            box.label(text=f"{provider_label} Settings", icon="KEY_HLT")
            box.prop(self, "api_key")
            box.separator(factor=0.4)
            box.operator("genscene.ping_test", text="Test Connection", icon="PLAY")

        layout.separator(factor=0.8)

        # ── Asset library ──────────────────────────────────────────────────────
        box2 = layout.box()
        box2.label(text="Asset Library", icon="ASSET_MANAGER")
        box2.prop(self, "asset_library_path", text="Path")
        row2 = box2.row(align=True)
        row2.operator("genscene.refresh_assets", text="Refresh Index", icon="FILE_REFRESH")


# ── Operators ─────────────────────────────────────────────────────────────────

class GENSCENE_OT_ping_test(bpy.types.Operator):
    """Send a one-word test message to verify the API connection."""

    bl_idname = "genscene.ping_test"
    bl_label = "Ping Test"
    bl_description = "Send a minimal request to verify the LLM connection is working"
    bl_options = {'REGISTER'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        from ..ai.api_client import ping_test
        try:
            result = ping_test()
            self.report({'INFO'}, f"GenScene: {result}")
        except Exception as exc:  # noqa: BLE001
            self.report({'ERROR'}, f"GenScene: {exc}")
        return {'FINISHED'}


class GENSCENE_OT_generate(bpy.types.Operator):
    """Generate Blender scene objects from a natural-language description."""

    bl_idname = "genscene.generate"
    bl_label = "Generate"
    bl_description = "Send the prompt to the AI and build the scene"
    bl_options = {'REGISTER'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        prompt: str = scene.genscene_prompt.strip()

        if not prompt:
            self.report({'WARNING'}, "GenScene: prompt is empty.")
            return {'CANCELLED'}

        if scene.genscene_busy:
            self.report({'WARNING'}, "GenScene: already running.")
            return {'CANCELLED'}

        # ── Imports (lazy to keep Blender load time fast) ─────────────────────
        from ..ai.api_client import call_llm
        from ..ai.prompt_builder import build_messages
        from ..ai.code_extractor import run_with_retry
        from ..ai.asset_index import AssetIndex
        from ..lib.scene_serializer import serialize_scene
        from ..brushes.style_presets import PRESETS

        # ── Step 1: gather context on the main thread ─────────────────────────
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

        # ── Step 2: set busy + status, then kick off background thread ────────
        scene_name = scene.name
        scene.genscene_busy = True
        scene.genscene_status = "Thinking…"
        _pending[scene_name] = None  # None = worker not yet done
        _tag_redraw_all()

        def _worker() -> None:
            try:
                raw_code = call_llm(messages)
                _pending[scene_name] = {
                    "ok": True,
                    "raw_code": raw_code,
                    "messages": messages,
                }
            except Exception as exc:  # noqa: BLE001
                _pending[scene_name] = {"ok": False, "error": str(exc)}

        # ── Step 3: timer polls until worker completes, then dispatches ───────
        def _on_result() -> float | None:
            # If the addon was unregistered while waiting, _pending was cleared.
            # A missing key means we should abort and let the timer unregister.
            if scene_name not in _pending:
                return None

            result = _pending[scene_name]
            if result is None:
                return 0.1  # worker still running — check again soon

            _pending.pop(scene_name, None)

            # Guard against the scene being deleted while we waited.
            sc = bpy.data.scenes.get(scene_name)
            if sc is None:
                return None

            # Guard: if properties were removed (addon disabled mid-flight), bail.
            if not hasattr(sc, "genscene_busy"):
                return None

            if not result["ok"]:
                sc.genscene_busy = False
                sc.genscene_status = f"Error: {result['error']}"
                _tag_redraw_all()
                return None

            sc.genscene_status = "Dispatching…"
            _tag_redraw_all()

            try:
                run_with_retry(result["raw_code"], original_messages=result["messages"])
                sc.genscene_status = "Done ✓"
            except Exception as exc:  # noqa: BLE001
                sc.genscene_status = f"Error: {exc}"
            finally:
                sc.genscene_busy = False
                _tag_redraw_all()

            return None  # returning None unregisters the timer

        threading.Thread(target=_worker, daemon=True).start()
        bpy.app.timers.register(_on_result, first_interval=0.1)

        return {'FINISHED'}


class GENSCENE_OT_clear_scene(bpy.types.Operator):
    """Delete all non-essential mesh/curve objects from the scene."""

    bl_idname = "genscene.clear_scene"
    bl_label = "Clear Scene"
    bl_description = "Remove all mesh and curve objects (keeps cameras and lights)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        _KEEP_TYPES = {'CAMERA', 'LIGHT', 'LIGHT_PROBE', 'SPEAKER'}
        targets = [
            obj for obj in context.scene.objects
            if obj.type not in _KEEP_TYPES
        ]
        count = len(targets)
        for obj in targets:
            bpy.data.objects.remove(obj, do_unlink=True)

        self.report({'INFO'}, f"GenScene: removed {count} object(s).")
        return {'FINISHED'}


class GENSCENE_OT_quick_preset(bpy.types.Operator):
    """Append a preset suffix to the current prompt and generate."""

    bl_idname = "genscene.quick_preset"
    bl_label = "Quick Preset"
    bl_description = "Append a modifier to the prompt and run Generate"
    bl_options = {'REGISTER'}

    suffix: StringProperty(
        name="Suffix",
        description="Text to append to the current prompt before generating",
        default="",
    )  # type: ignore[assignment]

    def execute(self, context: bpy.types.Context) -> set[str]:
        scene = context.scene
        base = scene.genscene_prompt.strip()
        if not base:
            self.report({'WARNING'}, "GenScene: prompt is empty.")
            return {'CANCELLED'}

        scene.genscene_prompt = f"{base}，{self.suffix}"
        return bpy.ops.genscene.generate()


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
    GENSCENE_Preferences,
    GENSCENE_OT_ping_test,
    GENSCENE_OT_generate,
    GENSCENE_OT_clear_scene,
    GENSCENE_OT_quick_preset,
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
    bpy.types.Scene.genscene_status = bpy.props.StringProperty(
        name="Status",
        description="Last status message from the GenScene pipeline",
        default="",
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
    # Clearing _pending causes all active _on_result timers to exit on their
    # next tick (they check `scene_name not in _pending` as their first guard).
    _pending.clear()

    # Reset busy flag on every open scene so the UI is not stuck on "Thinking…"
    # even after the addon is removed.
    for scene in bpy.data.scenes:
        try:
            scene.genscene_busy = False
        except AttributeError:
            pass

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)

    for prop in ("genscene_prompt", "genscene_busy", "genscene_status", "genscene_style"):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
