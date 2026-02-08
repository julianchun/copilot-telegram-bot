import os
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
