#!/usr/bin/env python3
"""
build.py — Package GenScene as a Blender 5.0 Extension zip.

Usage
─────
    python build.py            # → dist/genscene-0.1.0.zip
    python build.py --out DIR  # custom output directory

Install
───────
1. Run:   python build.py
2. Open Blender 5.0
3. Edit > Preferences > Add-ons > ▾ (top-right dropdown) > Install from Disk…
4. Select:  dist/genscene-0.1.0.zip
5. Enable the "GenScene" checkbox that appears.

Remove
──────
Edit > Preferences > Add-ons > search "GenScene" > ▾ (expand) > Remove

Zip layout produced (Blender 5.0 Extension format)
───────────────────────────────────────────────────
  blender_manifest.toml     ← at zip root (required by Extensions platform)
  __init__.py
  config.py
  ai/__init__.py
  ai/api_client.py
  …

Files intentionally excluded from the zip
──────────────────────────────────────────
  config_template.py   (developer scaffold — not needed at runtime)
  __pycache__/         (compiled bytecode — Blender recompiles on first run)
  *.pyc / *.pyo
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).parent
_ADDON_DIR = _ROOT / "genscene"
_MANIFEST = _ADDON_DIR / "blender_manifest.toml"

# ── Exclusion rules ────────────────────────────────────────────────────────────

_EXCLUDE_NAMES = {
    "__pycache__",
    ".DS_Store",
    ".git",
    "config_template.py",   # dev-only scaffold
}

_EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".pyd"}


def _should_exclude(path: Path) -> bool:
    """Return True if this file/directory should be omitted from the zip."""
    for part in path.parts:
        if part in _EXCLUDE_NAMES:
            return True
    return path.suffix in _EXCLUDE_SUFFIXES


# ── Version parsing ────────────────────────────────────────────────────────────

def _read_version() -> str:
    text = _MANIFEST.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError(
            f"Could not parse 'version = \"...\"' from {_MANIFEST}"
        )
    return match.group(1)


# ── Build ──────────────────────────────────────────────────────────────────────

def build(out_dir: Path) -> Path:
    """Create the Extension zip and return its path."""
    if not _ADDON_DIR.is_dir():
        raise FileNotFoundError(f"Addon directory not found: {_ADDON_DIR}")
    if not _MANIFEST.is_file():
        raise FileNotFoundError(f"Manifest not found: {_MANIFEST}")

    out_dir.mkdir(parents=True, exist_ok=True)
    version = _read_version()
    zip_path = out_dir / f"genscene-{version}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src in sorted(_ADDON_DIR.rglob("*")):
            rel = src.relative_to(_ADDON_DIR)
            if _should_exclude(rel):
                continue
            if not src.is_file():
                continue
            # arcname is relative to _ADDON_DIR so files land at zip root,
            # which is what Blender's Extension platform requires.
            zf.write(src, arcname=rel)
            print(f"  + {rel}")

    return zip_path


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the GenScene Blender Extension zip",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--out",
        default="dist",
        metavar="DIR",
        help="Output directory (default: dist/)",
    )
    args = parser.parse_args()

    try:
        zip_path = build(Path(args.out))
    except Exception as exc:
        print(f"\n✗ Build failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\n✓ Built:  {zip_path.resolve()}")
    print()
    print("Install in Blender 5.0:")
    print("  Edit > Preferences > Add-ons > ▾ > Install from Disk…")
    print(f"  Select: {zip_path.resolve()}")
    print()
    print("Remove from Blender:")
    print('  Edit > Preferences > Add-ons > search "GenScene" > ▾ > Remove')


if __name__ == "__main__":
    main()
