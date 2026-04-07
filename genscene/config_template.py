import os

# config_template.py
# ─────────────────────────────────────────────────────────────────────────────
# 复制此文件并重命名为 config.py，然后填入你的私钥。
# config.py 已被 .gitignore 屏蔽，不会被推送到远程仓库。
#
# 推荐做法（更安全）：通过操作系统环境变量注入密钥，而非直接粘贴在文件里：
#   export GENSCENE_API_KEY="sk-..."
#   export GENSCENE_PROVIDER="openai"          # 或 "anthropic"
#   export GENSCENE_ASSET_LIB="/path/to/assets"
# ─────────────────────────────────────────────────────────────────────────────

# ── API credentials ───────────────────────────────────────────────────────────
API_KEY: str = os.environ.get("GENSCENE_API_KEY", "在这里填入你的 API Key")

# "openai" 或 "anthropic"
API_PROVIDER: str = os.environ.get("GENSCENE_PROVIDER", "openai")

# ── 模型选择 ──────────────────────────────────────────────────────────────────
OPENAI_MODEL: str = "gpt-4o"
ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"

# ── Asset 库路径 ───────────────────────────────────────────────────────────────
# 指向包含 .blend 资产文件的根目录，子目录会被递归扫描。
ASSET_LIBRARY_PATH: str = os.environ.get("GENSCENE_ASSET_LIB", "/Users/yourname/Documents/Blender/Assets")

# ── 物理模拟 ──────────────────────────────────────────────────────────────────
PHYSICS_FRAMES: int = 60

# ── 安全限制 ──────────────────────────────────────────────────────────────────
MAX_EXEC_RETRIES: int = 2

# ── API 端点 ──────────────────────────────────────────────────────────────────
OPENAI_ENDPOINT: str = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_ENDPOINT: str = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION: str = "2023-06-01"
