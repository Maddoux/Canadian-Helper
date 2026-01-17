"""
Utility functions for the Canadian Helper bot.
"""

import os
import re
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import discord
from bot_config import ALLOWED_GUILD_ID

# =============================================================================
# GUILD RESTRICTION DECORATOR
# =============================================================================

def guild_only():
    """Decorator to restrict commands to the allowed guild only."""
    def decorator(func):
        async def wrapper(interaction: discord.Interaction, *args, **kwargs):
            if interaction.guild_id != ALLOWED_GUILD_ID:
                await interaction.response.send_message(
                    "❌ This bot only works in the authorized server.", 
                    ephemeral=True
                )
                return
            return await func(interaction, *args, **kwargs)
        return wrapper
    return decorator

# =============================================================================
# TIME PARSING FUNCTIONS
# =============================================================================

def parse_time_duration(duration_str: str) -> Optional[int]:
    """Parse a time duration string and return seconds."""
    if duration_str.lower() == "indefinite":
        return None
    
    # Parse duration like "1w", "2d", "3h", "30m", "6mo" (months)
    match = re.match(r'^(\d+)(mo|[wdhm])$', duration_str.lower())
    if not match:
        return None
    
    amount, unit = match.groups()
    amount = int(amount)
    
    if unit == 'mo':  # months (approximate as 30 days)
        return amount * 30 * 24 * 3600
    elif unit == 'w':  # weeks
        return amount * 7 * 24 * 3600
    elif unit == 'd':  # days
        return amount * 24 * 3600
    elif unit == 'h':  # hours
        return amount * 3600
    elif unit == 'm':  # minutes
        return amount * 60
    
    return None

def format_duration(seconds: int) -> str:
    """Format duration in seconds to human readable string."""
    if seconds is None:
        return "indefinite"
    
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h"
    elif seconds < 604800:
        days = seconds // 86400
        return f"{days}d"
    elif seconds < 2592000:  # Less than 30 days
        weeks = seconds // 604800
        return f"{weeks}w"
    else:  # 30 days or more
        months = seconds // 2592000
        return f"{months}mo"

def format_timestamp(timestamp: int, style: str = "F") -> str:
    """Format a Unix timestamp for Discord."""
    return f"<t:{timestamp}:{style}>"

# =============================================================================
# TEXT PROCESSING FUNCTIONS
# =============================================================================

def load_banned_words() -> set:
    """Load banned words from file."""
    banned_words = set()
    try:
        if os.path.exists("swearWords.txt"):
            with open("swearWords.txt", "r", encoding="utf-8") as f:
                for line in f:
                    word = line.strip().lower()
                    if word and not word.startswith("#"):
                        banned_words.add(word)
            logging.info(f"Loaded {len(banned_words)} banned words")
        else:
            logging.warning("swearWords.txt not found")
    except Exception as e:
        logging.error(f"Error loading banned words: {e}")
    
    return banned_words

# =============================================================================
# DISCORD HELPER FUNCTIONS
# =============================================================================

async def user_has_access(interaction: discord.Interaction) -> bool:
    """Check if user has access to bot commands."""
    from data_manager import get_allowed_roles
    
    # Administrators always have access
    if interaction.user.guild_permissions.administrator:
        return True
    
    # Check if user has any allowed roles
    allowed_role_ids = get_allowed_roles(interaction.guild.id)
    user_role_ids = [role.id for role in interaction.user.roles]
    
    return any(role_id in allowed_role_ids for role_id in user_role_ids)

# =============================================================================
# EMBED CREATION FUNCTIONS
# =============================================================================

def create_log_embed(log_number: int, user: discord.Member, rule_violation: str, 
                    description: str, punishment: str, moderator: discord.Member,
                    release_time: Optional[int] = None, guild_id: Optional[int] = None) -> discord.Embed:
    """Create a standardized log embed."""
    embed = discord.Embed(
        title=f"Log #{log_number}",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )
    
    embed.add_field(name="User", value=user.mention, inline=False)
    embed.add_field(name="Rule Violation", value=rule_violation, inline=False)
    embed.add_field(name="Punishment", value=punishment, inline=False)
    embed.add_field(name="Description", value=description, inline=False)
    embed.add_field(name="Moderator", value=moderator.mention, inline=False)
    
    if release_time:
        embed.add_field(
            name="Release Time", 
            value=format_timestamp(release_time, "F"), 
            inline=False
        )
    
    # Calculate total Canada logs for this user (not including retracted/deleted)
    if guild_id:
        try:
            from data_manager import get_punishment_count
            total_logs = get_punishment_count(user.id, guild_id)
            embed.set_footer(text=f"Total Canada logs: {total_logs}")
            
        except Exception as e:
            # Fallback to user ID if there's an error getting punishment count
            logging.error(f"Error getting user punishment count: {e}")
            embed.set_footer(text=f"User ID: {user.id}")
    else:
        embed.set_footer(text=f"User ID: {user.id}")
    
    return embed

def create_error_embed(title: str, description: str) -> discord.Embed:
    """Create a standardized error embed."""
    embed = discord.Embed(
        title=f"❌ {title}",
        description=description,
        color=discord.Color.red()
    )
    return embed

def create_success_embed(title: str, description: str) -> discord.Embed:
    """Create a standardized success embed."""
    embed = discord.Embed(
        title=f"✅ {title}",
        description=description,
        color=discord.Color.green()
    )
    return embed

def create_info_embed(title: str, description: str) -> discord.Embed:
    """Create a standardized info embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blue()
    )
    return embed

# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_punishment_duration(duration_str: str) -> bool:
    """Validate if a punishment duration string is valid."""
    if duration_str.lower() == "indefinite":
        return True
    
    return parse_time_duration(duration_str) is not None

def validate_log_number(log_number: int) -> bool:
    """Validate if a log number is valid."""
    return isinstance(log_number, int) and log_number > 0

# =============================================================================
# FILE OPERATION HELPERS
# =============================================================================

def ensure_directory_exists(directory: str):
    """Ensure a directory exists, create if it doesn't."""
    os.makedirs(directory, exist_ok=True)

def safe_filename(filename: str) -> str:
    """Create a safe filename by removing/replacing invalid characters."""
    # Remove or replace invalid filename characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove control characters
    filename = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', filename)
    # Limit length
    return filename[:255]

# =============================================================================
# DISCORD UI HELPERS
# =============================================================================

class Paginator(discord.ui.View):
    """A paginated view for displaying multiple embeds."""
    
    def __init__(self, embeds: List[discord.Embed], timeout: int = 300):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()
    
    def update_buttons(self):
        """Update button states based on current page."""
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.embeds) - 1
        
        # Update page indicator
        if len(self.embeds) > 1:
            footer_text = f"Page {self.current_page + 1} of {len(self.embeds)}"
            if self.embeds[self.current_page].footer.text:
                self.embeds[self.current_page].set_footer(
                    text=f"{self.embeds[self.current_page].footer.text} | {footer_text}"
                )
            else:
                self.embeds[self.current_page].set_footer(text=footer_text)
    
    @discord.ui.button(label="◀", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to next page."""
        if self.current_page < len(self.embeds) - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    async def on_timeout(self):
        """Disable buttons when view times out."""
        for item in self.children:
            item.disabled = True
