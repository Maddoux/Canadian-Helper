"""
Canadian Helper Discord Bot - Main Entry Point

A Discord bot for managing user punishments.
Now using JSON file storage instead of database.
"""

import sys
import logging
import discord
from discord.ext import commands

# Import our modules
from bot_config import setup_logging, DISCORD_BOT_TOKEN, ALLOWED_GUILD_ID
from data_manager import init_data_storage
from commands import ALL_COMMANDS
from admin_commands import ALL_ADMIN_COMMANDS
from events import on_ready as events_on_ready, on_member_ban, on_message as events_on_message, cleanup_scheduled_tasks

# =============================================================================
# BOT SETUP
# =============================================================================

# Set up logging
setup_logging()

# Create bot instance
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='can!', intents=intents)

# =============================================================================
# GLOBAL GUILD CHECK
# =============================================================================

@bot.check
async def guild_check(interaction: discord.Interaction):
    """Global check to ensure bot only works in the allowed guild."""
    if hasattr(interaction, 'guild_id') and interaction.guild_id != ALLOWED_GUILD_ID:
        await interaction.response.send_message(
            "❌ This bot only works in the authorized server.", 
            ephemeral=True
        )
        return False
    return True

# =============================================================================
# EVENT HANDLERS
# =============================================================================

@bot.event
async def on_ready():
    """Bot ready event."""
    await events_on_ready(bot)
    # Note: Command syncing is now handled in events_on_ready

@bot.event
async def on_member_ban(guild, user):
    """Member ban event."""
    await on_member_ban(guild, user)

@bot.event
async def on_message(message):
    """Message event."""
    await events_on_message(bot, message)

# =============================================================================
# COMMAND REGISTRATION
# =============================================================================

def register_commands():
    """Register all slash commands."""
    all_commands = ALL_COMMANDS + ALL_ADMIN_COMMANDS
    
    for command_func in all_commands:
        try:
            # Remove command if it already exists (for hot reloading)
            existing_command = bot.tree.get_command(command_func.name)
            if existing_command:
                bot.tree.remove_command(command_func.name)
            
            bot.tree.add_command(command_func)
            logging.info(f"Registered command: {command_func.name}")
        except Exception as e:
            logging.error(f"Error registering command {command_func.name}: {e}")

# =============================================================================
# UTILITY COMMANDS (for development)
# =============================================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def reload_slash(ctx):
    """Reload slash commands."""
    try:
        await bot.tree.sync()
        await ctx.send("✅ Slash commands have been reloaded.")
    except Exception as e:
        await ctx.send(f"❌ Error reloading commands: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def sync_commands(ctx):
    """Sync slash commands globally."""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Synced {len(synced)} commands globally.")
    except Exception as e:
        await ctx.send(f"❌ Error syncing commands: {e}")

# =============================================================================
# MAIN FUNCTION
# =============================================================================

def main():
    """Main function to start the bot with proper error handling."""
    if not DISCORD_BOT_TOKEN:
        logging.error("DISCORD_BOT_TOKEN not found in environment variables!")
        print("❌ Error: DISCORD_BOT_TOKEN not found in environment variables!")
        print("Please check your .env file and make sure it contains:")
        print("DISCORD_BOT_TOKEN=your_bot_token_here")
        sys.exit(1)
    
    # Initialize data storage
    try:
        init_data_storage()
        
        # Clean up punishment data for other guilds (one-time cleanup)
        from data_manager import cleanup_other_guild_data
        cleanup_other_guild_data()
        
        logging.info("✅ Data storage initialized successfully.")
    except Exception as e:
        logging.error(f"❌ Failed to initialize data storage: {e}")
        print(f"❌ Failed to initialize data storage: {e}")
        sys.exit(1)
    
    # Register commands
    try:
        register_commands()
        logging.info("✅ Commands registered successfully.")
    except Exception as e:
        logging.error(f"❌ Failed to register commands: {e}")
        print(f"❌ Failed to register commands: {e}")
        sys.exit(1)
    
    # Start bot with proper cleanup
    try:
        logging.info("🚀 Starting Canadian Helper Bot...")
        print("🚀 Starting Canadian Helper Bot...")
        print("📁 Using JSON file storage (no database required)")
        
        bot.run(DISCORD_BOT_TOKEN)
        
    except discord.LoginFailure:
        logging.error("❌ Invalid Discord bot token!")
        print("❌ Invalid Discord bot token!")
        print("Please check your .env file and make sure the token is correct.")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("🛑 Bot shutdown requested by user.")
        print("🛑 Bot shutdown requested by user.")
    except Exception as e:
        logging.error(f"❌ Bot failed to start: {e}")
        print(f"❌ Bot failed to start: {e}")
        sys.exit(1)
    finally:
        # Cleanup scheduled tasks on shutdown
        try:
            import asyncio
            asyncio.run(cleanup_scheduled_tasks())
        except Exception as cleanup_error:
            logging.error(f"Error during cleanup: {cleanup_error}")
        
        logging.info("🏁 Bot shutdown complete.")
        print("🏁 Bot shutdown complete.")

if __name__ == "__main__":
    main()
