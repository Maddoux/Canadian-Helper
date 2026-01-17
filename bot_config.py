"""
Bot configuration and constants.
"""

import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =============================================================================
# BOT CONFIGURATION
# =============================================================================

# Discord Configuration
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# These will be loaded from config database, fallback to env vars if not set
CANADA_ROLE_ID = int(os.getenv("CANADA_ROLE_ID", "1161079999962439751"))  # Fallback only

# Guild Restriction - Bot only works in this guild
ALLOWED_GUILD_ID = 654458344781774879

# Logging Configuration
LOGGING_LEVEL = logging.INFO

# File Paths
DATA_DIR = "data"
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
ROLES_FILE = os.path.join(DATA_DIR, "allowed_roles.json")
WARNINGS_FILE = os.path.join(DATA_DIR, "warnings.json")
BANNED_WORDS_FILE = "swearWords.txt"

# Channel IDs
WARNING_LOG_CHANNEL_ID = 1307310035411406898

# Rule Violations Options
RULE_VIOLATIONS = [
    "§1 - PG-13 server, follow Discord Community Guidelines",
    "§2 - No discriminatory or derogatory language", 
    "§3 - No harassment or unauthorized recordings",
    "§4 - No spam or flooding chat",
    "§5 - No ghost ping or mass ping",
    "§6 - No election fraud participation",
    "§7 - No hacking server or users",
    "§8 - No penalty evasion or multiple accounts",
    "§9 - No lying to staff",
    "§10 - No misrepresentation of yourself or others",
    "§11 - No OOC information in roleplay",
    "§12 - No character manipulation for unfair advantage",
    "§13 - No trolling or toxic behavior",
    "§14 - No server advertising",
    "§15 - No alternate accounts for advantage/avoidance",
    "Other"
]

# =============================================================================
# DYNAMIC CONFIGURATION HELPERS
# =============================================================================

def get_canada_role_id():
    """Get the Canada role ID from config, fallback to env var."""
    try:
        from data_manager import get_canada_role_id_str
        config_value = get_canada_role_id_str()
        if config_value:
            return int(config_value)
    except (ImportError, ValueError):
        pass
    return CANADA_ROLE_ID

# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging():
    """Set up logging configuration."""
    logging.basicConfig(
        level=LOGGING_LEVEL,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler()
        ]
    )
    
    # Set discord.py logging to WARNING to reduce noise
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.http').setLevel(logging.WARNING)
