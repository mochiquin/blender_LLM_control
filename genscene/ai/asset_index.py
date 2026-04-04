"""
ai/asset_index.py — Local asset library scanner and semantic name resolver.

Scans the configured asset library path for .blend files and builds a
normalised name → filepath index.  Provides two resolution strategies:

  1. Keyword match (always available): tokenise the query and score each
     asset name by how many query tokens it contains.
  2. Embedding match (optional, post-MVP): if sentence-transformers or a
     similar library is available in Blender's Python, use cosine similarity
     on pre-computed embeddings.  Falls back to keyword match gracefully.

The index is a singleton loaded once per Blender session and can be refreshed
via AssetIndex.refresh().  Its string representation (for_prompt()) is injected
into the LLM system prompt so the model knows which asset_id strings to use.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .. import config


# ── Name normalisation ────────────────────────────────────────────────────────

def _normalise(name: str) -> str:
    """Lowercase, replace separators with spaces, strip version suffixes."""
    name = name.lower()
    name = re.sub(r"[_\-.]", " ", name)
    # Strip trailing version tags like _v2, _v01, _001
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
    """Scanned, normalised index of all .blend assets in the library."""

    _instance: AssetIndex | None = None

    def __init__(self) -> None:
        # {normalised_name: absolute_path}
        self._index: dict[str, str] = {}
        # {normalised_name: original_stem}
        self._display_names: dict[str, str] = {}
        self._scan()

    # ── Class-level singleton ──────────────────────────────────────────────

    @classmethod
    def get(cls) -> AssetIndex:
        """Return the shared singleton, scanning on first access."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def refresh(cls) -> AssetIndex:
        """Force a rescan of the library and return the new index."""
        cls._instance = cls()
        return cls._instance

    # ── Scanning ──────────────────────────────────────────────────────────

    def _scan(self) -> None:
        """Walk ASSET_LIBRARY_PATH and index every .blend file found."""
        lib_root = config.ASSET_LIBRARY_PATH
        if not lib_root or not os.path.isdir(lib_root):
            return

        for dirpath, _dirs, files in os.walk(lib_root):
            for fname in files:
                if not fname.endswith(".blend"):
                    continue
                stem = Path(fname).stem
                norm = _normalise(stem)
                full_path = os.path.join(dirpath, fname)
                self._index[norm] = full_path
                self._display_names[norm] = stem

    # ── Resolution ────────────────────────────────────────────────────────

    def find(self, query: str, threshold: float = 0.15) -> str | None:
        """Return the best-matching asset file path for a semantic query.

        Args:
            query: A human-readable label, e.g. "rusty barrel" or "iron_barrel_v2".
            threshold: Minimum keyword score to accept a match (0–1).

        Returns:
            Absolute path to the best-matching .blend file, or None.
        """
        if not self._index:
            return None

        # Exact match on normalised name wins immediately
        norm_query = _normalise(query)
        if norm_query in self._index:
            return self._index[norm_query]

        # Keyword scoring
        q_tokens = _tokenise(query)
        best_score = 0.0
        best_path: str | None = None

        for norm_name, path in self._index.items():
            score = _keyword_score(q_tokens, set(norm_name.split()))
            if score > best_score:
                best_score = score
                best_path = path

        if best_score >= threshold:
            return best_path

        return None

    def find_all(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Return the top-k matches as (filepath, score) sorted by score."""
        q_tokens = _tokenise(query)
        scored: list[tuple[str, float]] = []
        for norm_name, path in self._index.items():
            score = _keyword_score(q_tokens, set(norm_name.split()))
            if score > 0:
                scored.append((path, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # ── Prompt serialisation ──────────────────────────────────────────────

    def for_prompt(self, max_entries: int = 80) -> str:
        """Return a newline-separated list of asset names for the system prompt.

        Keeps the catalogue short enough to fit in the context window.
        """
        entries = list(self._display_names.values())[:max_entries]
        if not entries:
            return ""
        return "\n".join(sorted(entries))

    def __len__(self) -> int:
        return len(self._index)

    def __repr__(self) -> str:
        return f"<AssetIndex: {len(self)} assets from '{config.ASSET_LIBRARY_PATH}'>"
