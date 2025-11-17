# Kalshi Discord Bot

A production-ready Discord bot that monitors your Kalshi orders via WebSocket and sends rich notifications to Discord when orders are filled. Supports both Discord bot (with real-time odds updates) and webhook modes.

## Features

- **Real-time order monitoring** via Kalshi WebSocket API
- **Discord bot notifications** with live odds updates (or webhook fallback)
- **Automatic reconnection** with exponential backoff
- **Partial fill aggregation** - combines multiple fills into a single notification
- **Rich embed formatting** with market details, side descriptions, and links
- **Production-ready architecture** with centralized configuration and type safety
- **Flexible deployment** - run API server and worker together or separately
- Uses `uv` for fast dependency management

## Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) installed
- Kalshi API credentials (demo or production)
- Discord bot token and channel ID (recommended for live odds) OR Discord webhook URL

## Setup

### 1. Get Kalshi API Credentials

1. Visit the [Kalshi API Portal](https://trading-api.kalshi.com/trade-api-portal/)
2. Generate an API key pair - you'll receive:
   - **Key ID**: A UUID (e.g., `1ae3670a-c64b-46b4-8741-315d8cee5a5d`)
   - **Private Key**: An RSA private key in PEM format
3. **Important**: Save the private key immediately - it cannot be retrieved again once you close the page

### 2. Set Up Discord (Bot Recommended)

**Option A: Discord Bot (Recommended - enables live odds updates)**

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** and give it a name
3. Go to **Bot** section and click **Add Bot**
4. Under **Token**, click **Reset Token** and copy the token
5. Under **Privileged Gateway Intents**, enable **MESSAGE CONTENT INTENT** (required for reading messages)
6. Go to **OAuth2** > **URL Generator**
7. Select **bot** scope and **Send Messages** permission
8. Copy the generated URL and open it to invite the bot to your server
9. Right-click your Discord channel and select **Copy Channel ID** (enable Developer Mode in Discord settings first)

**Option B: Discord Webhook (Simple, but no live odds updates)**

1. Open your Discord server
2. Go to **Server Settings** > **Integrations** > **Webhooks**
3. Click **Create Webhook**
4. Configure the webhook (name, channel, avatar)
5. Copy the **Webhook URL**

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Kalshi API credentials
# Key ID is a UUID like: 1ae3670a-c64b-46b4-8741-315d8cee5a5d
KALSHI_API_KEY_ID=your_api_key_id_here

# Private Key in PEM format (RSA private key)
# Can be provided as a single line with \n for newlines
KALSHI_PRIVATE_KEY_PEM=-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY_HERE\n-----END PRIVATE KEY-----

# Discord Bot (recommended for live odds updates)
DISCORD_BOT_TOKEN=your_discord_bot_token_here
DISCORD_CHANNEL_ID=your_channel_id_here

# OR Discord Webhook (fallback, no live odds)
# DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your_webhook_id/your_webhook_token

# Kalshi WebSocket URL (defaults to demo environment)
KALSHI_WS_URL=wss://demo-api.kalshi.co/trade-api/ws/v2
```

**Note:** 
- For production, change `KALSHI_WS_URL` to `wss://api.elections.kalshi.com/trade-api/ws/v2`
- **Discord Bot** is recommended as it supports real-time odds updates via WebSocket
- If both bot and webhook are configured, the bot will be used
- When adding your private key to `.env`, you can either:
  - Use `\n` for newlines in a single line: `KALSHI_PRIVATE_KEY_PEM=-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----`
  - Or use actual newlines if your `.env` file supports multi-line values

### 4. Install Dependencies

Using `uv`:

```bash
# Create virtual environment and install dependencies
uv venv
uv sync

# Or activate the venv and use it directly
source .venv/bin/activate
```

## Running

### Option 1: CLI 

After installing dependencies, use the CLI:

```bash
# Run both API server and WebSocket worker (default)
uv run kalshi-bot run-all

# Or run components separately (for production deployments)
uv run kalshi-bot run-api    # API server only (health check)
uv run kalshi-bot run-worker # WebSocket worker only
```

### Option 2: Python Module (Recommended)

```bash
# Run the main entry point (API + Worker)
uv run -m src.main

# Or if you activated the venv
python -m src.main
```

### Option 3: Direct API Server

For production, you can run the API server with uvicorn:

```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Then run the worker separately:

```bash
uv run kalshi-bot run-worker
```


## How It Works

1. The bot connects to Kalshi's WebSocket API using authenticated headers
2. Subscribes to the `fill` channel for order fill events
3. Subscribes to the `market` channel for real-time price updates (if using Discord Bot)
4. When an order is filled, sends a formatted notification to Discord
5. If using Discord Bot: Updates odds in real-time via WebSocket when prices change
6. Automatically reconnects if the connection is lost

## Notification Format

When an order is filled, you'll receive a rich Discord embed with:

- **Market name** (fetched from Kalshi API)
- **Side description** (e.g., "YES - Team Wins" or "NO - Team Wins")
- **Action** (Buy/Sell)
- **Odds percentage** (updates in real-time if using Discord bot)
- **Contract count** and **total amount**
- **Timestamp** and **market link**

If using Discord bot mode, the odds will update automatically as market prices change via WebSocket.

## Troubleshooting

### Connection Issues

- Ensure your system clock is synchronized (required for API authentication)
- Check that your API credentials are correct
- Verify the WebSocket URL matches your environment (demo vs production)

### No Notifications

- Verify your Discord webhook URL is correct
- Check that you're placing orders in the correct Kalshi environment (demo vs production)
- Review logs for any error messages

### Authentication Errors

- Double-check your API key ID and private key format
- Ensure your private key includes the `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----` markers
- If using `\n` in `.env`, make sure they're actual backslash-n characters, not literal newlines
- Ensure timestamps are accurate (sync your system clock)
- Verify you're using the correct WebSocket URL for your environment
- Check that your private key matches the key ID (they're paired together)

## Development

The project structure:

```
kalshi-bot/
├── src/
│   ├── __init__.py          # Package initialization
│   ├── main.py              # Main entry point (API + Worker)
│   ├── cli.py               # CLI interface (run-all, run-api, run-worker)
│   ├── api.py               # FastAPI application (health check)
│   ├── config.py            # Centralized configuration (Settings)
│   ├── kalshi_auth.py       # Shared Kalshi authentication utilities
│   ├── kalshi_api.py        # Kalshi REST API client
│   ├── kalshi_ws_client.py  # WebSocket client (order streaming)
│   ├── discord_bot.py       # Discord bot client (real-time updates)
│   └── discord_notify.py    # Discord webhook/embed formatting
├── generate_curl.py          # Helper script for API testing
├── pyproject.toml           # Project metadata and dependencies
├── .env                     # Your environment variables (not in git)
└── README.md
```

### Architecture

- **Configuration**: Centralized in `config.py` using Pydantic Settings
- **Authentication**: Shared RSA signing logic in `kalshi_auth.py`
- **WebSocket**: Handles order fills, partial fill aggregation, and reconnection
- **Discord**: Supports both bot (with message editing) and webhook modes
- **Type Safety**: Full type hints throughout for better IDE support and maintainability

## License

MIT
