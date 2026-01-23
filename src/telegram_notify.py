"""Telegram notifier for Kalshi order events."""
import logging
from typing import Optional, Dict, Any

import httpx

from .discord_notify import create_order_embed

logger = logging.getLogger(__name__)


def create_telegram_message(
    order: Dict[str, Any],
    ws_url: Optional[str] = None
) -> Optional[str]:
    """
    Create a Telegram message for an order notification.
    
    Reuses the Discord embed creation logic to get all order details,
    then formats them for Telegram using HTML.
    
    Args:
        order: Order data dictionary from Kalshi WebSocket
        ws_url: WebSocket URL to determine API base URL (demo vs production)
    
    Returns:
        HTML-formatted message string, or None on error
    """
    try:
        # Reuse the Discord embed creation to get all the parsed data
        embed, content = create_order_embed(order, ws_url)
        if not embed:
            return None
        
        # Extract data from the embed
        title = embed.get('title', '🎯 Kalshi Order Filled')
        fields = embed.get('fields', [])
        
        # Build the Telegram message with HTML formatting
        lines = [f"<b>{title}</b>", ""]
        
        for field in fields:
            name = field.get('name', '')
            value = field.get('value', '')
            # Remove Discord markdown (**) and convert to HTML bold
            value = value.replace('**', '')
            lines.append(f"{name} {value}")
        
        # Extract the market link from content
        # Content format: "**Order Filled:** [Market Name](url)"
        if content and '[' in content and '](' in content:
            try:
                # Parse markdown link: [text](url)
                link_start = content.index('[')
                link_mid = content.index('](')
                link_end = content.index(')', link_mid)
                link_text = content[link_start + 1:link_mid]
                link_url = content[link_mid + 2:link_end]
                lines.append("")
                lines.append(f'<a href="{link_url}">View Market</a>')
            except (ValueError, IndexError):
                pass
        
        return '\n'.join(lines)
    except Exception as e:
        logger.error(f"Error creating Telegram message: {e}", exc_info=True)
        return None


async def send_telegram_notification(
    bot_token: str,
    chat_id: str,
    order: Dict[str, Any],
    ws_url: Optional[str] = None
) -> bool:
    """
    Send a Telegram notification when a Kalshi order event occurs.
    
    Args:
        bot_token: Telegram Bot API token
        chat_id: Telegram chat ID to send the message to
        order: Order data dictionary from Kalshi WebSocket
        ws_url: WebSocket URL to determine API base URL (demo vs production)
    
    Returns:
        True if notification was sent successfully, False otherwise
    """
    try:
        message = create_telegram_message(order, ws_url)
        if not message:
            logger.warning("Failed to create Telegram message, skipping notification")
            return False
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
        
        order_id = order.get('order_id', 'N/A')
        logger.info(f"Telegram notification sent for order {order_id}")
        return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Telegram API error: {e.response.status_code} - {e.response.text}")
        return False
    except httpx.RequestError as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending Telegram notification: {e}", exc_info=True)
        return False
