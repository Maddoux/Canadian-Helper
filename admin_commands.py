"""
Administrative and utility commands for the Canadian Helper bot.
"""

import os
import re
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands

from bot_config import CANADA_ROLE_ID, ALLOWED_GUILD_ID, get_canada_role_id
from data_manager import *
from utils import *
from events import get_scheduled_removals, get_scheduled_unbans

# =============================================================================
# DEBUGGING COMMANDS
# =============================================================================

@app_commands.command(name="list_roles", description="List all roles in the server with their IDs")
@app_commands.default_permissions(administrator=True)
async def list_roles(interaction: discord.Interaction):
    """List all roles in the server for debugging."""
    await interaction.response.defer(ephemeral=True)
    
    roles = sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True)
    
    role_list = []
    for role in roles:
        if role.name != "@everyone":  # Skip @everyone role
            role_list.append(f"**{role.name}** - ID: `{role.id}`")
    
    # Split into chunks if too long
    if len(role_list) > 20:
        chunk_size = 20
        chunks = [role_list[i:i+chunk_size] for i in range(0, len(role_list), chunk_size)]
        
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"Server Roles (Page {i+1}/{len(chunks)})",
                description="\n".join(chunk),
                color=discord.Color.blue()
            )
            if i == 0:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(
            title="Server Roles",
            description="\n".join(role_list) if role_list else "No roles found",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@app_commands.command(name="debug_canada_role", description="Debug Canada role configuration")
@app_commands.default_permissions(administrator=True)
async def debug_canada_role(interaction: discord.Interaction):
    """Debug Canada role configuration."""
    await interaction.response.defer(ephemeral=True)
    
    # Get configured role ID
    configured_id = get_canada_role_id()
    fallback_id = CANADA_ROLE_ID
    
    embed = discord.Embed(title="Canada Role Debug Info", color=discord.Color.blue())
    
    embed.add_field(
        name="Configured Role ID",
        value=f"`{configured_id}`" if configured_id else "Not set",
        inline=False
    )
    
    embed.add_field(
        name="Fallback Role ID",
        value=f"`{fallback_id}`",
        inline=False
    )
    
    # Try to find the role using different methods
    if configured_id:
        try:
            role_id = int(configured_id)
            role = interaction.guild.get_role(role_id)
            
            if role:
                embed.add_field(
                    name="✅ Role Found",
                    value=f"**{role.name}** (ID: `{role.id}`)\nPosition: {role.position}\nColor: {role.color}",
                    inline=False
                )
            else:
                embed.add_field(
                    name="❌ Role Not Found",
                    value=f"Role with ID `{role_id}` does not exist in this server",
                    inline=False
                )
                
                # Check if bot can see roles
                bot_member = interaction.guild.get_member(interaction.client.user.id)
                embed.add_field(
                    name="Bot Permissions",
                    value=f"View Channels: {bot_member.guild_permissions.view_channel}\nManage Roles: {bot_member.guild_permissions.manage_roles}",
                    inline=False
                )
                
        except ValueError:
            embed.add_field(
                name="❌ Invalid Role ID",
                value=f"Configured role ID `{configured_id}` is not a valid integer",
                inline=False
            )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# =============================================================================
# ROLE MANAGEMENT COMMANDS
# =============================================================================

@app_commands.command(name="manage_roles", description="Manage which roles can use the bot")
@app_commands.describe(
    action="Add or remove roles",
    roles="Ping the roles you want to add or remove (e.g., @Role1 @Role2)"
)
@app_commands.choices(action=[
    app_commands.Choice(name="Add Roles", value="add"),
    app_commands.Choice(name="Remove Roles", value="remove"),
    app_commands.Choice(name="List Current Roles", value="list")
])
@app_commands.default_permissions(administrator=True)
async def manage_roles(interaction: discord.Interaction, action: str, roles: str = None):
    """Manage which roles can use the bot commands."""
    await interaction.response.defer(ephemeral=True)
    
    guild_id = interaction.guild.id
    
    if action == "list":
        allowed_role_ids = get_allowed_roles(guild_id)
        if not allowed_role_ids:
            await interaction.followup.send("No roles are currently allowed to use the bot.", ephemeral=True)
            return
        
        role_mentions = []
        for role_id in allowed_role_ids:
            role = interaction.guild.get_role(role_id)
            if role:
                role_mentions.append(role.mention)
            else:
                role_mentions.append(f"Unknown Role (ID: {role_id})")
        
        embed = create_info_embed(
            "Allowed Roles",
            "\\n".join(role_mentions)
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    if not roles:
        await interaction.followup.send("Please provide roles to add or remove.", ephemeral=True)
        return
    
    # Extract role IDs from role mentions
    role_pattern = r'<@&(\\d+)>'
    role_ids = [int(match) for match in re.findall(role_pattern, roles)]
    
    if not role_ids:
        await interaction.followup.send("No valid role mentions found. Please mention roles like @RoleName.", ephemeral=True)
        return
    
    # Verify roles exist in the guild
    valid_roles = []
    invalid_roles = []
    for role_id in role_ids:
        role = interaction.guild.get_role(role_id)
        if role:
            valid_roles.append(role)
        else:
            invalid_roles.append(str(role_id))
    
    if not valid_roles:
        await interaction.followup.send(f"None of the provided roles were found in this server.", ephemeral=True)
        return
    
    try:
        if action == "add":
            added_roles = []
            already_added = []
            
            for role in valid_roles:
                if add_allowed_role(guild_id, role.id):
                    added_roles.append(role.mention)
                else:
                    already_added.append(role.mention)
            
            result_parts = []
            if added_roles:
                result_parts.append(f"**Added roles:** {', '.join(added_roles)}")
            if already_added:
                result_parts.append(f"**Already allowed:** {', '.join(already_added)}")
            if invalid_roles:
                result_parts.append(f"**Invalid roles:** {', '.join(invalid_roles)}")
            
            await interaction.followup.send("\\n".join(result_parts), ephemeral=True)
            
        elif action == "remove":
            removed_roles = []
            not_found = []
            
            for role in valid_roles:
                if remove_allowed_role(guild_id, role.id):
                    removed_roles.append(role.mention)
                else:
                    not_found.append(role.mention)
            
            result_parts = []
            if removed_roles:
                result_parts.append(f"**Removed roles:** {', '.join(removed_roles)}")
            if not_found:
                result_parts.append(f"**Not in allowed list:** {', '.join(not_found)}")
            if invalid_roles:
                result_parts.append(f"**Invalid roles:** {', '.join(invalid_roles)}")
            
            await interaction.followup.send("\\n".join(result_parts), ephemeral=True)
            
    except Exception as e:
        logging.error(f"Error managing roles for guild {guild_id}: {e}")
        await interaction.followup.send("An error occurred while managing roles. Please try again.", ephemeral=True)

# =============================================================================
# TESTING AND DEBUG COMMANDS
# =============================================================================

@app_commands.command(name="check_config", description="Check current bot configuration")
@app_commands.default_permissions(administrator=True)
async def check_config(interaction: discord.Interaction):
    """Check what configuration is currently stored."""
    await interaction.response.defer(ephemeral=True)
    
    try:
        config_items = get_all_config()
        
        if not config_items:
            embed = create_info_embed(
                "Configuration",
                "No configuration items found. Use `/setup` commands to configure the bot."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Bot Configuration",
            description="Current settings:",
            color=discord.Color.blue()
        )
        
        for key, value in config_items.items():
            if "channel" in key.lower():
                # Try to get channel mention
                try:
                    channel = interaction.guild.get_channel(int(value))
                    display_value = channel.mention if channel else f"Channel not found (ID: {value})"
                except (ValueError, TypeError):
                    display_value = value
            else:
                display_value = value
            
            embed.add_field(
                name=key.replace('_', ' ').title(),
                value=display_value,
                inline=False
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        logging.error(f"Error checking configuration: {e}")
        await interaction.followup.send(f"Error checking configuration: {e}", ephemeral=True)

# =============================================================================
# CLEANUP AND MAINTENANCE COMMANDS
# =============================================================================

@app_commands.command(name="cleanup_punishments", description="Manually trigger cleanup of expired punishments")
@app_commands.default_permissions(administrator=True)
async def cleanup_punishments(interaction: discord.Interaction):
    """Manually trigger cleanup of expired punishments."""
    await interaction.response.defer(ephemeral=True)
    
    try:
        expired_punishments = get_expired_punishments(interaction.guild.id)
        
        if not expired_punishments:
            embed = create_info_embed(
                "Cleanup Complete",
                "No expired punishments found to clean up."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        cleaned_count = 0
        errors = []
        
        canada_role_id = get_canada_role_id()
        canada_role = interaction.guild.get_role(canada_role_id)
        
        for user_id, guild_id, release_time in expired_punishments:
            try:
                member = interaction.guild.get_member(user_id)
                if not member:
                    try:
                        member = await interaction.guild.fetch_member(user_id)
                    except discord.NotFound:
                        # Member left, mark as completed
                        mark_punishment_completed(user_id, guild_id, release_time)
                        cleaned_count += 1
                        continue
                
                if canada_role and canada_role in member.roles:
                    await member.remove_roles(canada_role, reason="Manual cleanup - punishment expired")
                
                mark_punishment_completed(user_id, guild_id, release_time)
                cleaned_count += 1
                
            except Exception as e:
                errors.append(f"User {user_id}: {str(e)[:100]}")
        
        result_msg = f"✅ **Cleanup completed!**\\n\\n**Cleaned up:** {cleaned_count} expired punishments"
        if errors:
            result_msg += f"\\n\\n**Errors ({len(errors)}):**\\n" + "\\n".join(errors[:5])
            if len(errors) > 5:
                result_msg += f"\\n... and {len(errors) - 5} more errors"
        
        await interaction.followup.send(result_msg, ephemeral=True)
        
    except Exception as e:
        logging.error(f"Error in manual cleanup: {e}")
        await interaction.followup.send(f"Error during cleanup: {e}", ephemeral=True)

@app_commands.command(name="punishment_status", description="Check active punishment schedules and status")
@app_commands.default_permissions(administrator=True)
async def punishment_status(interaction: discord.Interaction):
    """Check the status of active punishment schedules."""
    await interaction.response.defer(ephemeral=True)
    
    try:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        
        # Test data storage first
        try:
            stats = get_data_stats()
            db_status = "Connected"
        except Exception as db_error:
            db_status = f"Error: {str(db_error)[:50]}"
            embed = create_error_embed(
                "Data Storage Error",
                f"Could not access data storage: {db_error}"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        all_active = get_active_punishments(interaction.guild.id)
        active_punishments = [(user_id, release_time) for user_id, guild_id, release_time, punishment_start in all_active]
        
        if not active_punishments:
            embed = create_info_embed(
                "No Active Punishments",
                "There are currently no active punishments in this server."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Active Punishment Status",
            color=discord.Color.blue()
        )
        
        scheduled_removals = get_scheduled_removals()
        scheduled_count = len(scheduled_removals)
        active_count = len(active_punishments)
        overdue_count = 0
        upcoming_count = 0
        
        for user_id, release_time in active_punishments:
            if release_time <= now_ts:
                overdue_count += 1
            else:
                upcoming_count += 1
        
        embed.add_field(
            name="🔌 System Status",
            value=f"**Data Storage:** {db_status}\\n**Scheduled Tasks:** {scheduled_count}\\n**Cleanup Task:** Running every 1 minute",
            inline=False
        )
        
        embed.add_field(
            name="📊 Punishment Summary",
            value=f"**Total Active:** {active_count}\\n**Overdue:** {overdue_count}\\n**Upcoming:** {upcoming_count}",
            inline=False
        )
        
        if overdue_count > 0:
            embed.add_field(
                name="⚠️ Notice",
                value=f"There are {overdue_count} overdue punishments. Use `/cleanup_punishments` to clean them up.",
                inline=False
            )
        
        # Show next few expirations with more detail
        upcoming = [(user_id, release_time) for user_id, release_time in active_punishments if release_time > now_ts]
        upcoming.sort(key=lambda x: x[1])
        
        if upcoming:
            next_expiry_text = []
            for i, (user_id, release_time) in enumerate(upcoming[:5]):
                member = interaction.guild.get_member(user_id)
                user_display = member.display_name if member else f"User {user_id}"
                
                time_str = format_timestamp(release_time, "R")
                task_indicator = "🕒" if user_id in scheduled_removals else "❌"
                next_expiry_text.append(f"{task_indicator} **{user_display}:** {time_str}")
            
            embed.add_field(
                name="Next Expirations",
                value="\\n".join(next_expiry_text) + "\\n\\n🕒 = Scheduled task active\\n❌ = No scheduled task",
                inline=False
            )
        
        # Show overdue punishments
        if overdue_count > 0:
            overdue = [(user_id, release_time) for user_id, release_time in active_punishments if release_time <= now_ts]
            overdue_text = []
            canada_role_id = get_canada_role_id()
            canada_role = interaction.guild.get_role(canada_role_id)
            
            for i, (user_id, release_time) in enumerate(overdue[:5]):
                member = interaction.guild.get_member(user_id)
                if member:
                    user_display = member.display_name
                    has_role = canada_role and canada_role in member.roles
                    role_indicator = "🟥" if has_role else "✅"
                else:
                    user_display = f"User {user_id}"
                    role_indicator = "❓"
                
                time_str = format_timestamp(release_time, "R")
                overdue_text.append(f"{role_indicator} **{user_display}:** {time_str}")
            
            embed.add_field(
                name="🚨 Overdue Punishments",
                value="\\n".join(overdue_text) + "\\n\\n🟥 = Still has Canada role\\n✅ = Role already removed",
                inline=False
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        logging.error(f"Error checking punishment status: {e}")
        embed = discord.Embed(
            title="❌ Error Checking Status",
            description=f"```{str(e)[:1000]}```",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@app_commands.command(name="check_permissions", description="Check bot permissions in configured channels")
@app_commands.default_permissions(administrator=True)
async def check_permissions(interaction: discord.Interaction):
    """Check bot permissions in configured channels."""
    await interaction.response.defer(ephemeral=True)
    
    try:
        config_items = get_all_config()
        
        embed = discord.Embed(
            title="Bot Permissions Check",
            description="Checking bot permissions in configured channels...",
            color=discord.Color.blue()
        )
        
        bot_member = interaction.guild.me
        
        # Check configured channels
        for key, value in config_items.items():
            if "channel" not in key.lower():
                continue
                
            channel = interaction.guild.get_channel(int(value)) if value else None
            
            if not channel:
                embed.add_field(
                    name=f"{key.replace('_', ' ').title()}",
                    value=f"❌ Channel not found (ID: {value})",
                    inline=False
                )
                continue
            
            perms = channel.permissions_for(bot_member)
            
            required_perms = {
                "View Channel": perms.view_channel,
                "Send Messages": perms.send_messages,
                "Embed Links": perms.embed_links,
                "Read Message History": perms.read_message_history
            }
            
            status_lines = []
            all_good = True
            
            for perm_name, has_perm in required_perms.items():
                status = "✅" if has_perm else "❌"
                status_lines.append(f"{status} {perm_name}")
                if not has_perm:
                    all_good = False
            
            overall_status = "✅ All permissions OK" if all_good else "⚠️ Missing permissions"
            
            embed.add_field(
                name=f"{key.replace('_', ' ').title()} - {channel.mention}",
                value=f"{overall_status}\\n" + "\\n".join(status_lines),
                inline=False
            )
        
        # Check Canada role permissions
        canada_role_id = get_canada_role_id()
        canada_role = interaction.guild.get_role(canada_role_id)
        if canada_role:
            can_manage_roles = bot_member.guild_permissions.manage_roles
            role_hierarchy_ok = bot_member.top_role > canada_role
            
            role_status = []
            if can_manage_roles:
                role_status.append("✅ Manage Roles permission")
            else:
                role_status.append("❌ Manage Roles permission")
            
            if role_hierarchy_ok:
                role_status.append("✅ Role hierarchy OK")
            else:
                role_status.append("❌ Bot role must be above Canada role")
            
            overall_role_status = "✅ Can assign Canada role" if (can_manage_roles and role_hierarchy_ok) else "⚠️ Cannot assign Canada role"
            
            embed.add_field(
                name=f"Canada Role - {canada_role.mention}",
                value=f"{overall_role_status}\\n" + "\\n".join(role_status),
                inline=False
            )
        else:
            embed.add_field(
                name="Canada Role",
                value=f"Role not found (ID: {CANADA_ROLE_ID})",
                inline=False
            )
        
        if not config_items:
            embed.description = "No channels configured yet. Use `/setup` to configure channels."
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        logging.error(f"Error checking permissions: {e}")
        await interaction.followup.send(f"Error checking permissions: {e}", ephemeral=True)

# =============================================================================
# SYNC COMMAND
# =============================================================================

@app_commands.command(name="sync", description="Force sync slash commands with Discord")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def sync(interaction: discord.Interaction):
    """Force sync slash commands to update them in Discord."""
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Clear global commands first to avoid conflicts
        interaction.client.tree.clear_commands(guild=None)
        
        # Copy global commands to guild and sync
        guild = discord.Object(id=interaction.guild.id)
        interaction.client.tree.copy_global_to(guild=guild)
        synced = await interaction.client.tree.sync(guild=guild)
        
        # Also clear global commands from Discord
        await interaction.client.tree.sync()
        
        # Get command names for display
        command_names = [cmd.name for cmd in synced]
        
        embed = discord.Embed(
            title="✅ Commands Synced",
            description=f"Successfully synced **{len(synced)}** slash commands to this server.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Synced Commands",
            value=", ".join(f"`/{name}`" for name in sorted(command_names)[:20]) + 
                  (f"\n... and {len(command_names) - 20} more" if len(command_names) > 20 else ""),
            inline=False
        )
        embed.set_footer(text="Commands should now be updated in Discord")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        logging.info(f"Force synced {len(synced)} commands by {interaction.user}")
        
    except Exception as e:
        logging.error(f"Error force syncing commands: {e}")
        embed = discord.Embed(
            title="❌ Sync Failed",
            description=f"Error syncing commands: {e}",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

# =============================================================================
# EXPORTED COMMANDS LIST
# =============================================================================
# All admin command functions that need to be registered
ALL_ADMIN_COMMANDS = [
    list_roles, debug_canada_role, manage_roles, check_config, cleanup_punishments, 
    punishment_status, check_permissions, sync
]
