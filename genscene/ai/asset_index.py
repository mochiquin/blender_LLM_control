"""
ai/asset_index.py — Local asset library scanner and semantic name resolver.

Scanning strategy (two-pass)
─────────────────────────────
Pass 1 — filename stems:
  Walk ASSET_LIBRARY_PATH, add every .blend filename stem to the index.
  Fast, works without bpy, no file I/O beyond directory listing.

Pass 2 — object names inside each .blend (requires bpy at runtime):
  Open each file with bpy.data.libraries.load() in read-only mode and
  inspect data_from.objects WITHOUT actually loading any data.  This lets
  us index the object named "table" even though the file is called
  "test.asset.blend".

Both passes populate the same index:
  normalised_name → (absolute_filepath, original_object_name)

Resolution priority: exact normalised match → keyword overlap score.
The index is a singleton and can be refreshed via AssetIndex.refresh().
Its string representation (for_prompt()) is injected into the LLM system
prompt so the model knows which asset_id strings to use.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .. import config


# ── Library path helper ───────────────────────────────────────────────────────

def _get_lib_path() -> str:
    """Return asset library path: Blender preferences > config.py > empty."""
    try:
        import bpy
        # __package__ is "genscene.ai" (dev) or "bl_ext.user_default.genscene.ai"
        # (Extension).  Strip the last component to get the parent addon ID.
        addon_id = __package__.rsplit(".", 1)[0]
        addon = bpy.context.preferences.addons.get(addon_id)
        if addon:
            p = getattr(addon.preferences, "asset_library_path", "")
            if p:
                return p
    except Exception:  # noqa: BLE001
        pass
    return config.ASSET_LIBRARY_PATH


# ── Name normalisation ────────────────────────────────────────────────────────

def _normalise(name: str) -> str:
    """Lowercase, replace separators with spaces, strip version suffixes."""
    name = name.lower()
    name = re.sub(r"[_\-.]", " ", name)
    name = re.sub(r"\bv\d+\b", "", name)
    name = re.sub(r"\b\d{2,3}\b", "", name)
    return " ".join(name.split())


def _tokenise(text: str) -> set[str]:
    return set(_normalise(text).split())


# ── Keyword scorer ────────────────────────────────────────────────────────────

def _keyword_score(query_tokens: set[str], asset_tokens: set[str]) -> float:
    """Jaccard-like overlap between query and asset token sets."""
    if not query_tokens or not asset_tokens:
        return 0.0
    intersection = query_tokens & asset_tokens
    union = query_tokens | asset_tokens
    return len(intersection) / len(union)


# ── Singleton index ───────────────────────────────────────────────────────────

class AssetIndex:
    """Scanned, normalised index of all assets in the library.

    Internal structure
    ──────────────────
    _index:  dict[normalised_name, (filepath, object_name)]
        object_name is the exact name of the Blender object inside the file.
        For filename-stem entries it equals the stem itself.

    _display_names: dict[normalised_name, original_name]
        Human-readable name shown in the LLM prompt.
    """

    _instance: AssetIndex | None = None

    def __init__(self) -> None:
        self._index: dict[str, tuple[str, str]] = {}
        self._display_names: dict[str, str] = {}
        self._scan()

    # ── Class-level singleton ──────────────────────────────────────────────

    @classmethod
    def get(cls) -> AssetIndex:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def refresh(cls) -> AssetIndex:
        cls._instance = cls()
        return cls._instance

    # ── Scanning ──────────────────────────────────────────────────────────

    def _scan(self) -> None:
        """Walk the library and index assets by both filename stem and object name."""
        lib_root = _get_lib_path()
        if not lib_root or not os.path.isdir(lib_root):
            return

        # Lazy bpy import — not available outside Blender
        try:
            import bpy as _bpy
            _has_bpy = True
        except ImportError:
            _has_bpy = False

        for dirpath, _dirs, files in os.walk(lib_root):
            for fname in files:
                if not fname.endswith(".blend"):
                    continue
                full_path = os.path.join(dirpath, fname)
                stem = Path(fname).stem

                # Pass 1: index by filename stem
                norm_stem = _normalise(stem)
                self._index.setdefault(norm_stem, (full_path, stem))
                self._display_names.setdefault(norm_stem, stem)

                # Pass 2: peek inside to index by object names
                if not _has_bpy:
                    continue
                try:
                    with _bpy.data.libraries.load(full_path, link=False) as (src, _):
                        for obj_name in src.objects:
                            norm_obj = _normalise(obj_name)
                            # Object-name entry wins over filename-stem entry
                            self._index[norm_obj] = (full_path, obj_name)
                            self._display_names[norm_obj] = obj_name
                except Exception:  # noqa: BLE001
                    pass

    # ── Resolution ────────────────────────────────────────────────────────

    def find(self, query: str, threshold: float = 0.15) -> tuple[str, str] | None:
        """Return (filepath, object_name) for the best match, or None.

        Resolution order:
          1. Exact match on normalised query string.
          2. Best keyword-overlap score above threshold.

        Args:
            query: Human-readable label, e.g. "table" or "Wooden_Crate_v2".
            threshold: Minimum keyword score to accept (0–1).

        Returns:
            (absolute_blend_path, object_name_inside_file) or None.
        """
        if not self._index:
            return None

        norm_query = _normalise(query)
        if norm_query in self._index:
            return self._index[norm_query]

        q_tokens = _tokenise(query)
        best_score = 0.0
        best_match: tuple[str, str] | None = None

        for norm_name, entry in self._index.items():
            score = _keyword_score(q_tokens, set(norm_name.split()))
            if score > best_score:
                best_score = score
                best_match = entry

        if best_score >= threshold:
            return best_match

        return None

    def find_all(self, query: str, top_k: int = 5) -> list[tuple[str, str, float]]:
        """Return top-k matches as (filepath, object_name, score) sorted by score."""
        q_tokens = _tokenise(query)
        scored: list[tuple[str, str, float]] = []
        for norm_name, (path, obj_name) in self._index.items():
            score = _keyword_score(q_tokens, set(norm_name.split()))
            if score > 0:
                scored.append((path, obj_name, score))
        scored.sort(key=lambda x: x[2], reverse=True)
        return scored[:top_k]

    # ── Prompt serialisation ──────────────────────────────────────────────

    def for_prompt(self, max_entries: int = 80) -> str:
        """Return a sorted newline-separated list of asset names for the system prompt."""
        entries = list(self._display_names.values())[:max_entries]
        if not entries:
            return ""
        return "\n".join(sorted(set(entries)))

    def __len__(self) -> int:
        return len(self._index)

    def __repr__(self) -> str:
        return f"<AssetIndex: {len(self)} entries from '{_get_lib_path()}'>"
