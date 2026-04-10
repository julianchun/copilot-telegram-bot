import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
_raw_user_id = os.getenv("ALLOWED_USER_ID")
ALLOWED_USER_ID: int | None = int(_raw_user_id) if _raw_user_id else None
WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Optional: overrides CLI auth

# Resolve Workspace Root
WORKSPACE_PATH = Path(WORKSPACE_ROOT).resolve()

# Granted Projects (comma-separated absolute paths)
GRANTED_PROJECTS_STR = os.getenv("GRANTED_PROJECTS", "")
GRANTED_PROJECT_PATHS = [Path(p.strip()).resolve() for p in GRANTED_PROJECTS_STR.split(",") if p.strip()]

# Validate and log granted projects
for gp in GRANTED_PROJECT_PATHS:
    if gp.exists():
        logger.info(f"Granted Project: {gp}")
    else:
        logger.warning(f"Granted Project does not exist: {gp}")

if not TELEGRAM_BOT_TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN is not set!")

if not ALLOWED_USER_ID:
    logger.warning("ALLOWED_USER_ID is not set!")

# Log GitHub authentication method
if GITHUB_TOKEN:
    logger.info("🔑 Using GITHUB_TOKEN from environment")
else:
    logger.info("🔑 Using GitHub CLI auth (no GITHUB_TOKEN provided)")

# ── Shared Constants ──────────────────────────────────────────────────────────

DEFAULT_MODEL = "gpt-4.1"          # model used when user hasn't chosen one
INTERACTION_TIMEOUT = 300          # seconds — timeout for user interactions (permission, input)
MAX_TRACKED_FILES = 200            # max files tracked in SessionContext before pruning
TRACKED_FILES_PRUNE_SIZE = 100     # keep last N files when pruning
FILE_CONTENT_LIMIT = 100_000       # max characters when reading file content
TELEGRAM_MSG_LIMIT = 4000          # safe margin below Telegram's 4096 char limit
PERMISSION_TIMEOUT = 60.0          # seconds — timeout for tool permission requests

# ── MCP Server Configuration ─────────────────────────────────────────────────

MCP_CONFIG_PATH = Path(os.getenv(
    "MCP_CONFIG_PATH",
    Path.home() / ".copilot" / "mcp-config.json",
))

MCP_SERVERS: dict | None = None

if MCP_CONFIG_PATH.exists():
    try:
        with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
            _mcp_data = json.load(f)
        MCP_SERVERS = _mcp_data.get("mcpServers")
        if MCP_SERVERS:
            logger.info(f"🔌 Loaded {len(MCP_SERVERS)} MCP server(s) from {MCP_CONFIG_PATH}: {', '.join(MCP_SERVERS.keys())}")
        else:
            logger.info(f"📄 MCP config found at {MCP_CONFIG_PATH} but no servers defined")
    except Exception as e:
        logger.warning(f"⚠️ Failed to load MCP config from {MCP_CONFIG_PATH}: {e}")
else:
    logger.info(f"📄 No MCP config found at {MCP_CONFIG_PATH}")
