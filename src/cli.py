"""Command-line interface for Kalshi Discord bot."""
import asyncio
import logging
import sys

import typer
import uvicorn

from .api import app
from .config import Settings
from .discord_notify import post_order_created
from .discord_bot import initialize_bot, send_order_notification, handle_price_update
from .telegram_notify import send_telegram_notification
from .kalshi_ws_client import stream_orders

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

cli = typer.Typer(help="Kalshi Discord Bot - Real-time order monitoring and notifications")


async def _run_worker(settings: Settings) -> None:
    """Run the WebSocket worker (order streaming and Discord notifications)."""
    use_bot = settings.use_discord_bot
    
    # Initialize Discord bot if configured
    if use_bot:
        try:
            channel_id = settings.discord_channel_id_int
            if channel_id is None:
                raise ValueError(f"Invalid DISCORD_CHANNEL_ID: {settings.discord_channel_id}")
            
            logger.info(f"Initializing Discord bot for channel ID: {channel_id}")
            await initialize_bot(channel_id, settings.discord_bot_token)
            logger.info("Discord bot initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Discord bot: {e}", exc_info=True)
            logger.error("Falling back to webhook if configured...")
            use_bot = False
    else:
        logger.info("Using Discord webhook mode (bot credentials not provided)")
    
    # Callback for when an order is created
    async def on_order_created(order: dict, ws_url_param: str = None) -> None:
        """Handle order created event."""
        from .discord_bot import _bot_instance
        bot_available = _bot_instance is not None and _bot_instance.channel is not None
        
        ws_url_to_use = ws_url_param or settings.kalshi_ws_url
        
        # Send Discord notification
        if bot_available:
            logger.debug("Using Discord bot to send notification")
            await send_order_notification(order, ws_url_to_use)
        elif use_bot:
            logger.warning("Bot was configured but not available, trying to send anyway...")
            result = await send_order_notification(order, ws_url_to_use)
            if not result and settings.discord_webhook_url:
                logger.warning("Bot send failed, falling back to webhook")
                post_order_created(settings.discord_webhook_url, order, ws_url_to_use)
        elif settings.discord_webhook_url:
            logger.debug("Using Discord webhook to send notification")
            post_order_created(settings.discord_webhook_url, order, ws_url_to_use)
        
        # Send Telegram notification
        if settings.use_telegram:
            logger.debug("Sending Telegram notification")
            await send_telegram_notification(
                settings.telegram_bot_token,
                settings.telegram_chat_id,
                order,
                ws_url_to_use
            )
    
    # Wait a moment for bot to be fully ready
    if use_bot:
        await asyncio.sleep(1)
    
    # Pass price update callback if bot was initialized
    from .discord_bot import _bot_instance
    bot_available = use_bot and _bot_instance is not None and _bot_instance.channel is not None
    price_update_callback = handle_price_update if bot_available else None
    
    if price_update_callback:
        logger.info("Price update callback enabled - odds will update in real-time")
    else:
        if use_bot:
            logger.warning("Price update callback NOT enabled - bot may not be ready")
        else:
            logger.debug("Price update callback disabled - using webhook mode")
    
    await stream_orders(
        settings.kalshi_ws_url,
        settings.kalshi_api_key_id,
        settings.kalshi_private_key_pem,
        on_order_created,
        price_update_callback
    )


async def _run_api(settings: Settings) -> None:
    """Run the FastAPI server."""
    port = settings.get_port()  # Uses PORT env var for Render.com
    config = uvicorn.Config(
        app,
        host=settings.api_host,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


@cli.command()
def run_all():
    """Run both API server and WebSocket worker in the same process."""
    settings = Settings()
    
    missing_vars = settings.validate_required()
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please ensure your .env file contains the required values")
        sys.exit(1)
    
    port = settings.get_port()
    logger.info("Starting Kalshi trading bot (API + Worker)...")
    logger.info(f"WebSocket URL: {settings.kalshi_ws_url}")
    logger.info(f"API server: http://{settings.api_host}:{port}")
    if settings.use_telegram:
        logger.info("Telegram notifications enabled")
    
    async def main():
        try:
            await asyncio.gather(
                _run_api(settings),
                _run_worker(settings),
            )
        except KeyboardInterrupt:
            logger.info("Shutting down gracefully...")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)
    
    asyncio.run(main())


@cli.command()
def run_api():
    """Run only the API server (health check endpoint)."""
    settings = Settings()
    
    # API server doesn't need Discord credentials, but validate Kalshi credentials
    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_pem:
        logger.error("Missing KALSHI_API_KEY_ID or KALSHI_PRIVATE_KEY_PEM")
        sys.exit(1)
    
    port = settings.get_port()
    logger.info(f"Starting API server on http://{settings.api_host}:{port}")
    logger.info(f"Health check: http://{settings.api_host}:{port}/health")
    
    async def main():
        try:
            await _run_api(settings)
        except KeyboardInterrupt:
            logger.info("Shutting down gracefully...")
    
    asyncio.run(main())


@cli.command()
def run_worker():
    """Run only the WebSocket worker (order streaming and notifications)."""
    settings = Settings()
    
    missing_vars = settings.validate_required()
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please ensure your .env file contains the required values")
        sys.exit(1)
    
    logger.info("Starting WebSocket worker...")
    logger.info(f"WebSocket URL: {settings.kalshi_ws_url}")
    
    async def main():
        try:
            await _run_worker(settings)
        except KeyboardInterrupt:
            logger.info("Shutting down gracefully...")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)
    
    asyncio.run(main())


if __name__ == "__main__":
    cli()

