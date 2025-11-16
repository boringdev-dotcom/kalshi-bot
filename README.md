# Kalshi Discord Bot

A Discord bot that monitors your Kalshi orders via WebSocket and sends notifications to Discord when you place a new order.

## Features

- Real-time order monitoring via Kalshi WebSocket API
- Discord webhook notifications for new orders
- Automatic reconnection with exponential backoff
- Filters to only notify on order creation (not fills/cancellations)
- Uses `uv` for fast dependency management

## Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) installed
- Kalshi API credentials (demo or production)
- Discord webhook URL

## Setup

### 1. Get Kalshi API Credentials

1. Visit the [Kalshi API Portal](https://trading-api.kalshi.com/trade-api-portal/)
2. Generate an API key pair - you'll receive:
   - **Key ID**: A UUID (e.g., `1ae3670a-c64b-46b4-8741-315d8cee5a5d`)
   - **Private Key**: An RSA private key in PEM format
3. **Important**: Save the private key immediately - it cannot be retrieved again once you close the page

### 2. Create a Discord Webhook

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

# Discord webhook URL
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your_webhook_id/your_webhook_token

# Kalshi WebSocket URL (defaults to demo environment)
KALSHI_WS_URL=wss://demo-api.kalshi.co/trade-api/ws/v2
```

**Note:** 
- For production, change `KALSHI_WS_URL` to `wss://api.elections.kalshi.com/trade-api/ws/v2`
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

### Using uv (recommended)

```bash
uv run -m src.main
```

Or if you activated the venv:

```bash
python -m src.main
```


## How It Works

1. The bot connects to Kalshi's WebSocket API using authenticated headers
2. Subscribes to the `orders` channel for your account
3. Filters events to only process order creation events
4. Sends formatted notifications to your Discord channel via webhook
5. Automatically reconnects if the connection is lost

## Notification Format

When you place an order, you'll receive a Discord message like:

```
**New Kalshi Order Created**
Ticker: `INFLATION-2024-12`
Side: `yes`  Size: `10`  Price: `0.55`
Order ID: `abc123xyz`
```

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
│   ├── __init__.py
│   ├── main.py              # Entry point
│   ├── kalshi_ws_client.py  # WebSocket client
│   └── discord_notify.py    # Discord webhook sender
├── pyproject.toml           # Project metadata and dependencies
├── .env                     # Your environment variables (not in git)
└── README.md
```

## License

MIT
