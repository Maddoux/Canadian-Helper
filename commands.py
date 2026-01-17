"""
Discord slash commands for the Canadian Helper bot.
"""

import os
import re
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot_config import CANADA_ROLE_ID, RULE_VIOLATIONS, ALLOWED_GUILD_ID, get_canada_role_id, WARNING_LOG_CHANNEL_ID
from data_manager import *
from utils import *
from events import schedule_role_removal, cancel_scheduled_removal, get_scheduled_removals, schedule_temp_unban, cancel_temp_unban, get_scheduled_unbans

# Ban log channel ID
BAN_LOG_CHANNEL_ID = 689927423382519866

# Moderator and Admin role IDs (for permission checks)
MODERATOR_ROLE_ID = 707781265985896469
ADMIN_ROLE_ID = 654477469004595221

# =============================================================================
# TEMP BAN CONFIRMATION VIEW
# =============================================================================

class TempBanConfirmView(discord.ui.View):
    """View with Yes/No buttons for confirming temp bans."""
    
    def __init__(self, user: discord.Member, temp_ban_info: dict, log_number: int, moderator: discord.Member):
        super().__init__(timeout=86400)  # 24 hour timeout
        self.user = user
        self.temp_ban_info = temp_ban_info
        self.log_number = log_number
        self.moderator = moderator
        self.responded = False
    
    # Role IDs that cannot be temp banned
    PROTECTED_ROLE_IDS = [654477469004595221, 707781265985896469]  # Admin, Moderator
    
    # Ban log channel ID
    BAN_LOG_CHANNEL_ID = 689927423382519866
    
    @discord.ui.button(label="Yes, Temp Ban", style=discord.ButtonStyle.danger, emoji="⛔")
    async def confirm_ban(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.responded:
            await interaction.response.send_message("This has already been handled.", ephemeral=True)
            return
        
        # Check if user has protected roles (Admin or Moderator)
        user_role_ids = [role.id for role in self.user.roles]
        if any(role_id in user_role_ids for role_id in self.PROTECTED_ROLE_IDS):
            await interaction.response.send_message(
                f"❌ Cannot temp ban **{self.user.display_name}** - they have Admin or Moderator role.",
                ephemeral=True
            )
            return
        
        self.responded = True
        
        # Disable all buttons
        for child in self.children:
            child.disabled = True
        
        try:
            # Ban the user
            duration_str = self.temp_ban_info.get("duration", "6mo")
            reason = f"Temp ban for log #{self.log_number} - {self.temp_ban_info.get('description', 'Rule violation')}"
            
            # Calculate unban time
            duration_seconds = parse_time_duration(duration_str)
            unban_time = int(datetime.now(timezone.utc).timestamp()) + duration_seconds if duration_seconds else None
            
            await self.user.ban(reason=reason, delete_message_days=0)
            
            # Track the temp ban in storage
            from data_manager import create_temp_ban
            from events import schedule_temp_unban
            
            create_temp_ban(
                guild_id=interaction.guild.id,
                user_id=self.user.id,
                moderator_id=interaction.user.id,
                log_number=self.log_number,
                duration=duration_str,
                unban_time=unban_time,
                reason=reason
            )
            
            # Schedule the automatic unban
            if unban_time:
                await schedule_temp_unban(
                    interaction.client,
                    interaction.guild.id,
                    self.user.id,
                    unban_time,
                    self.log_number
                )
            
            # Send to ban log channel
            ban_log_channel = interaction.guild.get_channel(self.BAN_LOG_CHANNEL_ID)
            if ban_log_channel:
                log_embed = discord.Embed(
                    title="⛔ Temp Ban Applied",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )
                log_embed.add_field(name="User", value=f"{self.user.mention} ({self.user.id})", inline=True)
                log_embed.add_field(name="Log #", value=str(self.log_number), inline=True)
                log_embed.add_field(name="Duration", value=duration_str, inline=True)
                log_embed.add_field(name="Approved By", value=interaction.user.mention, inline=True)
                log_embed.add_field(name="Original Moderator", value=self.moderator.mention, inline=True)
                if unban_time:
                    log_embed.add_field(name="Unban Time", value=f"<t:{unban_time}:F>", inline=False)
                log_embed.add_field(name="Reason", value=self.temp_ban_info.get('description', 'Rule violation'), inline=False)
                log_embed.set_thumbnail(url=self.user.display_avatar.url if self.user.display_avatar else None)
                
                try:
                    await ban_log_channel.send(embed=log_embed)
                except Exception as e:
                    logging.error(f"Error sending ban log: {e}")
            
            # Update the message to show it was approved
            embed = interaction.message.embeds[0] if interaction.message.embeds else None
            if embed:
                embed.color = discord.Color.red()
                embed.set_footer(text=f"✅ Approved by {interaction.user.display_name} at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
            
            await interaction.message.edit(embed=embed, view=self)
            
            # Send confirmation
            if unban_time:
                unban_timestamp = f"<t:{unban_time}:F>"
                await interaction.response.send_message(
                    f"✅ **{self.user.display_name}** has been temp banned for **{duration_str}**.\n"
                    f"📅 Unban scheduled for: {unban_timestamp}\n"
                    f"📝 Log #{self.log_number}",
                    ephemeral=False
                )
            else:
                await interaction.response.send_message(
                    f"✅ **{self.user.display_name}** has been banned.\n"
                    f"📝 Log #{self.log_number}",
                    ephemeral=False
                )
            
            logging.info(f"Temp ban confirmed for {self.user.id} by {interaction.user.id}")
            
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to ban this user.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error banning user: {e}",
                ephemeral=True
            )
    
    @discord.ui.button(label="No, Just Canada", style=discord.ButtonStyle.secondary, emoji="🍁")
    async def decline_ban(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.responded:
            await interaction.response.send_message("This has already been handled.", ephemeral=True)
            return
        
        self.responded = True
        
        # Disable all buttons
        for child in self.children:
            child.disabled = True
        
        # Update the message to show it was declined
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            embed.color = discord.Color.green()
            embed.set_footer(text=f"❌ Declined by {interaction.user.display_name} at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            f"👍 No temp ban applied. User remains in Canada only.\n📝 Log #{self.log_number}",
            ephemeral=False
        )
        
        logging.info(f"Temp ban declined for {self.user.id} by {interaction.user.id}")
    
    async def on_timeout(self):
        """Called when the view times out."""
        # Disable all buttons
        for child in self.children:
            child.disabled = True
        
        # Try to update the message
        # Note: We can't easily access the message here, so this is handled by the bot's persistence

async def send_temp_ban_confirmation(bot, guild: discord.Guild, user: discord.Member, 
                                      temp_ban_info: dict, log_number: int, moderator: discord.Member):
    """Send a temp ban confirmation message to the designated channel."""
    channel_id = get_temp_ban_channel_id()
    if not channel_id:
        logging.warning("No temp ban confirmation channel configured")
        return
    
    channel = guild.get_channel(int(channel_id))
    if not channel:
        logging.warning(f"Temp ban confirmation channel {channel_id} not found")
        return
    
    # Create the confirmation embed
    embed = discord.Embed(
        title="⚠️ Temp Ban Confirmation Required",
        description=f"Should **{user.display_name}** ({user.mention}) be temp banned?",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc)
    )
    
    embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=True)
    embed.add_field(name="Log #", value=str(log_number), inline=True)
    embed.add_field(name="Moderator", value=moderator.mention, inline=True)
    
    embed.add_field(
        name="Rule Violation",
        value=temp_ban_info.get("description", "Unknown"),
        inline=False
    )
    
    embed.add_field(
        name="Suggested Ban Duration",
        value=f"**{temp_ban_info.get('duration', 'Unknown')}**",
        inline=True
    )
    
    embed.add_field(
        name="Trigger",
        value=temp_ban_info.get("trigger", "Unknown").replace("_", " ").title(),
        inline=True
    )
    
    if "prior_offenses" in temp_ban_info:
        embed.add_field(
            name="Prior Offenses",
            value=str(temp_ban_info["prior_offenses"]),
            inline=True
        )
    
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    
    # Create and send the view
    view = TempBanConfirmView(user, temp_ban_info, log_number, moderator)
    
    try:
        await channel.send(embed=embed, view=view)
        logging.info(f"Sent temp ban confirmation for {user.id} to channel {channel_id}")
    except Exception as e:
        logging.error(f"Error sending temp ban confirmation: {e}")

# =============================================================================
# SETUP COMMANDS
# =============================================================================

@app_commands.command(name="setup", description="Set up bot configuration")
@app_commands.describe(
    log_channel="The channel for punishment logs",
    canada_role="The role to assign for punishments",
    temp_ban_channel="The channel for temp ban confirmation prompts"
)
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def setup(interaction: discord.Interaction, 
                log_channel: Optional[discord.TextChannel] = None,
                canada_role: Optional[discord.Role] = None,
                temp_ban_channel: Optional[discord.TextChannel] = None):
    """Set up bot configuration including channels and roles."""
    await interaction.response.defer(ephemeral=True)
    
    # Check if at least one parameter is provided
    if not any([log_channel, canada_role, temp_ban_channel]):
        embed = create_error_embed(
            "No Parameters Provided",
            "Please provide at least one parameter to set up:\n• `log_channel` - Channel for punishment logs\n• `canada_role` - Role to assign for punishments\n• `temp_ban_channel` - Channel for temp ban confirmations"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    setup_results = []
    
    # Save the log channel ID to config if provided
    if log_channel:
        success = set_log_channel_id(str(log_channel.id))
        if success:
            setup_results.append(f"✅ Log channel: {log_channel.mention}")
        else:
            setup_results.append(f"❌ Failed to set log channel")
    
    # Save Canada role if provided
    if canada_role:
        success = set_canada_role_id(str(canada_role.id))
        if success:
            setup_results.append(f"✅ Canada role: {canada_role.mention}")
        else:
            setup_results.append(f"❌ Failed to set Canada role")
    
    # Save temp ban channel if provided
    if temp_ban_channel:
        success = set_temp_ban_channel_id(str(temp_ban_channel.id))
        if success:
            setup_results.append(f"✅ Temp ban channel: {temp_ban_channel.mention}")
        else:
            setup_results.append(f"❌ Failed to set temp ban channel")
    
    # Create response embed
    if all("✅" in result for result in setup_results):
        embed = create_success_embed(
            "Bot Setup Complete",
            "\n".join(setup_results)
        )
    else:
        embed = create_error_embed(
            "Setup Partially Failed",
            "\n".join(setup_results)
        )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# =============================================================================
# PUNISHMENT COMMANDS
# =============================================================================

@app_commands.command(name="canada", description="Punish a user by sending them to 'Canada'")
@app_commands.describe(
    user="The user to punish",
    description="Reason for punishment",
    rule_violation="Rule violation (leave blank to use rule selector)",
    punishment="Override automatic duration (e.g., '1w', '1d', '12h', '30m', or 'indefinite') - leave blank for automatic"
)
async def canada(interaction: discord.Interaction, user: discord.Member, 
                description: str, rule_violation: Optional[str] = None, punishment: Optional[str] = None):
    """Send a user to Canada."""
    if not await user_has_access(interaction):
        await interaction.response.send_message("You don't have permission to use this feature.", ephemeral=True)
        return
    
    # Defer the response to give us more time (ephemeral if no rule provided)
    await interaction.response.defer(ephemeral=(rule_violation is None))
    
    # Validate punishment duration if provided
    if punishment and not validate_punishment_duration(punishment):
        embed = create_error_embed(
            "Invalid Punishment Duration",
            "Please use format like '1w', '1d', '12h', '30m', or 'indefinite'"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Get Canada role
    canada_role_id = get_canada_role_id()
    canada_role = interaction.guild.get_role(canada_role_id)
    if not canada_role:
        embed = create_error_embed(
            "Canada Role Not Found",
            f"Canada role (ID: {canada_role_id}) not found. Please use `/setup canada_role:@RoleName` to configure the role."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Check if user already has Canada role
    if canada_role in user.roles:
        embed = create_error_embed(
            "User Already in Canada",
            f"{user.mention} is already in Canada."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Handle rule violation selection if not provided
    if not rule_violation:
        # Create a rule selection view
        class RuleSelectView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)
            
            @discord.ui.select(
                placeholder="Select rule violation(s)...",
                min_values=1,
                max_values=len(RULE_VIOLATIONS),
                options=[discord.SelectOption(label=rule[:100], value=rule) for rule in RULE_VIOLATIONS]
            )
            async def rule_select(self, interaction: discord.Interaction, select: discord.ui.Select):
                selected_rules = select.values
                
                # Extract section numbers and format them nicely
                section_numbers = []
                for rule in selected_rules:
                    # Extract section number from rules like "§1 - Description"
                    import re
                    match = re.match(r'§(\d+)', rule)
                    if match:
                        section_numbers.append(match.group(1))
                
                # Format the combined rule violation
                if len(section_numbers) == 1:
                    combined_rule = f"§ {section_numbers[0]}"
                elif len(section_numbers) == 2:
                    combined_rule = f"§§ {section_numbers[0]} and {section_numbers[1]}"
                else:
                    # For 3 or more sections: "§§ 1, 2, and 3"
                    combined_rule = f"§§ {', '.join(section_numbers[:-1])}, and {section_numbers[-1]}"
                
                await self.process_punishment(interaction, combined_rule)
            
            async def process_punishment(self, select_interaction: discord.Interaction, selected_rule: str):
                await select_interaction.response.defer()
                
                # Calculate automatic punishment if not overridden
                actual_punishment = punishment
                if not actual_punishment:
                    actual_punishment = calculate_automatic_punishment(user.id, interaction.guild.id, selected_rule)
                
                # Calculate release time
                punishment_start = int(datetime.now(timezone.utc).timestamp())
                duration_seconds = parse_time_duration(actual_punishment)
                release_time = punishment_start + duration_seconds if duration_seconds else None
                
                # Create log entry
                try:
                    log_number = create_log(
                        guild_id=interaction.guild.id,
                        user_id=user.id,
                        rule_violation=selected_rule,
                        description=description,
                        punishment=actual_punishment,
                        release_time=release_time,
                        punishment_start=punishment_start,
                        moderator_id=interaction.user.id
                    )
                except Exception as e:
                    embed = create_error_embed("Database Error", f"Failed to create log: {e}")
                    await select_interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Add Canada role
                try:
                    await user.add_roles(canada_role, reason=f"Canada punishment #{log_number}")
                except discord.Forbidden:
                    embed = create_error_embed(
                        "Permission Error",
                        "Bot doesn't have permission to assign roles."
                    )
                    await select_interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Create and send log embed
                embed = create_log_embed(
                    log_number=log_number,
                    user=user,
                    rule_violation=selected_rule,
                    description=description,
                    punishment=actual_punishment,
                    moderator=interaction.user,
                    release_time=release_time,
                    guild_id=interaction.guild.id
                )
                
                # Send to log channel
                channel_id = get_log_channel_id()
                if channel_id:
                    log_channel = interaction.guild.get_channel(int(channel_id))
                    if log_channel:
                        try:
                            log_message = await log_channel.send(embed=embed)
                            update_log_message_id(log_number, interaction.guild.id, log_message.id)
                        except Exception as e:
                            logging.error(f"Error sending log message: {e}")
                
                # Send public notification to Canada channel
                canada_channel = None
                # First try to find a channel named "canada" or similar
                for channel in interaction.guild.text_channels:
                    if channel.name.lower() in ['canada', 'canadian-exile', 'exile', 'canadian-helper']:
                        canada_channel = channel
                        break
                
                # If no specific Canada channel found, you could optionally use the log channel
                # or add a separate canada_notification_channel_id to the config
                
                if canada_channel:
                    try:
                        # Create a simpler public notification message matching your example
                        notification_msg = f"{user.mention} You have been sent to Canada for {actual_punishment} due to: {description}\n"
                        notification_msg += "You can [appeal here](https://discord.com/channels/654458344781774879/759578710654844958/1369303047041318952)."
                        
                        await canada_channel.send(notification_msg)
                        logging.info(f"Sent Canada notification to #{canada_channel.name}")
                    except Exception as e:
                        logging.error(f"Error sending Canada channel notification: {e}")
                else:
                    logging.warning("No Canada notification channel found (looked for #canada, #canadian-exile, #exile, #canadian-helper)")
                
                # Schedule role removal if not indefinite
                if release_time:
                    bot = select_interaction.client
                    await schedule_role_removal(bot, interaction.guild.id, user.id, release_time)
                
                # Send DM to user
                try:
                    dm_embed = discord.Embed(
                        title="You have been sent to Canada",
                        color=discord.Color.red()
                    )
                    dm_embed.add_field(name="Rule Violation", value=selected_rule, inline=False)
                    dm_embed.add_field(name="Reason", value=description, inline=False)
                    dm_embed.add_field(name="Duration", value=actual_punishment, inline=False)
                    if release_time:
                        dm_embed.add_field(
                            name="Release Time",
                            value=format_timestamp(release_time, "F"),
                            inline=False
                        )
                    dm_embed.add_field(
                        name="How to Appeal",
                        value="If you believe this decision was incorrect, please see [this message](https://discord.com/channels/654458344781774879/759578710654844958/1369303047041318952) for information on how to appeal your punishment.",
                        inline=False
                    )
                    await user.send(embed=dm_embed)
                except discord.Forbidden:
                    pass  # User has DMs disabled
                
                # Send confirmation and delete the original selection message
                await select_interaction.followup.send(f"✅ {user.mention} has been sent to Canada (#{log_number})", ephemeral=True)
                
                # Check if temp ban might be applicable and send confirmation request
                temp_ban_info = check_temp_ban_applicable(selected_rule, user.id, interaction.guild.id)
                if temp_ban_info:
                    await send_temp_ban_confirmation(
                        select_interaction.client,
                        interaction.guild,
                        user,
                        temp_ban_info,
                        log_number,
                        interaction.user
                    )
                
                # Delete the original rule selection message
                try:
                    await select_interaction.message.delete()
                except Exception as e:
                    logging.error(f"Error deleting rule selection message: {e}")
        
        # Send rule selection
        embed = create_info_embed(
            "Select Rule Violation",
            f"Please select the rule violation for {user.mention}:"
        )
        view = RuleSelectView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        return
    
    # Calculate automatic punishment if not overridden
    actual_punishment = punishment
    if not actual_punishment:
        actual_punishment = calculate_automatic_punishment(user.id, interaction.guild.id, rule_violation)
    
    # Process with provided rule violation
    punishment_start = int(datetime.now(timezone.utc).timestamp())
    duration_seconds = parse_time_duration(actual_punishment)
    release_time = punishment_start + duration_seconds if duration_seconds else None
    
    # Create log entry
    try:
        log_number = create_log(
            guild_id=interaction.guild.id,
            user_id=user.id,
            rule_violation=rule_violation,
            description=description,
            punishment=actual_punishment,
            release_time=release_time,
            punishment_start=punishment_start,
            moderator_id=interaction.user.id
        )
    except Exception as e:
        embed = create_error_embed("Database Error", f"Failed to create log: {e}")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Add Canada role
    try:
        await user.add_roles(canada_role, reason=f"Canada punishment #{log_number}")
    except discord.Forbidden:
        embed = create_error_embed(
            "Permission Error",
            "Bot doesn't have permission to assign roles."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Create and send log embed
    embed = create_log_embed(
        log_number=log_number,
        user=user,
        rule_violation=rule_violation,
        description=description,
        punishment=actual_punishment,
        moderator=interaction.user,
        release_time=release_time,
        guild_id=interaction.guild.id
    )
    
    # Send to log channel
    channel_id = get_log_channel_id()
    if channel_id:
        log_channel = interaction.guild.get_channel(int(channel_id))
        if log_channel:
            try:
                log_message = await log_channel.send(embed=embed)
                update_log_message_id(log_number, interaction.guild.id, log_message.id)
            except Exception as e:
                logging.error(f"Error sending log message: {e}")
    
    # Send public notification to Canada channel
    canada_channel = None
    # First try to find a channel named "canada" or similar
    for channel in interaction.guild.text_channels:
        if channel.name.lower() in ['canada', 'canadian-exile', 'exile', 'canadian-helper']:
            canada_channel = channel
            break
    
    # If no specific Canada channel found, you could optionally use the log channel
    # or add a separate canada_notification_channel_id to the config
    
    if canada_channel:
        try:
            # Create a simpler public notification message matching your example
            notification_msg = f"{user.mention} You have been sent to Canada for {actual_punishment} due to: {description}\n"
            notification_msg += "You can [appeal here](https://discord.com/channels/654458344781774879/759578710654844958/1369303047041318952)."
            
            await canada_channel.send(notification_msg)
            logging.info(f"Sent Canada notification to #{canada_channel.name}")
        except Exception as e:
            logging.error(f"Error sending Canada channel notification: {e}")
    else:
        logging.warning("No Canada notification channel found (looked for #canada, #canadian-exile, #exile, #canadian-helper)")
    
    # Schedule role removal if not indefinite
    if release_time:
        bot = interaction.client
        await schedule_role_removal(bot, interaction.guild.id, user.id, release_time)
    
    # Send DM to user
    try:
        dm_embed = discord.Embed(
            title="You have been sent to Canada",
            color=discord.Color.red()
        )
        dm_embed.add_field(name="Rule Violation", value=rule_violation, inline=False)
        dm_embed.add_field(name="Reason", value=description, inline=False)
        dm_embed.add_field(name="Duration", value=actual_punishment, inline=False)
        if release_time:
            dm_embed.add_field(
                name="Release Time",
                value=format_timestamp(release_time, "F"),
                inline=False
            )
        dm_embed.add_field(
            name="How to Appeal",
            value="If you believe this decision was incorrect, please see [this message](https://discord.com/channels/654458344781774879/759578710654844958/1369303047041318952) for information on how to appeal your punishment.",
            inline=False
        )
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        pass  # User has DMs disabled
    
    # Check if temp ban might be applicable and send confirmation request
    temp_ban_info = check_temp_ban_applicable(rule_violation, user.id, interaction.guild.id)
    if temp_ban_info:
        await send_temp_ban_confirmation(
            interaction.client,
            interaction.guild,
            user,
            temp_ban_info,
            log_number,
            interaction.user
        )
    
    # Send confirmation
    await interaction.followup.send(f"✅ {user.mention} has been sent to Canada (#{log_number})")

@app_commands.command(name="release", description="Manually release a user from Canada")
@app_commands.describe(user="The user to release from Canada")
async def release(interaction: discord.Interaction, user: discord.Member):
    """Manually release a user from Canada."""
    if not await user_has_access(interaction):
        await interaction.response.send_message("You don't have permission to use this feature.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Check if user has Canada role
    canada_role_id = get_canada_role_id()
    canada_role = interaction.guild.get_role(canada_role_id)
    if not canada_role:
        await interaction.followup.send(f"Canada role (ID: {canada_role_id}) not found. Please use `/setup canada_role:@RoleName` to configure the role.", ephemeral=True)
        return
    
    if canada_role not in user.roles:
        await interaction.followup.send(f"{user.mention} is not currently in Canada.", ephemeral=True)
        return
    
    try:
        # Remove the Canada role
        await user.remove_roles(canada_role, reason=f"Manually released by {interaction.user}")
        
        # Get any active punishments for this user and mark them as completed
        now_ts = int(datetime.now(timezone.utc).timestamp())
        active_punishments = get_active_punishments(interaction.guild.id)
        
        released_punishments = []
        for user_id, guild_id, release_time, punishment_start in active_punishments:
            if user_id == user.id:
                # Mark the punishment as completed
                mark_punishment_completed(user_id, guild_id, release_time)
                released_punishments.append((user_id, guild_id, release_time))
        
        # Cancel any scheduled removal task
        await cancel_scheduled_removal(user.id)
        
        # Send DM to user
        try:
            dm_embed = discord.Embed(
                title="You have been released from Canada",
                description=f"You have been manually released from Canada by {interaction.user.mention}.",
                color=discord.Color.green()
            )
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            pass  # User has DMs disabled, that's fine
        
        # Log the manual release
        channel_id = get_log_channel_id()
        if channel_id:
            log_channel = interaction.guild.get_channel(int(channel_id))
            if log_channel:
                try:
                    embed = discord.Embed(
                        title="Manual Release",
                        description=f"{user.mention} has been manually released from Canada",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Released by", value=interaction.user.mention, inline=False)
                    embed.add_field(name="Active punishments ended", value=str(len(released_punishments)), inline=False)
                    await log_channel.send(embed=embed)
                except Exception as log_error:
                    logging.error(f"Error sending release log: {log_error}")
        
        success_msg = f"✅ {user.mention} has been released from Canada."
        if released_punishments:
            success_msg += f"\\n🔄 {len(released_punishments)} active punishment(s) marked as completed."
        
        await interaction.followup.send(success_msg)
        logging.info(f"Manual release: {interaction.user} released {user} from Canada")
        
    except discord.Forbidden:
        await interaction.followup.send(f"❌ Bot doesn't have permission to remove the Canada role from {user.mention}. Please check bot permissions.", ephemeral=True)
    except Exception as e:
        logging.error(f"Error releasing user {user.id} from Canada: {e}")
        await interaction.followup.send(f"❌ An error occurred while releasing {user.mention}: {e}", ephemeral=True)

# =============================================================================
# LOG MANAGEMENT COMMANDS
# =============================================================================

@app_commands.command(
    name="edit",
    description="Edit fields in a log entry (user, rule violation, description only)"
)
@app_commands.describe(
    log_number="The log number to edit",
    user="The user to assign the log to",
    rule_violation="The rule violated",
    description="The reason for punishment"
)
async def edit(interaction: discord.Interaction, log_number: int, 
              user: discord.Member = None, rule_violation: str = None, description: str = None):
    """Edit a log entry."""
    if not await user_has_access(interaction):
        await interaction.response.send_message("You don't have permission to use this feature.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Get existing log
    log_data = get_log(log_number, interaction.guild.id)
    if not log_data:
        await interaction.followup.send(f"Log #{log_number} not found.", ephemeral=True)
        return
    
    # Update log
    success = update_log(
        log_number=log_number,
        guild_id=interaction.guild.id,
        user_id=user.id if user else None,
        rule_violation=rule_violation,
        description=description
    )
    
    if not success:
        await interaction.followup.send(f"Failed to update log #{log_number}.", ephemeral=True)
        return
    
    # Update the message in log channel if it exists
    message_id = log_data[4]
    if message_id:
        channel_id = get_log_channel_id()
        if channel_id:
            log_channel = interaction.guild.get_channel(int(channel_id))
            if log_channel:
                try:
                    message = await log_channel.fetch_message(message_id)
                    
                    # Get updated log data
                    updated_log = get_log(log_number, interaction.guild.id)
                    if updated_log:
                        updated_user = interaction.guild.get_member(updated_log[0])
                        if updated_user:
                            embed = create_log_embed(
                                log_number=log_number,
                                user=updated_user,
                                rule_violation=updated_log[1],
                                description=updated_log[2],
                                punishment=updated_log[3],
                                moderator=interaction.user,
                                release_time=updated_log[6],
                                guild_id=interaction.guild.id
                            )
                            embed.add_field(name="Last Edited By", value=interaction.user.mention, inline=False)
                            await message.edit(embed=embed)
                except Exception as e:
                    logging.error(f"Error updating log message: {e}")
    
    await interaction.followup.send(f"✅ Log #{log_number} has been updated.")

@app_commands.command(name="extend", description="Extend a punishment duration by a specified amount")
@app_commands.describe(
    log_number="The log number to extend",
    by="The amount of time to extend by (e.g., '1w', '1d', '12h', '30m')"
)
async def extend(interaction: discord.Interaction, log_number: int, by: str):
    """Extend a punishment duration."""
    if not await user_has_access(interaction):
        await interaction.response.send_message("You don't have permission to use this feature.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Validate extension duration
    extension_seconds = parse_time_duration(by)
    if extension_seconds is None:
        embed = create_error_embed(
            "Invalid Duration",
            "Please use format like '1w', '1d', '12h', '30m'"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Get log data
    log_data = get_log(log_number, interaction.guild.id)
    if not log_data:
        await interaction.followup.send(f"Log #{log_number} not found.", ephemeral=True)
        return
    
    current_release_time = log_data[6]
    if current_release_time is None:
        await interaction.followup.send(f"Log #{log_number} has indefinite punishment and cannot be extended.", ephemeral=True)
        return
    
    # Calculate new release time
    new_release_time = current_release_time + extension_seconds
    
    # Update log
    success = update_log(
        log_number=log_number,
        guild_id=interaction.guild.id,
        release_time=new_release_time
    )
    
    if not success:
        await interaction.followup.send(f"Failed to extend log #{log_number}.", ephemeral=True)
        return
    
    # Calculate new punishment duration for display
    punishment_start = log_data[7]
    new_duration_seconds = new_release_time - punishment_start
    new_punishment = format_duration(new_duration_seconds)
    
    # Reschedule role removal
    user_id = log_data[0]
    await cancel_scheduled_removal(user_id)
    bot = interaction.client
    await schedule_role_removal(bot, interaction.guild.id, user_id, new_release_time)
    
    # Update log message if exists
    message_id = log_data[4]
    if message_id:
        channel_id = get_log_channel_id()
        if channel_id:
            log_channel = interaction.guild.get_channel(int(channel_id))
            if log_channel:
                try:
                    message = await log_channel.fetch_message(message_id)
                    updated_log = get_log(log_number, interaction.guild.id)
                    if updated_log:
                        user = interaction.guild.get_member(updated_log[0])
                        # Get original moderator
                        moderator_id = updated_log[9] if len(updated_log) > 9 and updated_log[9] else None
                        original_moderator = interaction.guild.get_member(moderator_id) if moderator_id else interaction.user
                        
                        if user:
                            embed = create_log_embed(
                                log_number=log_number,
                                user=user,
                                rule_violation=updated_log[1],
                                description=updated_log[2],
                                punishment=new_punishment,
                                moderator=original_moderator,
                                release_time=new_release_time,
                                guild_id=interaction.guild.id
                            )
                            embed.add_field(name="Extended By", value=f"{interaction.user.mention} (+{by})", inline=False)
                            await message.edit(embed=embed)
                except Exception as e:
                    logging.error(f"Error updating extended log message: {e}")
    
    await interaction.followup.send(f"✅ #{log_number} has been extended by {by}. New release time: {format_timestamp(new_release_time, 'F')}")

@app_commands.command(name="reduce", description="Reduce a punishment duration by a specified amount")
@app_commands.describe(
    log_number="The log number to reduce",
    by="The amount of time to reduce by (e.g., '1w', '1d', '12h', '30m')"
)
async def reduce(interaction: discord.Interaction, log_number: int, by: str):
    """Reduce a punishment duration."""
    if not await user_has_access(interaction):
        await interaction.response.send_message("You don't have permission to use this feature.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Validate reduction duration
    reduction_seconds = parse_time_duration(by)
    if reduction_seconds is None:
        embed = create_error_embed(
            "Invalid Duration",
            "Please use format like '1w', '1d', '12h', '30m'"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Get log data
    log_data = get_log(log_number, interaction.guild.id)
    if not log_data:
        await interaction.followup.send(f"Log #{log_number} not found.", ephemeral=True)
        return
    
    current_release_time = log_data[6]
    if current_release_time is None:
        await interaction.followup.send(f"Log #{log_number} has indefinite punishment and cannot be reduced.", ephemeral=True)
        return
    
    # Calculate new release time
    now_ts = int(datetime.now(timezone.utc).timestamp())
    new_release_time = max(now_ts, current_release_time - reduction_seconds)
    
    # Update log
    success = update_log(
        log_number=log_number,
        guild_id=interaction.guild.id,
        release_time=new_release_time
    )
    
    if not success:
        await interaction.followup.send(f"Failed to reduce log #{log_number}.", ephemeral=True)
        return
    
    # Calculate new punishment duration for display
    punishment_start = log_data[7]
    new_duration_seconds = new_release_time - punishment_start
    new_punishment = format_duration(new_duration_seconds)
    
    # Reschedule role removal
    user_id = log_data[0]
    await cancel_scheduled_removal(user_id)
    bot = interaction.client
    await schedule_role_removal(bot, interaction.guild.id, user_id, new_release_time)
    
    # Update log message if exists
    message_id = log_data[4]
    if message_id:
        channel_id = get_log_channel_id()
        if channel_id:
            log_channel = interaction.guild.get_channel(int(channel_id))
            if log_channel:
                try:
                    message = await log_channel.fetch_message(message_id)
                    updated_log = get_log(log_number, interaction.guild.id)
                    if updated_log:
                        user = interaction.guild.get_member(updated_log[0])
                        # Get original moderator
                        moderator_id = updated_log[9] if len(updated_log) > 9 and updated_log[9] else None
                        original_moderator = interaction.guild.get_member(moderator_id) if moderator_id else interaction.user
                        
                        if user:
                            embed = create_log_embed(
                                log_number=log_number,
                                user=user,
                                rule_violation=updated_log[1],
                                description=updated_log[2],
                                punishment=new_punishment,
                                moderator=original_moderator,
                                release_time=new_release_time,
                                guild_id=interaction.guild.id
                            )
                            embed.add_field(name="Reduced By", value=f"{interaction.user.mention} (-{by})", inline=False)
                            await message.edit(embed=embed)
                except Exception as e:
                    logging.error(f"Error updating reduced log message: {e}")
    
    await interaction.followup.send(f"✅ #{log_number} has been reduced by {by}. New punishment: {new_punishment}")

@app_commands.command(name="delete", description="Delete a log entry")
@app_commands.describe(log_number="The log entry number to delete")
async def delete(interaction: discord.Interaction, log_number: int):
    """Delete a log entry."""
    if not await user_has_access(interaction):
        await interaction.response.send_message("You don't have permission to use this feature.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Get log data to check if it exists and get message ID
    log_data = get_log(log_number, interaction.guild.id)
    if not log_data:
        await interaction.followup.send(f"Log #{log_number} not found.", ephemeral=True)
        return
    
    message_id = log_data[4]  # message_id is at index 4
    
    # Delete the log
    success = delete_log(log_number, interaction.guild.id)
    if not success:
        await interaction.followup.send(f"Failed to delete log #{log_number}.", ephemeral=True)
        return
    
    # Delete the message if it exists
    if message_id:
        channel_id = get_log_channel_id()
        if channel_id:
            channel = interaction.guild.get_channel(int(channel_id))
            if channel:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.delete()
                except discord.NotFound:
                    pass  # Message already deleted
                except Exception as e:
                    logging.error(f"Error deleting log message: {e}")
    
    await interaction.followup.send(f"✅ #{log_number} and its message have been deleted.", ephemeral=True)

@app_commands.command(name="retract", description="Retract or unretract a log entry")
@app_commands.describe(log_number="The log entry number to retract or unretract")
async def retract(interaction: discord.Interaction, log_number: int):
    """Retract or unretract a log entry."""
    if not await user_has_access(interaction):
        await interaction.response.send_message("You don't have permission to use this feature.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Get log data
    log_data = get_log(log_number, interaction.guild.id)
    if not log_data:
        await interaction.followup.send(f"Log #{log_number} not found.", ephemeral=True)
        return
    
    message_id = log_data[4]  # message_id is at index 4
    current_retracted = log_data[8]  # retracted is at index 8
    
    new_retracted_status = not bool(current_retracted)
    
    # Update retraction status
    success = retract_log(log_number, interaction.guild.id, new_retracted_status)
    if not success:
        await interaction.followup.send(f"Failed to update log #{log_number}.", ephemeral=True)
        return
    
    # Update the message if it exists
    if message_id:
        channel_id = get_log_channel_id()
        if channel_id:
            channel = interaction.guild.get_channel(int(channel_id))
            if channel:
                try:
                    message = await channel.fetch_message(message_id)
                    
                    # Get updated log data
                    updated_log = get_log(log_number, interaction.guild.id)
                    if updated_log:
                        user = interaction.guild.get_member(updated_log[0])
                        if user:
                            embed = create_log_embed(
                                log_number=log_number,
                                user=user,
                                rule_violation=updated_log[1],
                                description=updated_log[2],
                                punishment=updated_log[3],
                                moderator=interaction.user,
                                release_time=updated_log[6],
                                guild_id=interaction.guild.id
                            )
                            
                            if new_retracted_status:
                                embed.color = discord.Color.orange()
                                embed.title = f"Log #{log_number} [RETRACTED]"
                                embed.add_field(name="Retracted By", value=interaction.user.mention, inline=False)
                            else:
                                embed.add_field(name="Unretracted By", value=interaction.user.mention, inline=False)
                            
                            await message.edit(embed=embed)
                except discord.NotFound:
                    pass  # Message not found
                except Exception as e:
                    logging.error(f"Error updating retracted log message: {e}")
    
    action = "retracted" if new_retracted_status else "unretracted"
    await interaction.followup.send(f"✅ #{log_number} has been {action}.")

# =============================================================================
# USER MANAGEMENT COMMANDS
# =============================================================================

class CheckView(discord.ui.View):
    """View for checking user's warnings and canadas with navigation."""
    
    def __init__(self, user: discord.User, guild_id: int, warnings: List, canadas: List):
        super().__init__(timeout=300)
        self.user = user
        self.guild_id = guild_id
        self.warnings = warnings
        self.canadas = canadas
        self.current_view = "totals"  # totals, warnings, canadas
        self.current_page = 0
        self.items_per_page = 8
        self.update_buttons()
    
    def get_totals_embed(self) -> discord.Embed:
        """Create the totals overview embed."""
        embed = discord.Embed(
            title=f"Record for {self.user.name}",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=self.user.display_avatar.url if self.user.display_avatar else None)
        embed.add_field(name="Warnings", value=str(len(self.warnings)), inline=True)
        embed.add_field(name="Canadas", value=str(len(self.canadas)), inline=True)
        
        if len(self.warnings) == 0 and len(self.canadas) == 0:
            embed.description = "This user has a clean record!"
        else:
            embed.description = "Click a button below to view details."
        
        return embed
    
    def get_warnings_embeds(self) -> List[discord.Embed]:
        """Create paginated embeds for warnings."""
        if not self.warnings:
            embed = discord.Embed(
                title=f"⚠️ Warnings for {self.user.name}",
                description="No warnings found.",
                color=discord.Color.orange()
            )
            return [embed]
        
        embeds = []
        for i in range(0, len(self.warnings), self.items_per_page):
            page_warnings = self.warnings[i:i + self.items_per_page]
            embed = discord.Embed(
                title=f"⚠️ Warnings for {self.user.name}",
                color=discord.Color.orange()
            )
            
            for warning_number, reason, created_at in page_warnings:
                timestamp = f"<t:{created_at}:R>" if created_at else "Unknown"
                embed.add_field(
                    name=f"Warning #{warning_number}",
                    value=f"{reason[:100]}{'...' if len(reason) > 100 else ''}\n{timestamp}",
                    inline=False
                )
            
            page_num = (i // self.items_per_page) + 1
            total_pages = (len(self.warnings) + self.items_per_page - 1) // self.items_per_page
            embed.set_footer(text=f"Page {page_num}/{total_pages} • Total: {len(self.warnings)} warnings")
            embeds.append(embed)
        
        return embeds
    
    def get_canadas_embeds(self) -> List[discord.Embed]:
        """Create paginated embeds for canadas."""
        if not self.canadas:
            embed = discord.Embed(
                title=f"🍁 Canadas for {self.user.name}",
                description="No canadas found.",
                color=discord.Color.red()
            )
            return [embed]
        
        embeds = []
        for i in range(0, len(self.canadas), self.items_per_page):
            page_canadas = self.canadas[i:i + self.items_per_page]
            embed = discord.Embed(
                title=f"🍁 Canadas for {self.user.name}",
                color=discord.Color.red()
            )
            
            for log_number, rule_violation, description, retracted in page_canadas:
                embed.add_field(
                    name=f"#{log_number} - {rule_violation[:50]}{'...' if len(rule_violation) > 50 else ''}",
                    value=description[:100] + ('...' if len(description) > 100 else ''),
                    inline=False
                )
            
            page_num = (i // self.items_per_page) + 1
            total_pages = (len(self.canadas) + self.items_per_page - 1) // self.items_per_page
            embed.set_footer(text=f"Page {page_num}/{total_pages} • Total: {len(self.canadas)} canadas")
            embeds.append(embed)
        
        return embeds
    
    def update_buttons(self):
        """Update button visibility based on current view."""
        self.clear_items()
        
        if self.current_view == "totals":
            # Show warnings and canadas buttons
            warnings_btn = discord.ui.Button(
                label=f"Warnings ({len(self.warnings)})", 
                style=discord.ButtonStyle.secondary, 
                emoji="⚠️",
                disabled=len(self.warnings) == 0
            )
            warnings_btn.callback = self.show_warnings
            self.add_item(warnings_btn)
            
            canadas_btn = discord.ui.Button(
                label=f"Canadas ({len(self.canadas)})", 
                style=discord.ButtonStyle.danger, 
                emoji="🍁",
                disabled=len(self.canadas) == 0
            )
            canadas_btn.callback = self.show_canadas
            self.add_item(canadas_btn)
        else:
            # Show back button and pagination
            back_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.primary, emoji="◀️")
            back_btn.callback = self.go_back
            self.add_item(back_btn)
            
            # Get total pages for current view
            if self.current_view == "warnings":
                total_pages = max(1, (len(self.warnings) + self.items_per_page - 1) // self.items_per_page)
            else:
                total_pages = max(1, (len(self.canadas) + self.items_per_page - 1) // self.items_per_page)
            
            if total_pages > 1:
                prev_btn = discord.ui.Button(
                    label="◀", 
                    style=discord.ButtonStyle.secondary,
                    disabled=self.current_page == 0
                )
                prev_btn.callback = self.prev_page
                self.add_item(prev_btn)
                
                next_btn = discord.ui.Button(
                    label="▶", 
                    style=discord.ButtonStyle.secondary,
                    disabled=self.current_page >= total_pages - 1
                )
                next_btn.callback = self.next_page
                self.add_item(next_btn)
    
    async def show_warnings(self, interaction: discord.Interaction):
        self.current_view = "warnings"
        self.current_page = 0
        self.update_buttons()
        embeds = self.get_warnings_embeds()
        await interaction.response.edit_message(embed=embeds[0], view=self)
    
    async def show_canadas(self, interaction: discord.Interaction):
        self.current_view = "canadas"
        self.current_page = 0
        self.update_buttons()
        embeds = self.get_canadas_embeds()
        await interaction.response.edit_message(embed=embeds[0], view=self)
    
    async def go_back(self, interaction: discord.Interaction):
        self.current_view = "totals"
        self.current_page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_totals_embed(), view=self)
    
    async def prev_page(self, interaction: discord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            if self.current_view == "warnings":
                embeds = self.get_warnings_embeds()
            else:
                embeds = self.get_canadas_embeds()
            await interaction.response.edit_message(embed=embeds[self.current_page], view=self)
    
    async def next_page(self, interaction: discord.Interaction):
        if self.current_view == "warnings":
            total_pages = max(1, (len(self.warnings) + self.items_per_page - 1) // self.items_per_page)
            embeds = self.get_warnings_embeds()
        else:
            total_pages = max(1, (len(self.canadas) + self.items_per_page - 1) // self.items_per_page)
            embeds = self.get_canadas_embeds()
        
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=embeds[self.current_page], view=self)
    
    async def on_timeout(self):
        """Disable buttons when view times out."""
        for item in self.children:
            item.disabled = True

@app_commands.command(name="check", description="Check a user's warnings and punishments")
@app_commands.describe(user="The user to check")
async def check(interaction: discord.Interaction, user: discord.User):
    """Check a user's warnings and punishments."""
    await interaction.response.defer(ephemeral=False)
    
    # Get warnings and canadas for the user
    warnings = get_user_warnings(user.id, interaction.guild.id)
    canadas = get_user_punishments(user.id, interaction.guild.id, include_retracted=False)
    
    # Create the view with data
    view = CheckView(user, interaction.guild.id, warnings, canadas)
    
    # Send the totals embed
    await interaction.followup.send(embed=view.get_totals_embed(), view=view)

# =============================================================================
# TEMP BAN MANAGEMENT COMMANDS
# =============================================================================

@app_commands.command(name="tempbans", description="List all active temp bans")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def tempbans(interaction: discord.Interaction):
    """List all active temp bans with their unban times."""
    await interaction.response.defer(ephemeral=True)
    
    active_bans = get_active_temp_bans(interaction.guild.id)
    
    if not active_bans:
        embed = create_info_embed(
            "No Active Temp Bans",
            "There are no active temporary bans scheduled."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    embed = discord.Embed(
        title="⏰ Active Temp Bans",
        description=f"**{len(active_bans)}** active temp ban(s)",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc)
    )
    
    for ban in active_bans[:25]:  # Discord embed field limit
        user_id = ban.get("user_id")
        unban_time = ban.get("unban_time")
        duration = ban.get("duration", "Unknown")
        log_number = ban.get("log_number", "?")
        reason = ban.get("reason", "No reason provided")
        
        try:
            user = await interaction.client.fetch_user(user_id)
            user_str = f"{user.name} ({user_id})"
        except:
            user_str = f"Unknown User ({user_id})"
        
        unban_str = f"<t:{unban_time}:R>" if unban_time else "Never"
        
        embed.add_field(
            name=f"Log #{log_number} - {user_str}",
            value=f"**Duration:** {duration}\n**Unban:** {unban_str}\n**Reason:** {reason[:100]}{'...' if len(reason) > 100 else ''}",
            inline=False
        )
    
    if len(active_bans) > 25:
        embed.set_footer(text=f"Showing 25 of {len(active_bans)} temp bans")
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@app_commands.command(name="tempban_cancel", description="Cancel a temp ban and unban a user early")
@app_commands.describe(
    user="The user to unban early",
    reason="Reason for cancelling the temp ban"
)
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def tempban_cancel(interaction: discord.Interaction, user: discord.User, reason: str = "No reason provided"):
    """Cancel a temp ban and unban a user early."""
    await interaction.response.defer(ephemeral=False)
    
    # Check if user has an active temp ban
    temp_ban = get_temp_ban_for_user(user.id, interaction.guild.id)
    
    if not temp_ban:
        embed = create_error_embed(
            "No Active Temp Ban",
            f"{user.mention} does not have an active temp ban."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    log_number = temp_ban.get("log_number", "?")
    
    try:
        # Cancel the scheduled unban task
        await cancel_temp_unban(user.id)
        
        # Mark the temp ban as cancelled in storage
        cancel_temp_ban_record(user.id, interaction.guild.id, interaction.user.id)
        
        # Unban the user
        await interaction.guild.unban(user, reason=f"Temp ban cancelled by {interaction.user.name}: {reason}")
        
        # Log to ban log channel
        ban_log_channel = interaction.guild.get_channel(BAN_LOG_CHANNEL_ID)
        if ban_log_channel:
            log_embed = discord.Embed(
                title="🔓 Temp Ban Cancelled Early",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=True)
            log_embed.add_field(name="Log #", value=str(log_number), inline=True)
            log_embed.add_field(name="Cancelled By", value=interaction.user.mention, inline=True)
            log_embed.add_field(name="Reason", value=reason, inline=False)
            log_embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
            
            try:
                await ban_log_channel.send(embed=log_embed)
            except Exception as e:
                logging.error(f"Error sending cancel log: {e}")
        
        embed = create_success_embed(
            "Temp Ban Cancelled",
            f"✅ {user.mention} has been unbanned early.\n\n**Log #:** {log_number}\n**Reason:** {reason}"
        )
        await interaction.followup.send(embed=embed)
        
        # Try to DM the user
        try:
            dm_embed = discord.Embed(
                title="Your Temp Ban Has Been Cancelled",
                description="Your temporary ban has been cancelled early. You can now rejoin the server.",
                color=discord.Color.green()
            )
            dm_embed.add_field(name="Reason", value=reason, inline=False)
            dm_embed.add_field(
                name="Rejoin Link",
                value="https://discord.gg/virtualcongress",
                inline=False
            )
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            pass
        
    except discord.NotFound:
        embed = create_error_embed(
            "User Not Banned",
            f"{user.mention} is not currently banned from the server."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    except discord.Forbidden:
        embed = create_error_embed(
            "Permission Error",
            "I don't have permission to unban users."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        embed = create_error_embed(
            "Error",
            f"An error occurred: {e}"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@app_commands.command(name="tempban", description="Directly apply a temp ban to a user")
@app_commands.describe(
    user="The user to temp ban",
    duration="Duration of the ban (e.g., '2mo', '6mo', '1w')",
    reason="Reason for the temp ban"
)
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def tempban(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str):
    """Directly apply a temp ban to a user without going through Canada first."""
    await interaction.response.defer(ephemeral=False)
    
    # Protected roles
    PROTECTED_ROLE_IDS = [654477469004595221, 707781265985896469]  # Admin, Moderator
    
    # Check if user has protected roles
    user_role_ids = [role.id for role in user.roles]
    if any(role_id in user_role_ids for role_id in PROTECTED_ROLE_IDS):
        embed = create_error_embed(
            "Cannot Temp Ban",
            f"{user.mention} has Admin or Moderator role and cannot be temp banned."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Validate duration
    duration_seconds = parse_time_duration(duration)
    if duration_seconds is None and duration.lower() != "indefinite":
        embed = create_error_embed(
            "Invalid Duration",
            "Please use a valid duration format: '2mo', '6mo', '1w', '30d', etc."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Calculate unban time
    unban_time = int(datetime.now(timezone.utc).timestamp()) + duration_seconds if duration_seconds else None
    
    try:
        # Create a log entry for this temp ban
        log_number = create_log(
            guild_id=interaction.guild.id,
            user_id=user.id,
            rule_violation="Direct Temp Ban",
            description=reason,
            punishment=f"Temp Ban ({duration})",
            release_time=None,  # Not a Canada punishment
            punishment_start=int(datetime.now(timezone.utc).timestamp()),
            moderator_id=interaction.user.id
        )
        
        # Ban the user
        await user.ban(reason=f"Temp ban by {interaction.user.name} (Log #{log_number}): {reason}", delete_message_days=0)
        
        # Track the temp ban
        create_temp_ban(
            guild_id=interaction.guild.id,
            user_id=user.id,
            moderator_id=interaction.user.id,
            log_number=log_number,
            duration=duration,
            unban_time=unban_time,
            reason=reason
        )
        
        # Schedule the automatic unban
        if unban_time:
            await schedule_temp_unban(
                interaction.client,
                interaction.guild.id,
                user.id,
                unban_time,
                log_number
            )
        
        # Log to ban log channel
        ban_log_channel = interaction.guild.get_channel(BAN_LOG_CHANNEL_ID)
        if ban_log_channel:
            log_embed = discord.Embed(
                title="⛔ Direct Temp Ban Applied",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=True)
            log_embed.add_field(name="Log #", value=str(log_number), inline=True)
            log_embed.add_field(name="Duration", value=duration, inline=True)
            log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
            if unban_time:
                log_embed.add_field(name="Unban Time", value=f"<t:{unban_time}:F>", inline=True)
            log_embed.add_field(name="Reason", value=reason, inline=False)
            log_embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
            
            try:
                await ban_log_channel.send(embed=log_embed)
            except Exception as e:
                logging.error(f"Error sending ban log: {e}")
        
        # Send confirmation
        unban_str = f"<t:{unban_time}:F>" if unban_time else "Never (indefinite)"
        embed = create_success_embed(
            "Temp Ban Applied",
            f"✅ {user.mention} has been temp banned.\n\n"
            f"**Log #:** {log_number}\n"
            f"**Duration:** {duration}\n"
            f"**Unban:** {unban_str}\n"
            f"**Reason:** {reason}"
        )
        await interaction.followup.send(embed=embed)
        
        # Try to DM the user
        try:
            dm_embed = discord.Embed(
                title="You Have Been Temp Banned",
                description=f"You have been temporarily banned from the server.",
                color=discord.Color.red()
            )
            dm_embed.add_field(name="Duration", value=duration, inline=True)
            if unban_time:
                dm_embed.add_field(name="Unban Time", value=f"<t:{unban_time}:F>", inline=True)
            dm_embed.add_field(name="Reason", value=reason, inline=False)
            dm_embed.add_field(
                name="How to Appeal",
                value="If you believe this decision was incorrect, please see [this form](https://dyno.gg/form/27f3392e) for information on how to appeal.",
                inline=False
            )
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            pass
        
    except discord.Forbidden:
        embed = create_error_embed(
            "Permission Error",
            "I don't have permission to ban this user."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        embed = create_error_embed(
            "Error",
            f"An error occurred: {e}"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

# =============================================================================
# WARNING COMMANDS
# =============================================================================

def has_mod_or_admin_role(interaction: discord.Interaction) -> bool:
    """Check if user has Moderator or Admin role."""
    user_role_ids = [role.id for role in interaction.user.roles]
    return MODERATOR_ROLE_ID in user_role_ids or ADMIN_ROLE_ID in user_role_ids or interaction.user.guild_permissions.administrator

@app_commands.command(name="warn", description="Warn a user")
@app_commands.describe(
    user="The user to warn",
    reason="The reason for the warning"
)
@app_commands.guild_only()
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    """Warn a user and log it."""
    # Check permissions
    if not has_mod_or_admin_role(interaction):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=False)
    
    # Create the warning in database
    warning_number = create_warning(
        guild_id=interaction.guild.id,
        user_id=user.id,
        reason=reason,
        moderator_id=interaction.user.id
    )
    
    if warning_number == -1:
        embed = create_error_embed("Error", "Failed to create warning.")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Send confirmation in the command channel
    confirm_embed = discord.Embed(
        description=f"✅ {user.mention} has been warned.",
        color=discord.Color.green()
    )
    await interaction.followup.send(embed=confirm_embed)
    
    # Create the log embed for the warning log channel
    log_embed = discord.Embed(
        title=f"Warning #{warning_number}",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc)
    )
    log_embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False)
    log_embed.add_field(name="Reason", value=reason, inline=False)
    log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
    
    # Get total warnings for this user
    total_warnings = get_warning_count(user.id, interaction.guild.id)
    log_embed.set_footer(text=f"Total warnings for user: {total_warnings}")
    
    # Send to warning log channel
    log_channel = interaction.guild.get_channel(WARNING_LOG_CHANNEL_ID)
    if log_channel:
        try:
            log_message = await log_channel.send(embed=log_embed)
            # Update warning with message ID
            update_warning_message_id(warning_number, interaction.guild.id, log_message.id)
        except Exception as e:
            logging.error(f"Failed to send warning log: {e}")
    
    # Try to DM the user
    try:
        dm_embed = discord.Embed(
            title="⚠️ You have received a warning",
            description=f"You have been warned in **{interaction.guild.name}**.",
            color=discord.Color.orange()
        )
        dm_embed.add_field(name="Reason", value=reason, inline=False)
        dm_embed.add_field(name="Warning #", value=str(warning_number), inline=True)
        dm_embed.add_field(name="Total Warnings", value=str(total_warnings), inline=True)
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        pass  # User has DMs disabled, continue without error

@app_commands.command(name="warn_remove", description="Remove a warning from a user")
@app_commands.describe(
    warning_number="The warning number to remove"
)
@app_commands.guild_only()
async def warn_remove(interaction: discord.Interaction, warning_number: int):
    """Remove a warning by its number."""
    # Check permissions
    if not has_mod_or_admin_role(interaction):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    # Get the warning first to find the message ID
    warning = get_warning(warning_number, interaction.guild.id)
    
    if not warning:
        embed = create_error_embed("Not Found", f"Warning #{warning_number} not found.")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Delete the warning log message if it exists
    if warning.get("message_id"):
        log_channel = interaction.guild.get_channel(WARNING_LOG_CHANNEL_ID)
        if log_channel:
            try:
                message = await log_channel.fetch_message(warning["message_id"])
                await message.delete()
            except discord.NotFound:
                pass  # Message already deleted
            except Exception as e:
                logging.error(f"Error deleting warning log message: {e}")
    
    # Delete the warning from database
    success = delete_warning(warning_number, interaction.guild.id)
    
    if success:
        await interaction.followup.send(f"✅ Warning #{warning_number} has been removed.", ephemeral=True)
    else:
        embed = create_error_embed("Error", "Failed to remove warning.")
        await interaction.followup.send(embed=embed, ephemeral=True)

# All command functions that need to be registered
ALL_COMMANDS = [
    setup, canada, edit, extend, reduce, delete, retract, check, release,
    tempbans, tempban_cancel, tempban, warn, warn_remove
]
