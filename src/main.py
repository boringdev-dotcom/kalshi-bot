"""Main entry point for Kalshi Discord bot."""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
import uvicorn

from .api import app
from .discord_notify import post_order_created
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
    # Load environment variables
    load_dotenv()
    
    # Get configuration from environment
    ws_url = os.getenv(
        "KALSHI_WS_URL",
        "wss://demo-api.kalshi.co/trade-api/ws/v2"
    )
    key_id = os.getenv("KALSHI_API_KEY_ID")
    private_key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    
    # Validate required environment variables
    missing_vars = []
    if not key_id:
        missing_vars.append("KALSHI_API_KEY_ID")
    if not private_key_pem:
        missing_vars.append("KALSHI_PRIVATE_KEY_PEM")
    if not webhook_url:
        missing_vars.append("DISCORD_WEBHOOK_URL")
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please copy .env.example to .env and fill in the values")
        sys.exit(1)
    
    # Handle newlines in private key (replace \n with actual newlines)
    if private_key_pem:
        private_key_pem = private_key_pem.replace("\\n", "\n")
    
    logger.info("Starting Kalshi Discord bot...")
    logger.info(f"WebSocket URL: {ws_url}")
    logger.info(f"Discord webhook configured: {webhook_url[:50]}...")
    
    # Get API server configuration
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", "8000"))
    
    # Callback for when an order is created
    async def on_order_created(order: dict) -> None:
        """Handle order created event."""
        post_order_created(webhook_url, order)
    
    # Start API server and WebSocket client concurrently
    async def run_api_server():
        """Run the FastAPI server."""
        config = uvicorn.Config(
            app,
            host=api_host,
            port=api_port,
            log_level="info",
            access_log=False,
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    async def run_websocket_client():
        """Run the WebSocket client."""
        await stream_orders(ws_url, key_id, private_key_pem, on_order_created)
    
    # Run both tasks concurrently
    try:
        logger.info(f"Starting API server on http://{api_host}:{api_port}")
        logger.info(f"Health check available at http://{api_host}:{api_port}/health")
        await asyncio.gather(
            run_api_server(),
            run_websocket_client(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

