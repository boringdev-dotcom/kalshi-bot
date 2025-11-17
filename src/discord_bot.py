"""Discord bot client for sending and updating order notifications."""
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, TypedDict

import discord

logger = logging.getLogger(__name__)


class OrderMessageData(TypedDict, total=False):
    """Type definition for order message tracking data."""
    message: discord.Message
    order: dict
    ws_url: Optional[str]
    last_price: Optional[int]


# Global state: Track active order messages for real-time odds updates
# This allows us to edit Discord messages when market prices change via WebSocket
# Key: order_id (str), Value: OrderMessageData
# Lifecycle: Messages are added when orders are filled, removed when:
#   - Market closes (status != 'active'/'open')
#   - Message is deleted
#   - Error occurs updating the message
active_order_messages: Dict[str, OrderMessageData] = {}

# Global bot instance: Single bot instance shared across the application
# Set by initialize_bot(), checked by send_order_notification() and handle_price_update()
# This is a singleton pattern - only one bot instance should exist
_bot_instance: Optional["KalshiDiscordBot"] = None


class KalshiDiscordBot(discord.Client):
    """Discord bot for Kalshi order notifications."""
    
    def __init__(self, channel_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel_id = channel_id
        self.channel: Optional[discord.TextChannel] = None
    
    async def on_ready(self):
        """Called when the bot is ready."""
        logger.info(f"Discord bot logged in as {self.user}")
        self.channel = self.get_channel(self.channel_id)
        if not self.channel:
            logger.error(f"Could not find channel with ID {self.channel_id}")
        else:
            logger.info(f"Bot connected to channel: {self.channel.name}")
    
    async def update_odds_from_websocket(self, market_update: dict) -> None:
        """
        Update odds for active orders when WebSocket receives market price update.
        
        This method edits existing Discord messages to reflect current market prices,
        providing real-time odds updates without spamming new messages.
        
        Args:
            market_update: Market update dictionary from WebSocket, containing:
                - ticker/market_ticker: Market identifier
                - yes_price/no_price: Current prices in cents
                - status: Market status ('active', 'open', 'closed', etc.)
        """
        if not self.channel:
            return
        
        ticker = market_update.get('ticker') or market_update.get('market_ticker')
        if not ticker:
            return
        
        # Find all active orders for this market
        orders_to_update = [
            (order_id, order_data) 
            for order_id, order_data in active_order_messages.items()
            if (order_data.get('order', {}).get('market_ticker') or 
                order_data.get('order', {}).get('ticker')) == ticker
        ]
        
        if not orders_to_update:
            return
        
        # Extract price data from market update
        # Market updates might have yes_price, no_price, yes_bid, yes_ask, no_bid, no_ask, last_price
        yes_price = market_update.get('yes_price') or market_update.get('yes_bid') or market_update.get('yes_ask') or market_update.get('last_price')
        no_price = market_update.get('no_price') or market_update.get('no_bid') or market_update.get('no_ask')
        if not no_price and market_update.get('last_price'):
            # If last_price is YES price, calculate NO price
            no_price = 100 - market_update.get('last_price')
        
        # Check market status
        market_status = market_update.get('status', '').lower()
        if market_status and market_status not in ('active', 'open'):
            # Market closed, remove all orders for this market from tracking
            for order_id, order_data in orders_to_update:
                logger.debug(f"Market {ticker} is {market_status}, removing order {order_id} from tracking")
                active_order_messages.pop(order_id, None)
            return
        
        # Update each order message
        for order_id, order_data in orders_to_update:
            try:
                message = order_data.get('message')
                order = order_data.get('order', {})
                if not message or not order:
                    continue
                    
                raw_side = order.get('side', '')
                
                # Determine current price based on side
                if raw_side.upper() == 'YES':
                    current_price_cents = yes_price
                elif raw_side.upper() == 'NO':
                    current_price_cents = no_price
                else:
                    current_price_cents = market_update.get('last_price')
                
                if current_price_cents is None:
                    continue
                
                # Only update if price changed
                if current_price_cents == order_data.get('last_price'):
                    continue
                
                order_data['last_price'] = current_price_cents
                
                # Update the embed with new odds
                embed = message.embeds[0] if message.embeds else None
                if embed:
                    # Find and update the odds field
                    odds_field_index = None
                    for i, field in enumerate(embed.fields):
                        if field.name == "🎯 Odds":
                            odds_field_index = i
                            break
                    
                    odds_value = f"**{current_price_cents}%**"
                    if odds_field_index is not None:
                        embed.set_field_at(odds_field_index, name="🎯 Odds", value=odds_value, inline=True)
                    else:
                        # Add odds field if it doesn't exist
                        embed.add_field(name="🎯 Odds", value=odds_value, inline=True)
                    
                    # Update timestamp
                    embed.timestamp = datetime.utcnow()
                    
                    await message.edit(embed=embed)
                    logger.debug(f"Updated odds for order {order_id} via WebSocket: {current_price_cents}%")
                
            except discord.errors.NotFound:
                # Message was deleted, remove from tracking
                logger.debug(f"Message for order {order_id} was deleted, removing from tracking")
                active_order_messages.pop(order_id, None)
            except Exception as e:
                logger.error(f"Error updating odds for order {order_id}: {e}", exc_info=True)


async def initialize_bot(channel_id: int, token: str) -> None:
    """
    Initialize and start the Discord bot.
    
    This function creates a singleton bot instance and starts it in the background.
    The bot will connect to the specified channel and be ready to send notifications.
    
    Args:
        channel_id: Discord channel ID where notifications will be sent
        token: Discord bot token
        
    Raises:
        Exception: If bot initialization fails
    """
    global _bot_instance
    
    # Enable intents - message_content may be needed for reading messages
    intents = discord.Intents.default()
    intents.message_content = True
    
    _bot_instance = KalshiDiscordBot(channel_id=channel_id, intents=intents)
    
    async def start_bot() -> None:
        """Background task to start the bot."""
        try:
            await _bot_instance.start(token)
        except Exception as e:
            logger.error(f"Error in bot start task: {e}", exc_info=True)
    
    # Start bot in background task
    bot_task = asyncio.create_task(start_bot())
    
    # Give the task a moment to actually start the bot
    await asyncio.sleep(0.1)
    
    # Wait for bot to be ready
    await _bot_instance.wait_until_ready()
    logger.info("Discord bot initialized and ready")


async def handle_price_update(market_update: dict) -> None:
    """
    Handle market price update from WebSocket.
    
    This is the callback function passed to stream_orders() to receive
    real-time market price updates for updating Discord message odds.
    
    Args:
        market_update: Market update dictionary from WebSocket
    """
    global _bot_instance
    if _bot_instance:
        await _bot_instance.update_odds_from_websocket(market_update)


async def send_order_notification(
    order: dict, 
    ws_url: Optional[str] = None
) -> Optional[discord.Message]:
    """
    Send a Discord notification for an order fill.
    
    Creates a formatted Discord message with order details and tracks it
    for real-time odds updates via update_odds_from_websocket().
    
    Args:
        order: Order data dictionary from Kalshi WebSocket
        ws_url: WebSocket URL (used to determine API base URL for market links)
        
    Returns:
        Discord message object if successful, None otherwise
    """
    global _bot_instance
    
    if not _bot_instance:
        logger.error("Discord bot instance not found")
        return None
    
    if not _bot_instance.channel:
        logger.error(f"Discord bot channel not found (channel_id={_bot_instance.channel_id})")
        return None
    
    try:
        # Import here to avoid circular dependency
        from .discord_notify import create_order_embed
        
        embed_dict, content = create_order_embed(order, ws_url)
        if not embed_dict:
            logger.error("Failed to create order embed")
            return None
        
        # Create embed from dict
        embed = discord.Embed.from_dict(embed_dict)
        
        # Send message
        message = await _bot_instance.channel.send(content=content, embed=embed)
        
        # Track this message for odds updates (allows real-time price updates)
        order_id = order.get('order_id', 'unknown')
        active_order_messages[order_id] = OrderMessageData(
            message=message,
            order=order,
            ws_url=ws_url,
            last_price=order.get('yes_price') or order.get('no_price'),
        )
        
        logger.info(f"Discord bot notification sent for order {order_id}")
        return message
        
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}", exc_info=True)
        return None

