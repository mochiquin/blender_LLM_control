import os

# ── API credentials ───────────────────────────────────────────────────────────
# Set GENSCENE_API_KEY in your OS environment, or paste the key directly here
# (not recommended for shared files).
API_KEY: str = os.environ.get("GENSCENE_API_KEY", "")

# "openai" or "anthropic"
API_PROVIDER: str = os.environ.get("GENSCENE_PROVIDER", "openai")

# Model to use for each provider
OPENAI_MODEL: str = "gpt-4o"
ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"

# ── Asset library ─────────────────────────────────────────────────────────────
# Absolute path to the root folder that contains your .blend asset files.
# Sub-directories are scanned recursively.
ASSET_LIBRARY_PATH: str = os.environ.get("GENSCENE_ASSET_LIB", "")

# ── Physics settings ──────────────────────────────────────────────────────────
# Number of frames stepped during apply_physics_drop().
PHYSICS_FRAMES: int = 60

# ── Execution safety ──────────────────────────────────────────────────────────
# Maximum number of LLM self-correction retries on exec() failure.
MAX_EXEC_RETRIES: int = 2

# ── URL endpoints ─────────────────────────────────────────────────────────────
OPENAI_ENDPOINT: str = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_ENDPOINT: str = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION: str = "2023-06-01"
