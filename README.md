# Canadian Helper Discord Bot

A Discord moderation bot with advanced warning and punishment systems.

## Features

- Warning system for users
- Automatic punishments based on warning count
- Temporary bans
- Role-based permissions
- Swear word filtering
- Logging system

## Setup

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in your credentials:
   ```bash
   cp .env.example .env
   ```
4. Update the `.env` file with:
   - Your Discord bot token
   - Database credentials (host, name, user, password)

5. Run the bot:
   ```bash
   python main.py
   ```

## Configuration

The bot uses JSON files in the `data/` directory for configuration:
- `config.json` - General bot configuration
- `allowed_roles.json` - Roles with moderation permissions
- `punishment_config.json` - Punishment rules
- `warnings.json` - User warnings data
- `temp_bans.json` - Temporary ban data

## Requirements

See `requirements.txt` for Python dependencies.

## License

This project is for personal use.
