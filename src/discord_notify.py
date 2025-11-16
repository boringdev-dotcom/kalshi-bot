"""Discord webhook notifier for Kalshi order events."""
import logging
import requests

logger = logging.getLogger(__name__)


def post_order_created(webhook_url: str, order: dict) -> None:
    """
    Send a Discord notification when a new Kalshi order event occurs.
    
    Args:
        webhook_url: Discord webhook URL
        order: Order data dictionary from Kalshi WebSocket (could be fill, order creation, etc.)
    """
    try:
        # Handle different event types - fill events might have different field names
        ticker = order.get('market_ticker') or order.get('ticker', 'N/A')
        side = order.get('side', 'N/A')
        # Fill events use "count", order events might use "size"
        size = order.get('count') or order.get('size', 'N/A')
        # Fill events use "yes_price", order events might use "price"
        price = order.get('yes_price') or order.get('price', 'N/A')
        order_id = order.get('order_id', 'N/A')
        
        content = (
            f"**Kalshi Order Event**\n"
            f"Ticker: `{ticker}`\n"
            f"Side: `{side}`  Size: `{size}`  Price: `{price}`\n"
            f"Order ID: `{order_id}`"
        )
        
        response = requests.post(
            webhook_url,
            json={"content": content},
            timeout=10
        )
        response.raise_for_status()
        logger.info(f"Discord notification sent for order {order.get('order_id')}")
    except requests.RequestException as e:
        logger.error(f"Failed to send Discord notification: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending Discord notification: {e}")

