"""Main entry point for Kalshi Discord bot."""
import asyncio
import logging
import sys

import uvicorn

from .api import app
from .config import Settings
from .discord_notify import post_order_created
from .discord_bot import initialize_bot, send_order_notification, handle_price_update
from .kalshi_ws_client import stream_orders

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


async def main():
    """Main async entry point."""
    # Load configuration from environment
    settings = Settings()
    
    # Validate required settings
    missing_vars = settings.validate_required()
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please ensure your .env file contains the required values")
        sys.exit(1)
    
    logger.info("Starting Kalshi Discord bot...")
    logger.info(f"WebSocket URL: {settings.kalshi_ws_url}")
    
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
        # Check if bot is actually available (more reliable than use_bot flag)
        from .discord_bot import _bot_instance
        bot_available = _bot_instance is not None and _bot_instance.channel is not None
        
        ws_url_to_use = ws_url_param or settings.kalshi_ws_url
        
        if bot_available:
            # Use Discord bot (supports message editing for live odds)
            logger.debug("Using Discord bot to send notification")
            await send_order_notification(order, ws_url_to_use)
        elif use_bot:
            # Bot was supposed to be initialized but isn't available
            logger.warning("Bot was configured but not available, trying to send anyway...")
            result = await send_order_notification(order, ws_url_to_use)
            if not result and settings.discord_webhook_url:
                logger.warning("Bot send failed, falling back to webhook")
                post_order_created(settings.discord_webhook_url, order, ws_url_to_use)
        else:
            # Fallback to webhook
            logger.debug("Using Discord webhook to send notification")
            if settings.discord_webhook_url:
                post_order_created(settings.discord_webhook_url, order, ws_url_to_use)
            else:
                logger.error("No Discord notification method available")
    
    # Start API server and WebSocket client concurrently
    port = settings.get_port()  # Uses PORT env var for Render.com
    
    async def run_api_server():
        """Run the FastAPI server."""
        config = uvicorn.Config(
            app,
            host=settings.api_host,
            port=port,
            log_level="info",
            access_log=False,
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    async def run_websocket_client():
        """Run the WebSocket client."""
        # Wait a moment for bot to be fully ready (channel set in on_ready)
        if use_bot:
            await asyncio.sleep(1)
        
        # Pass price update callback if bot was initialized (for real-time odds updates)
        # We check both use_bot flag and actual bot instance availability
        from .discord_bot import _bot_instance
        bot_available = use_bot and _bot_instance is not None and _bot_instance.channel is not None
        price_update_callback = handle_price_update if bot_available else None
        
        if price_update_callback:
            logger.info("Price update callback enabled - odds will update in real-time")
        else:
            if use_bot:
                logger.warning("Price update callback NOT enabled - bot may not be ready")
                if _bot_instance:
                    logger.debug(f"Bot instance exists but channel is {'set' if _bot_instance.channel else 'NOT set'}")
            else:
                logger.debug("Price update callback disabled - using webhook mode")
        
        await stream_orders(
            settings.kalshi_ws_url,
            settings.kalshi_api_key_id,
            settings.kalshi_private_key_pem,
            on_order_created,
            price_update_callback
        )
    
    # Run both tasks concurrently
    try:
        logger.info(f"Starting API server on http://{settings.api_host}:{port}")
        logger.info(f"Health check available at http://{settings.api_host}:{port}/health")
        await asyncio.gather(
            run_api_server(),
            run_websocket_client(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

