"""
JSON-based data management system for the Canadian Helper bot.
Replaces the MySQL database with JSON file storage.
"""

import json
import os
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from bot_config import DATA_DIR, LOGS_FILE, CONFIG_FILE, ROLES_FILE, ALLOWED_GUILD_ID, WARNINGS_FILE

# Punishment config file path
PUNISHMENT_CONFIG_FILE = os.path.join(DATA_DIR, "punishment_config.json")

# Thread lock for file operations
file_lock = threading.Lock()

# =============================================================================
# FILE SYSTEM SETUP
# =============================================================================

def init_data_storage():
    """Initialize data storage directories and files."""
    # Create data directory if it doesn't exist
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Initialize default data files if they don't exist
    if not os.path.exists(LOGS_FILE):
        save_json(LOGS_FILE, {"logs": [], "next_log_id": 1})
    
    if not os.path.exists(CONFIG_FILE):
        save_json(CONFIG_FILE, {})
    
    if not os.path.exists(ROLES_FILE):
        save_json(ROLES_FILE, {})
    
    if not os.path.exists(WARNINGS_FILE):
        save_json(WARNINGS_FILE, {"warnings": [], "next_warning_id": 1})
    
    logging.info("Data storage initialized successfully.")

# =============================================================================
# JSON FILE OPERATIONS
# =============================================================================

def load_json(file_path: str) -> Dict[str, Any]:
    """Load JSON data from file with error handling."""
    try:
        with file_lock:
            if not os.path.exists(file_path):
                return {}
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Error loading JSON from {file_path}: {e}")
        return {}

def save_json(file_path: str, data: Dict[str, Any]) -> bool:
    """Save JSON data to file with error handling."""
    try:
        with file_lock:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Write to temporary file first, then rename for atomic operation
            temp_path = file_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            os.replace(temp_path, file_path)
            return True
    except (IOError, OSError) as e:
        logging.error(f"Error saving JSON to {file_path}: {e}")
        return False

# =============================================================================
# LOG MANAGEMENT FUNCTIONS
# =============================================================================

def create_log(guild_id: int, user_id: int, rule_violation: str, description: str, 
               punishment: str, release_time: Optional[int] = None, 
               punishment_start: Optional[int] = None, moderator_id: Optional[int] = None) -> int:
    """Create a new log entry and return the log number."""
    if punishment_start is None:
        punishment_start = int(datetime.now(timezone.utc).timestamp())
    
    data = load_json(LOGS_FILE)
    
    # Get next log number for this guild
    guild_logs = [log for log in data.get("logs", []) 
                  if log.get("guild_id") == guild_id and not log.get("retracted", False)]
    log_number = max([log.get("log_number", 0) for log in guild_logs], default=0) + 1
    
    # Create new log entry
    log_entry = {
        "id": data.get("next_log_id", 1),
        "log_number": log_number,
        "guild_id": guild_id,
        "user_id": user_id,
        "rule_violation": rule_violation,
        "description": description,
        "punishment": punishment,
        "release_time": release_time,
        "punishment_start": punishment_start,
        "moderator_id": moderator_id,
        "retracted": False,
        "message_id": None,
        "created_at": int(datetime.now(timezone.utc).timestamp())
    }
    
    # Add log to data
    if "logs" not in data:
        data["logs"] = []
    data["logs"].append(log_entry)
    data["next_log_id"] = data.get("next_log_id", 1) + 1
    
    # Save data
    if save_json(LOGS_FILE, data):
        return log_number
    else:
        raise Exception("Failed to save log data")

def get_log(log_number: int, guild_id: int) -> Optional[Tuple]:
    """Get a log entry by log number and guild ID."""
    data = load_json(LOGS_FILE)
    
    for log in data.get("logs", []):
        if log.get("log_number") == log_number and log.get("guild_id") == guild_id:
            return (
                log.get("user_id"),
                log.get("rule_violation"),
                log.get("description"),
                log.get("punishment"),
                log.get("message_id"),
                log.get("guild_id"),
                log.get("release_time"),
                log.get("punishment_start"),
                log.get("retracted", False),
                log.get("moderator_id")
            )
    return None

def update_log(log_number: int, guild_id: int, user_id: Optional[int] = None, 
               rule_violation: Optional[str] = None, description: Optional[str] = None,
               punishment: Optional[str] = None, release_time: Optional[int] = None) -> bool:
    """Update a log entry. Returns True if successful."""
    data = load_json(LOGS_FILE)
    
    for log in data.get("logs", []):
        if log.get("log_number") == log_number and log.get("guild_id") == guild_id:
            # Update only provided fields
            if user_id is not None:
                log["user_id"] = user_id
            if rule_violation is not None:
                log["rule_violation"] = rule_violation
            if description is not None:
                log["description"] = description
            if punishment is not None:
                log["punishment"] = punishment
            if release_time is not None:
                log["release_time"] = release_time
            
            log["updated_at"] = int(datetime.now(timezone.utc).timestamp())
            return save_json(LOGS_FILE, data)
    
    return False

def delete_log(log_number: int, guild_id: int) -> bool:
    """Delete a log entry. Returns True if successful."""
    data = load_json(LOGS_FILE)
    
    # Find and remove the log
    original_count = len(data.get("logs", []))
    data["logs"] = [log for log in data.get("logs", []) 
                    if not (log.get("log_number") == log_number and log.get("guild_id") == guild_id)]
    
    if len(data["logs"]) < original_count:
        return save_json(LOGS_FILE, data)
    return False

def retract_log(log_number: int, guild_id: int, retract: bool = True) -> bool:
    """Retract or unretract a log entry. Returns True if successful."""
    data = load_json(LOGS_FILE)
    
    for log in data.get("logs", []):
        if log.get("log_number") == log_number and log.get("guild_id") == guild_id:
            log["retracted"] = retract
            if retract:
                log["release_time"] = None
            log["updated_at"] = int(datetime.now(timezone.utc).timestamp())
            return save_json(LOGS_FILE, data)
    
    return False

def update_log_message_id(log_number: int, guild_id: int, message_id: int) -> bool:
    """Update the message ID for a log entry."""
    data = load_json(LOGS_FILE)
    
    for log in data.get("logs", []):
        if log.get("log_number") == log_number and log.get("guild_id") == guild_id:
            log["message_id"] = message_id
            return save_json(LOGS_FILE, data)
    
    return False

def get_user_punishments(user_id: int, guild_id: int, include_retracted: bool = True) -> List[Tuple]:
    """Get all punishments for a user."""
    data = load_json(LOGS_FILE)
    punishments = []
    
    for log in data.get("logs", []):
        if log.get("user_id") == user_id and log.get("guild_id") == guild_id:
            if include_retracted or not log.get("retracted", False):
                punishments.append((
                    log.get("log_number"),
                    log.get("rule_violation"),
                    log.get("description"),
                    log.get("retracted", False)
                ))
    
    return punishments

def get_punishment_count(user_id: int, guild_id: int) -> int:
    """Get the count of non-retracted punishments for a user."""
    data = load_json(LOGS_FILE)
    count = 0
    
    for log in data.get("logs", []):
        if (log.get("user_id") == user_id and 
            log.get("guild_id") == guild_id and 
            not log.get("retracted", False)):
            count += 1
    
    return count

# =============================================================================
# WARNING MANAGEMENT FUNCTIONS
# =============================================================================

def create_warning(guild_id: int, user_id: int, reason: str, moderator_id: int) -> int:
    """Create a new warning entry and return the warning number."""
    data = load_json(WARNINGS_FILE)
    
    if "warnings" not in data:
        data["warnings"] = []
    if "next_warning_id" not in data:
        data["next_warning_id"] = 1
    
    # Get next warning number for this guild
    guild_warnings = [w for w in data.get("warnings", []) if w.get("guild_id") == guild_id]
    warning_number = max([w.get("warning_number", 0) for w in guild_warnings], default=0) + 1
    
    # Create new warning entry
    warning_entry = {
        "id": data.get("next_warning_id", 1),
        "warning_number": warning_number,
        "guild_id": guild_id,
        "user_id": user_id,
        "reason": reason,
        "moderator_id": moderator_id,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        "message_id": None
    }
    
    data["warnings"].append(warning_entry)
    data["next_warning_id"] = data.get("next_warning_id", 1) + 1
    
    if save_json(WARNINGS_FILE, data):
        return warning_number
    return -1

def delete_warning(warning_number: int, guild_id: int) -> bool:
    """Delete a warning entry. Returns True if successful."""
    data = load_json(WARNINGS_FILE)
    
    # Find and remove the warning
    original_count = len(data.get("warnings", []))
    data["warnings"] = [w for w in data.get("warnings", []) 
                        if not (w.get("warning_number") == warning_number and w.get("guild_id") == guild_id)]
    
    if len(data["warnings"]) < original_count:
        return save_json(WARNINGS_FILE, data)
    return False

def get_warning(warning_number: int, guild_id: int) -> Optional[Dict[str, Any]]:
    """Get a specific warning by number."""
    data = load_json(WARNINGS_FILE)
    
    for warning in data.get("warnings", []):
        if warning.get("warning_number") == warning_number and warning.get("guild_id") == guild_id:
            return warning
    return None

def update_warning_message_id(warning_number: int, guild_id: int, message_id: int) -> bool:
    """Update the message ID for a warning entry."""
    data = load_json(WARNINGS_FILE)
    
    for warning in data.get("warnings", []):
        if warning.get("warning_number") == warning_number and warning.get("guild_id") == guild_id:
            warning["message_id"] = message_id
            return save_json(WARNINGS_FILE, data)
    
    return False

def get_user_warnings(user_id: int, guild_id: int) -> List[Tuple]:
    """Get all warnings for a user."""
    data = load_json(WARNINGS_FILE)
    warnings = []
    
    for warning in data.get("warnings", []):
        if warning.get("user_id") == user_id and warning.get("guild_id") == guild_id:
            warnings.append((
                warning.get("warning_number"),
                warning.get("reason"),
                warning.get("created_at")
            ))
    
    return warnings

def get_warning_count(user_id: int, guild_id: int) -> int:
    """Get the count of warnings for a user."""
    data = load_json(WARNINGS_FILE)
    count = 0
    
    for warning in data.get("warnings", []):
        if warning.get("user_id") == user_id and warning.get("guild_id") == guild_id:
            count += 1
    
    return count

# =============================================================================
# PUNISHMENT CONFIG FUNCTIONS
# =============================================================================

def get_punishment_config() -> Dict[str, Any]:
    """Load punishment configuration from file."""
    return load_json(PUNISHMENT_CONFIG_FILE)

def extract_rule_number(rule_violation: str) -> Optional[str]:
    """Extract the rule number from a rule violation string like '§2' or '§§ 2 and 3'."""
    import re
    # Match patterns like §1, §2, §§ 1, 2, and 3, etc.
    matches = re.findall(r'§+\s*(\d+)', rule_violation)
    if matches:
        return matches[0]  # Return the first rule number found
    return None

def calculate_automatic_punishment(user_id: int, guild_id: int, rule_violation: str) -> str:
    """
    Calculate automatic punishment duration based on rule violation and prior offenses.
    
    Formula: base_time + (prior_offenses * per_prior_offense_time)
    """
    config = get_punishment_config()
    
    if not config:
        return "2h"  # Default fallback
    
    base_times = config.get("base_times", {})
    per_prior = config.get("per_prior_offense", {})
    
    # Extract rule number from violation string
    rule_num = extract_rule_number(rule_violation)
    if not rule_num:
        rule_num = "default"
    
    # Get base time for this rule
    base_time_str = base_times.get(rule_num, base_times.get("default", "2h"))
    
    # If base time is indefinite, return immediately
    if base_time_str.lower() == "indefinite":
        return "indefinite"
    
    # Get per-prior-offense time for this rule
    per_prior_str = per_prior.get(rule_num, per_prior.get("default", "2h"))
    
    # Get prior offense count
    prior_count = get_punishment_count(user_id, guild_id)
    
    # Parse times to seconds
    from utils import parse_time_duration, format_duration
    
    base_seconds = parse_time_duration(base_time_str) or 7200  # Default 2h
    per_prior_seconds = parse_time_duration(per_prior_str) or 0
    
    # Calculate total time
    total_seconds = base_seconds + (prior_count * per_prior_seconds)
    
    # Format back to duration string
    return format_duration(total_seconds)

def get_temp_ban_channel_id() -> Optional[str]:
    """Get the temp ban confirmation channel ID from punishment config."""
    config = get_punishment_config()
    return config.get("temp_ban_channel_id")

def set_temp_ban_channel_id(channel_id: str) -> bool:
    """Set the temp ban confirmation channel ID in punishment config."""
    config = get_punishment_config()
    config["temp_ban_channel_id"] = channel_id
    return save_json(PUNISHMENT_CONFIG_FILE, config)

def get_temp_ban_rules() -> Dict[str, Any]:
    """Get the temp ban rules from punishment config."""
    config = get_punishment_config()
    return config.get("temp_ban_rules", {})

def check_temp_ban_applicable(rule_violation: str, user_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
    """
    Check if a temp ban might be applicable for this rule violation.
    Returns temp ban info if applicable, None otherwise.
    """
    temp_ban_rules = get_temp_ban_rules()
    rule_num = extract_rule_number(rule_violation)
    
    if not rule_num:
        return None
    
    # Check for direct rule matches (like §8 which always suggests temp ban)
    if rule_num in temp_ban_rules:
        rule_info = temp_ban_rules[rule_num]
        return {
            "rule_key": rule_num,
            "description": rule_info.get("description", f"§{rule_num} violation"),
            "duration": rule_info.get("duration", "6mo"),
            "trigger": rule_info.get("trigger", "first_offense")
        }
    
    # Check for continued offense rules (prior offenses exist)
    prior_count = get_punishment_count(user_id, guild_id)
    if prior_count > 0:
        # Check for continued offense temp ban rules
        continued_key = f"{rule_num}_continued"
        if continued_key in temp_ban_rules:
            return {
                "rule_key": continued_key,
                "description": temp_ban_rules[continued_key].get("description"),
                "duration": temp_ban_rules[continued_key].get("duration"),
                "trigger": "continued",
                "prior_offenses": prior_count
            }
    
    return None

def get_active_punishments(guild_id: Optional[int] = None) -> List[Tuple]:
    """Get all active punishments with release times."""
    data = load_json(LOGS_FILE)
    punishments = []
    
    for log in data.get("logs", []):
        if (log.get("release_time") is not None and 
            not log.get("retracted", False)):
            if guild_id is None or log.get("guild_id") == guild_id:
                punishments.append((
                    log.get("user_id"),
                    log.get("guild_id"),
                    log.get("release_time"),
                    log.get("punishment_start")
                ))
    
    return punishments

def get_expired_punishments(guild_id: Optional[int] = None) -> List[Tuple]:
    """Get punishments that should have expired."""
    now_ts = int(datetime.now(timezone.utc).timestamp())
    data = load_json(LOGS_FILE)
    expired = []
    
    for log in data.get("logs", []):
        release_time = log.get("release_time")
        if (release_time is not None and 
            release_time <= now_ts and 
            not log.get("retracted", False)):
            if guild_id is None or log.get("guild_id") == guild_id:
                expired.append((
                    log.get("user_id"),
                    log.get("guild_id"),
                    release_time
                ))
    
    return expired

def mark_punishment_completed(user_id: int, guild_id: int, release_time: int) -> bool:
    """Mark a punishment as completed by clearing its release_time."""
    data = load_json(LOGS_FILE)
    
    for log in data.get("logs", []):
        if (log.get("user_id") == user_id and 
            log.get("guild_id") == guild_id and 
            log.get("release_time") == release_time):
            log["release_time"] = None
            log["completed_at"] = int(datetime.now(timezone.utc).timestamp())
            return save_json(LOGS_FILE, data)
    
    return False

# =============================================================================
# CONFIGURATION FUNCTIONS
# =============================================================================

def get_config(key: str) -> Optional[str]:
    """Get a configuration value."""
    data = load_json(CONFIG_FILE)
    return data.get(key)

def set_config(key: str, value: str) -> bool:
    """Set a configuration value."""
    data = load_json(CONFIG_FILE)
    data[key] = value
    return save_json(CONFIG_FILE, data)

def get_log_channel_id() -> Optional[str]:
    """Get the log channel ID."""
    return get_config('log_channel_id')

def set_log_channel_id(channel_id: str) -> bool:
    """Set the log channel ID."""
    return set_config('log_channel_id', channel_id)

def get_canada_role_id_str() -> Optional[str]:
    """Get the Canada role ID as string."""
    return get_config('canada_role_id')

def set_canada_role_id(role_id: str) -> bool:
    """Set the Canada role ID."""
    return set_config('canada_role_id', role_id)

def get_all_config() -> Dict[str, str]:
    """Get all configuration items."""
    return load_json(CONFIG_FILE)

# =============================================================================
# ROLE PERMISSION FUNCTIONS
# =============================================================================

def get_allowed_roles(guild_id: int) -> List[int]:
    """Get all allowed role IDs for a guild."""
    data = load_json(ROLES_FILE)
    guild_roles = data.get(str(guild_id), [])
    return guild_roles

def add_allowed_role(guild_id: int, role_id: int) -> bool:
    """Add a role to the allowed roles list."""
    data = load_json(ROLES_FILE)
    guild_key = str(guild_id)
    
    if guild_key not in data:
        data[guild_key] = []
    
    if role_id not in data[guild_key]:
        data[guild_key].append(role_id)
        return save_json(ROLES_FILE, data)
    
    return False  # Already exists

def remove_allowed_role(guild_id: int, role_id: int) -> bool:
    """Remove a role from the allowed roles list."""
    data = load_json(ROLES_FILE)
    guild_key = str(guild_id)
    
    if guild_key in data and role_id in data[guild_key]:
        data[guild_key].remove(role_id)
        # Remove empty guild entries
        if not data[guild_key]:
            del data[guild_key]
        return save_json(ROLES_FILE, data)
    
    return False

def is_role_allowed(guild_id: int, role_id: int) -> bool:
    """Check if a role is allowed to use the bot."""
    data = load_json(ROLES_FILE)
    guild_roles = data.get(str(guild_id), [])
    return role_id in guild_roles

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def cleanup_data():
    """Perform data maintenance tasks."""
    try:
        # Could implement data cleanup tasks here if needed
        # For example, removing very old completed punishments
        logging.info("Data cleanup completed")
        return True
    except Exception as e:
        logging.error(f"Data cleanup failed: {e}")
        return False

def backup_data() -> bool:
    """Create backup copies of all data files."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(DATA_DIR, "backups", timestamp)
        os.makedirs(backup_dir, exist_ok=True)
        
        # Copy all data files to backup directory
        import shutil
        for file_path in [LOGS_FILE, CONFIG_FILE, ROLES_FILE]:
            if os.path.exists(file_path):
                backup_path = os.path.join(backup_dir, os.path.basename(file_path))
                shutil.copy2(file_path, backup_path)
        
        logging.info(f"Data backup created at {backup_dir}")
        return True
    except Exception as e:
        logging.error(f"Data backup failed: {e}")
        return False

def get_data_stats() -> Dict[str, Any]:
    """Get statistics about the stored data."""
    try:
        logs_data = load_json(LOGS_FILE)
        config_data = load_json(CONFIG_FILE)
        roles_data = load_json(ROLES_FILE)
        
        total_logs = len(logs_data.get("logs", []))
        active_logs = len([log for log in logs_data.get("logs", []) if not log.get("retracted", False)])
        
        return {
            "total_logs": total_logs,
            "active_logs": active_logs,
            "retracted_logs": total_logs - active_logs,
            "config_items": len(config_data),
            "guilds_with_roles": len(roles_data),
            "data_files_exist": {
                "logs": os.path.exists(LOGS_FILE),
                "config": os.path.exists(CONFIG_FILE),
                "roles": os.path.exists(ROLES_FILE)
            }
        }
    except Exception as e:
        logging.error(f"Error getting data stats: {e}")
        return {}

# =============================================================================
# TEMP BAN TRACKING
# =============================================================================

TEMP_BANS_FILE = os.path.join(DATA_DIR, "temp_bans.json")

def init_temp_bans_storage():
    """Initialize temp bans storage file."""
    if not os.path.exists(TEMP_BANS_FILE):
        save_json(TEMP_BANS_FILE, {"temp_bans": []})

def create_temp_ban(guild_id: int, user_id: int, moderator_id: int, log_number: int,
                    duration: str, unban_time: int, reason: str) -> bool:
    """Create a temp ban record."""
    init_temp_bans_storage()
    data = load_json(TEMP_BANS_FILE)
    
    temp_ban = {
        "guild_id": guild_id,
        "user_id": user_id,
        "moderator_id": moderator_id,
        "log_number": log_number,
        "duration": duration,
        "unban_time": unban_time,
        "reason": reason,
        "banned_at": int(datetime.now(timezone.utc).timestamp()),
        "unbanned": False
    }
    
    data["temp_bans"].append(temp_ban)
    return save_json(TEMP_BANS_FILE, data)

def get_active_temp_bans(guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get all active (not yet unbanned) temp bans."""
    init_temp_bans_storage()
    data = load_json(TEMP_BANS_FILE)
    
    active_bans = []
    for ban in data.get("temp_bans", []):
        if not ban.get("unbanned", False):
            if guild_id is None or ban.get("guild_id") == guild_id:
                active_bans.append(ban)
    
    return active_bans

def get_expired_temp_bans(guild_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get temp bans that should have expired (unban time passed but not yet unbanned)."""
    init_temp_bans_storage()
    now_ts = int(datetime.now(timezone.utc).timestamp())
    data = load_json(TEMP_BANS_FILE)
    
    expired = []
    for ban in data.get("temp_bans", []):
        unban_time = ban.get("unban_time")
        if (unban_time is not None and 
            unban_time <= now_ts and 
            not ban.get("unbanned", False)):
            if guild_id is None or ban.get("guild_id") == guild_id:
                expired.append(ban)
    
    return expired

def mark_temp_ban_completed(user_id: int, guild_id: int, unban_time: int) -> bool:
    """Mark a temp ban as completed (unbanned)."""
    init_temp_bans_storage()
    data = load_json(TEMP_BANS_FILE)
    
    for ban in data.get("temp_bans", []):
        if (ban.get("user_id") == user_id and 
            ban.get("guild_id") == guild_id and 
            ban.get("unban_time") == unban_time and
            not ban.get("unbanned", False)):
            ban["unbanned"] = True
            ban["unbanned_at"] = int(datetime.now(timezone.utc).timestamp())
            return save_json(TEMP_BANS_FILE, data)
    
    return False

def get_temp_ban_for_user(user_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
    """Get active temp ban for a user if one exists."""
    active_bans = get_active_temp_bans(guild_id)
    for ban in active_bans:
        if ban.get("user_id") == user_id:
            return ban
    return None

def cancel_temp_ban_record(user_id: int, guild_id: int, cancelled_by: int) -> bool:
    """Cancel a temp ban record (mark as unbanned early)."""
    init_temp_bans_storage()
    data = load_json(TEMP_BANS_FILE)
    
    for ban in data.get("temp_bans", []):
        if (ban.get("user_id") == user_id and 
            ban.get("guild_id") == guild_id and
            not ban.get("unbanned", False)):
            ban["unbanned"] = True
            ban["unbanned_at"] = int(datetime.now(timezone.utc).timestamp())
            ban["cancelled_early"] = True
            ban["cancelled_by"] = cancelled_by
            return save_json(TEMP_BANS_FILE, data)
    
    return False

# =============================================================================
# GUILD RESTRICTION CLEANUP
# =============================================================================

def cleanup_other_guild_data():
    """Remove punishment data for guilds other than the allowed one."""
    try:
        data = load_json(LOGS_FILE)
        original_count = len(data.get("logs", []))
        
        # Filter out logs from other guilds
        filtered_logs = [
            log for log in data.get("logs", [])
            if log.get("guild_id") == ALLOWED_GUILD_ID
        ]
        
        new_count = len(filtered_logs)
        removed_count = original_count - new_count
        
        if removed_count > 0:
            # Update the data
            data["logs"] = filtered_logs
            save_json(LOGS_FILE, data)
            
            logging.info(f"Cleaned up {removed_count} punishment records from other guilds")
            logging.info(f"Kept {new_count} records for the allowed guild ({ALLOWED_GUILD_ID})")
            return removed_count
        else:
            logging.debug("No cleanup needed - all punishment records are for the allowed guild")
            return 0
            
    except Exception as e:
        logging.error(f"Error during guild data cleanup: {e}")
        return 0
