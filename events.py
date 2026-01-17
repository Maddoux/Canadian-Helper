"""
Discord bot event handlers.
"""

import discord
import logging
import asyncio
from datetime import datetime, timezone
from bot_config import CANADA_ROLE_ID, ALLOWED_GUILD_ID, get_canada_role_id
from data_manager import get_active_punishments, mark_punishment_completed, get_expired_punishments


# Dictionary to store scheduled punishment removal tasks
scheduled_removals = {}

# =============================================================================
# BOT EVENT HANDLERS
# =============================================================================

async def on_ready(bot):
    """Event triggered when bot is ready."""
    # Check if bot is in the allowed guild
    allowed_guild = bot.get_guild(ALLOWED_GUILD_ID)
    if not allowed_guild:
        logging.error(f"❌ Bot is not in the allowed guild (ID: {ALLOWED_GUILD_ID})")
        print(f"❌ Bot is not in the allowed guild (ID: {ALLOWED_GUILD_ID})")
        print("   Please invite the bot to the correct server or update ALLOWED_GUILD_ID")
        await bot.close()
        return
    
    logging.info(f"✅ Bot restricted to guild: {allowed_guild.name} (ID: {ALLOWED_GUILD_ID})")
    print(f"✅ Bot restricted to guild: {allowed_guild.name} (ID: {ALLOWED_GUILD_ID})")
    
    try:
        # Force sync commands to the allowed guild
        # This copies all commands to the guild and syncs them
        guild = discord.Object(id=ALLOWED_GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        logging.info(f"✅ Bot logged in as {bot.user} and synced {len(synced)} slash commands to {allowed_guild.name}.")
        print(f"✅ Synced {len(synced)} slash commands to {allowed_guild.name}")
    except Exception as e:
        logging.error(f"Error syncing commands: {e}")
        print(f"❌ Error syncing commands: {e}")
    
    # Start periodic cleanup task
    bot.loop.create_task(cleanup_expired_punishments(bot))
    logging.info("Started periodic cleanup task for expired punishments (runs every 1 minute)")
    
    # Restore active punishments after restart
    await restore_active_punishments(bot)
    
    # Restore active temp bans after restart
    await restore_active_temp_bans(bot)

async def on_member_ban(guild, user):
    """Event triggered when a member is banned."""
    appeal_embed = discord.Embed(
        title="Ban Appeal Form",
        description="You have been banned from the server. If you believe this was a mistake or wish to appeal, please fill out the form below:",
        color=discord.Color.red()
    )
    appeal_embed.add_field(name="Appeal Form Link", value="https://dyno.gg/form/27f3392e", inline=False)
    
    try:
        await user.send(embed=appeal_embed)
    except discord.Forbidden:
        ban_appeal_channel = guild.get_channel(805554084273717248)
        if ban_appeal_channel:
            try:
                # Check if bot has permission to send messages in the ban appeal channel
                bot_permissions = ban_appeal_channel.permissions_for(guild.me)
                if bot_permissions.send_messages:
                    await ban_appeal_channel.send(f"{user.mention} was banned.")
                else:
                    logging.warning(f"Bot lacks permission to send messages in ban appeal channel {ban_appeal_channel.name} ({ban_appeal_channel.id})")
            except discord.Forbidden:
                logging.warning(f"Bot forbidden from sending to ban appeal channel {ban_appeal_channel.name} ({ban_appeal_channel.id})")
            except Exception as e:
                logging.error(f"Error sending to ban appeal channel {ban_appeal_channel.name} ({ban_appeal_channel.id}): {e}")
        else:
            logging.warning("Ban appeal channel (805554084273717248) not found in guild")
    except Exception as e:
        logging.error(f"Error sending ban appeal form to {user.id}: {e}")

async def on_message(bot, message):
    """Event triggered when a message is sent."""
    # Only process messages from the allowed guild
    if message.guild and message.guild.id != ALLOWED_GUILD_ID:
        return
    
    await bot.process_commands(message)
    
    if message.author.bot:
        return

# =============================================================================
# PUNISHMENT SYSTEM FUNCTIONS
# =============================================================================

async def cleanup_expired_punishments(bot):
    """Periodic task to clean up expired punishments that weren't removed by scheduled tasks."""
    
    while True:
        try:
            await asyncio.sleep(60)  # Run every 1 minute
            
            # Clean up expired Canada punishments
            expired_punishments = get_expired_punishments(guild_id=ALLOWED_GUILD_ID)
            
            if expired_punishments:
                logging.info(f"Found {len(expired_punishments)} expired punishments to clean up")
                
                for user_id, guild_id, release_time in expired_punishments:
                    try:
                        # Double-check that this punishment is for the allowed guild
                        if guild_id != ALLOWED_GUILD_ID:
                            # Use debug level to avoid spam in logs
                            logging.debug(f"Skipping punishment for guild {guild_id} - not the allowed guild ({ALLOWED_GUILD_ID})")
                            continue
                        
                        guild = bot.get_guild(guild_id)
                        if not guild:
                            logging.warning(f"Allowed guild {guild_id} not found during cleanup for user {user_id}")
                            continue
                        
                        # Try to get member from cache first, then fetch from API if needed
                        member = guild.get_member(user_id)
                        if not member:
                            try:
                                member = await guild.fetch_member(user_id)
                                logging.debug(f"Successfully fetched member {user_id} from API (not in cache) for cleanup")
                            except discord.NotFound:
                                logging.info(f"Member {user_id} left guild, marking punishment as completed")
                                mark_punishment_completed(user_id, guild_id, release_time)
                                continue
                            except Exception as e:
                                logging.error(f"Error fetching member {user_id} during cleanup: {e}")
                                continue
                        
                        canada_role_id = get_canada_role_id()
                        canada_role = guild.get_role(canada_role_id)
                        
                        if member and canada_role and canada_role in member.roles:
                            try:
                                await member.remove_roles(canada_role, reason="Punishment expired (cleanup)")
                                mark_punishment_completed(user_id, guild_id, release_time)
                                logging.info(f"Cleanup: Removed Canada role from {member} ({member.id})")
                                
                                # Send DM to user
                                try:
                                    dm_embed = discord.Embed(
                                        title="You have been released from Canada",
                                        description="Your punishment has expired and you have been released from Canada.",
                                        color=discord.Color.green()
                                    )
                                    await member.send(embed=dm_embed)
                                except discord.Forbidden:
                                    pass  # User has DMs disabled
                                    
                            except Exception as e:
                                logging.error(f"Error removing Canada role during cleanup for {member.id}: {e}")
                        elif member and canada_role:
                            # Role already removed, mark as completed
                            mark_punishment_completed(user_id, guild_id, release_time)
                            logging.info(f"Cleanup: Canada role already removed from {member} ({member.id})")
                        else:
                            # Member not found or role not found, still mark as completed
                            mark_punishment_completed(user_id, guild_id, release_time)
                            logging.info(f"Cleanup: Member or role not found for user {user_id}, marking as completed")
                        
                        # Cancel any remaining scheduled task
                        if scheduled_removals.get(user_id):
                            scheduled_removals[user_id].cancel()
                            del scheduled_removals[user_id]
                        
                    except Exception as e:
                        logging.error(f"Error during cleanup for user {user_id}: {e}")
            
            # Also clean up expired temp bans
            await cleanup_expired_temp_bans(bot)
                    
        except Exception as e:
            logging.error(f"Error in cleanup_expired_punishments task: {e}")

async def restore_active_punishments(bot):
    """Restore active punishments after bot restart."""
    rows = get_active_punishments()
    
    now_ts = int(datetime.now(timezone.utc).timestamp())
    for user_id, guild_id, release_time, punishment_start in rows:
        if release_time and release_time > now_ts:
            guild = bot.get_guild(guild_id)
            if guild:
                # Try to get member from cache first, then fetch from API if needed
                member = guild.get_member(user_id)
                if not member:
                    try:
                        member = await guild.fetch_member(user_id)
                        logging.debug(f"Successfully fetched member {user_id} from API (not in cache) for bot restart")
                    except discord.NotFound:
                        logging.info(f"Member {user_id} left guild, skipping punishment restoration")
                        continue
                    except Exception as e:
                        logging.error(f"Error fetching member {user_id} for restoration: {e}")
                        continue
                        
                canada_role_id = get_canada_role_id()
                canada_role = guild.get_role(canada_role_id)
                if member and canada_role:
                    if canada_role not in member.roles:
                        await member.add_roles(canada_role, reason="Restoring Canada punishment after bot restart")
                    
                    # Cancel any existing scheduled task
                    if scheduled_removals.get(user_id):
                        scheduled_removals[user_id].cancel()
                        del scheduled_removals[user_id]
                    
                    # Schedule new removal task
                    await schedule_role_removal(bot, guild_id, user_id, release_time)

async def schedule_role_removal(bot, guild_id: int, user_id: int, release_time: int):
    """Schedule role removal for a specific time."""
    async def remove_role_later():
        try:
            now_ts = int(datetime.now(timezone.utc).timestamp())
            delay = max(0, release_time - now_ts)
            
            if delay > 0:
                logging.info(f"Scheduled Canada role removal for user {user_id} in {delay} seconds")
                await asyncio.sleep(delay)
            
            guild = bot.get_guild(guild_id)
            if not guild:
                logging.warning(f"Guild {guild_id} not found for scheduled removal of user {user_id}")
                return
            
            member = guild.get_member(user_id)
            if not member:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    logging.info(f"Member {user_id} left guild, cannot remove Canada role")
                    mark_punishment_completed(user_id, guild_id, release_time)
                    return
                except Exception as e:
                    logging.error(f"Error fetching member {user_id} for scheduled removal: {e}")
                    return
            
            canada_role_id = get_canada_role_id()
            canada_role = guild.get_role(canada_role_id)
            if canada_role and canada_role in member.roles:
                await member.remove_roles(canada_role, reason="Punishment expired")
                logging.info(f"Scheduled removal: Removed Canada role from {member} ({member.id})")
                
                # Send DM to user
                try:
                    dm_embed = discord.Embed(
                        title="You have been released from Canada",
                        description="Your punishment has expired and you have been released from Canada.",
                        color=discord.Color.green()
                    )
                    await member.send(embed=dm_embed)
                except discord.Forbidden:
                    pass  # User has DMs disabled
            
            # Mark as completed
            mark_punishment_completed(user_id, guild_id, release_time)
            
            # Remove from scheduled tasks
            if scheduled_removals.get(user_id):
                del scheduled_removals[user_id]
                
        except Exception as e:
            logging.error(f"Error in scheduled role removal for user {user_id}: {e}")
    
    task = bot.loop.create_task(remove_role_later())
    scheduled_removals[user_id] = task

async def cancel_scheduled_removal(user_id: int):
    """Cancel a scheduled role removal."""
    if scheduled_removals.get(user_id):
        scheduled_removals[user_id].cancel()
        del scheduled_removals[user_id]
        logging.info(f"Cancelled scheduled removal task for user {user_id}")

# =============================================================================
# TEMP BAN SCHEDULING
# =============================================================================

# Dictionary to store scheduled temp unban tasks
scheduled_unbans = {}

# Ban log channel ID
BAN_LOG_CHANNEL_ID = 689927423382519866

async def schedule_temp_unban(bot, guild_id: int, user_id: int, unban_time: int, log_number: int):
    """Schedule automatic unban for a specific time."""
    from data_manager import mark_temp_ban_completed
    
    async def unban_later():
        try:
            now_ts = int(datetime.now(timezone.utc).timestamp())
            delay = max(0, unban_time - now_ts)
            
            if delay > 0:
                logging.info(f"Scheduled temp unban for user {user_id} in {delay} seconds")
                await asyncio.sleep(delay)
            
            guild = bot.get_guild(guild_id)
            if not guild:
                logging.warning(f"Guild {guild_id} not found for scheduled unban of user {user_id}")
                return
            
            # Try to unban the user
            try:
                user = await bot.fetch_user(user_id)
                await guild.unban(user, reason=f"Temp ban expired (Log #{log_number})")
                logging.info(f"Scheduled unban: Unbanned {user} ({user_id})")
                
                # Mark as completed
                mark_temp_ban_completed(user_id, guild_id, unban_time)
                
                # Send to ban log channel
                ban_log_channel = guild.get_channel(BAN_LOG_CHANNEL_ID)
                if ban_log_channel:
                    embed = discord.Embed(
                        title="⏰ Temp Ban Expired - User Unbanned",
                        color=discord.Color.green(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=True)
                    embed.add_field(name="Log #", value=str(log_number), inline=True)
                    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
                    
                    try:
                        await ban_log_channel.send(embed=embed)
                    except Exception as e:
                        logging.error(f"Error sending unban log: {e}")
                
                # Try to DM the user
                try:
                    dm_embed = discord.Embed(
                        title="Your Temp Ban Has Expired",
                        description="Your temporary ban has expired and you can now rejoin the server.",
                        color=discord.Color.green()
                    )
                    dm_embed.add_field(
                        name="Rejoin Link",
                        value="https://discord.gg/virtualcongress",  # Update with actual invite
                        inline=False
                    )
                    await user.send(embed=dm_embed)
                except discord.Forbidden:
                    pass  # User has DMs disabled
                    
            except discord.NotFound:
                logging.info(f"User {user_id} not found for scheduled unban - may already be unbanned")
                mark_temp_ban_completed(user_id, guild_id, unban_time)
            except discord.Forbidden:
                logging.error(f"Bot lacks permission to unban user {user_id}")
            except Exception as e:
                logging.error(f"Error unbanning user {user_id}: {e}")
            
            # Remove from scheduled tasks
            if scheduled_unbans.get(user_id):
                del scheduled_unbans[user_id]
                
        except Exception as e:
            logging.error(f"Error in scheduled unban for user {user_id}: {e}")
    
    # Cancel any existing task for this user
    if scheduled_unbans.get(user_id):
        scheduled_unbans[user_id].cancel()
    
    task = bot.loop.create_task(unban_later())
    scheduled_unbans[user_id] = task

async def restore_active_temp_bans(bot):
    """Restore temp ban schedules after bot restart."""
    from data_manager import get_active_temp_bans
    
    active_bans = get_active_temp_bans(ALLOWED_GUILD_ID)
    if not active_bans:
        logging.info("No active temp bans to restore")
        return
    
    logging.info(f"Restoring {len(active_bans)} active temp ban schedules...")
    
    for ban in active_bans:
        user_id = ban.get("user_id")
        unban_time = ban.get("unban_time")
        log_number = ban.get("log_number")
        
        if unban_time:
            await schedule_temp_unban(bot, ALLOWED_GUILD_ID, user_id, unban_time, log_number)
    
    logging.info("Temp ban schedules restored")

async def cleanup_expired_temp_bans(bot):
    """Check for and process any expired temp bans."""
    from data_manager import get_expired_temp_bans, mark_temp_ban_completed
    
    expired = get_expired_temp_bans(ALLOWED_GUILD_ID)
    
    if not expired:
        return
    
    guild = bot.get_guild(ALLOWED_GUILD_ID)
    if not guild:
        return
    
    for ban in expired:
        user_id = ban.get("user_id")
        unban_time = ban.get("unban_time")
        log_number = ban.get("log_number")
        
        try:
            user = await bot.fetch_user(user_id)
            await guild.unban(user, reason=f"Temp ban expired (Log #{log_number})")
            logging.info(f"Cleanup: Unbanned {user} ({user_id})")
            mark_temp_ban_completed(user_id, guild.id, unban_time)
            
            # Send to ban log channel
            ban_log_channel = guild.get_channel(BAN_LOG_CHANNEL_ID)
            if ban_log_channel:
                embed = discord.Embed(
                    title="⏰ Temp Ban Expired - User Unbanned (Cleanup)",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=True)
                embed.add_field(name="Log #", value=str(log_number), inline=True)
                
                try:
                    await ban_log_channel.send(embed=embed)
                except Exception as e:
                    logging.error(f"Error sending cleanup unban log: {e}")
                    
        except discord.NotFound:
            mark_temp_ban_completed(user_id, guild.id, unban_time)
        except Exception as e:
            logging.error(f"Error in cleanup unban for {user_id}: {e}")

def get_scheduled_unbans():
    """Get the scheduled unbans dictionary."""
    return scheduled_unbans

async def cancel_temp_unban(user_id: int) -> bool:
    """Cancel a scheduled temp unban task."""
    if scheduled_unbans.get(user_id):
        scheduled_unbans[user_id].cancel()
        del scheduled_unbans[user_id]
        logging.info(f"Cancelled scheduled unban task for user {user_id}")
        return True
    return False

# =============================================================================
# CLEANUP FUNCTIONS
# =============================================================================

async def cleanup_scheduled_tasks():
    """Cleanup all scheduled tasks on shutdown."""
    try:
        if scheduled_removals:
            logging.info(f"Cleaning up {len(scheduled_removals)} scheduled role removal tasks...")
            # Cancel all scheduled tasks
            for user_id, task in list(scheduled_removals.items()):
                try:
                    if not task.done():
                        task.cancel()
                    del scheduled_removals[user_id]
                except Exception as cleanup_error:
                    logging.error(f"Error canceling task for user {user_id}: {cleanup_error}")
            logging.info("Scheduled role removal tasks cleanup completed.")
        
        if scheduled_unbans:
            logging.info(f"Cleaning up {len(scheduled_unbans)} scheduled unban tasks...")
            for user_id, task in list(scheduled_unbans.items()):
                try:
                    if not task.done():
                        task.cancel()
                    del scheduled_unbans[user_id]
                except Exception as cleanup_error:
                    logging.error(f"Error canceling unban task for user {user_id}: {cleanup_error}")
            logging.info("Scheduled unban tasks cleanup completed.")
    except Exception as cleanup_error:
        logging.error(f"Error during cleanup: {cleanup_error}")

def get_scheduled_removals():
    """Get the scheduled removals dictionary for access from other modules."""
    return scheduled_removals
