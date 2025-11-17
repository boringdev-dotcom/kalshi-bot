"""Kalshi WebSocket client for subscribing to order events."""
import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Callable, Optional

import websockets

from .kalshi_auth import sign_request

logger = logging.getLogger(__name__)

KALSHI_WS_PATH = "/trade-api/ws/v2"

# Type aliases for async callbacks
# These are async functions that take the specified arguments
OrderCallback = Callable[[dict, Optional[str]], None]  # async (order, ws_url) -> None
PriceUpdateCallback = Callable[[dict], None]  # async (market_update) -> None


async def stream_orders(
    ws_url: str,
    key_id: str,
    private_key_pem: str,
    on_created: OrderCallback,
    on_price_update: Optional[PriceUpdateCallback] = None,
    reconnect_delay: float = 1.0,
    max_reconnect_delay: float = 30.0,
) -> None:
    """
    Connect to Kalshi WebSocket and stream order events.
    
    Automatically reconnects on connection loss with exponential backoff.
    Aggregates multiple fill events for the same order_id to handle partial fills.
    
    Args:
        ws_url: WebSocket URL (e.g., wss://demo-api.kalshi.co/trade-api/ws/v2)
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format (as string)
        on_created: Async callback function called when an order is created/filled.
                    Signature: (order: dict, ws_url: Optional[str]) -> None
        on_price_update: Optional async callback for market price updates.
                         Signature: (market_update: dict) -> None
        reconnect_delay: Initial reconnect delay in seconds
        max_reconnect_delay: Maximum reconnect delay in seconds
    """
    # Track fills per order_id to aggregate partial fills
    # Partial fills are common when large orders are filled across multiple price levels
    order_fills: dict[str, list[dict]] = defaultdict(list)  # order_id -> list of fill events
    fill_timeouts: dict[str, asyncio.Task] = {}  # order_id -> asyncio.Task for aggregation timeout
    
    async def process_order_fill(fill_data: dict, order_id: str) -> None:
        """
        Process a fill event, aggregating partial fills.
        
        When an order is partially filled, Kalshi sends multiple fill events.
        This function waits 500ms to collect all fills for the same order_id,
        then aggregates them into a single notification with accurate totals.
        """
        # Add this fill to the list for this order
        order_fills[order_id].append(fill_data)
        
        # Cancel any existing timeout for this order (new fill received)
        if order_id in fill_timeouts:
            fill_timeouts[order_id].cancel()
            try:
                await fill_timeouts[order_id]  # Wait for cancellation to complete
            except asyncio.CancelledError:
                pass
        
        # Wait a short time (500ms) to see if more fills come in for the same order
        async def send_aggregated_notification() -> None:
            await asyncio.sleep(0.5)  # Wait for potential additional fills
            
            # Check if order still exists (might have been cleaned up)
            if order_id not in order_fills:
                return
            
            fills = order_fills[order_id]
            # Aggregate all fills for this order
            total_count = sum(f.get('count', 0) for f in fills)
            latest_fill = fills[-1]  # Use the latest fill for most info
            
            # Calculate total amount across all fills (important for sell orders with different prices)
            total_amount_cents = 0
            for fill in fills:
                fill_price_cents = fill.get('yes_price') or fill.get('no_price') or 0
                fill_count = fill.get('count', 0)
                total_amount_cents += fill_price_cents * fill_count
            
            # Create aggregated fill data
            aggregated = latest_fill.copy()
            aggregated['count'] = total_count
            aggregated['fill_count'] = len(fills)  # Number of partial fills
            aggregated['is_partial'] = len(fills) > 1
            
            # Store total amount for accurate calculation
            aggregated['total_amount_cents'] = total_amount_cents
            # Calculate average price for display
            if total_count > 0:
                avg_price_cents = total_amount_cents // total_count
                aggregated['yes_price'] = avg_price_cents
                aggregated['yes_price_dollars'] = f"{avg_price_cents / 100:.4f}"
            
            # Send notification
            await on_created(aggregated, ws_url)
            
            # Clean up tracking data
            order_fills.pop(order_id, None)
            fill_timeouts.pop(order_id, None)
        
        # Schedule the aggregated notification
        fill_timeouts[order_id] = asyncio.create_task(send_aggregated_notification())
    
    delay = reconnect_delay
    
    while True:
        try:
            # Generate authentication headers
            timestamp_ms = str(int(time.time() * 1000))
            signature = sign_request(private_key_pem, timestamp_ms, "GET", KALSHI_WS_PATH)
            
            headers = {
                "KALSHI-ACCESS-KEY": key_id,
                "KALSHI-ACCESS-SIGNATURE": signature,
                "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            }
            
            logger.info(f"Connecting to Kalshi WebSocket: {ws_url}")
            
            async with websockets.connect(
                ws_url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
            ) as ws:
                logger.info("Connected to Kalshi WebSocket")
                
                # Subscribe to order fill events
                subscribe_fill = {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["fill"]
                    }
                }
                await ws.send(json.dumps(subscribe_fill))
                logger.info("Subscribed to fill channel")
                
                # Subscribe to market price updates if callback provided
                # Note: Market channel may not be available in demo environment
                if on_price_update:
                    subscribe_market = {
                        "id": 2,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["market"]
                        }
                    }
                    await ws.send(json.dumps(subscribe_market))
                    logger.info("Subscribed to market channel for price updates")
                    # Note: If this fails with "Unknown channel name", market updates won't work
                    # but fill events will still contain price information
                
                # Reset reconnect delay on successful connection
                delay = reconnect_delay
                
                # Listen for messages
                async for raw_message in ws:
                    try:
                        event = json.loads(raw_message)
                        event_type = event.get("type", "unknown")
                        logger.debug(f"Received WebSocket event: type={event_type}")
                        
                        # Handle subscription confirmation
                        if event_type == "subscribed" or event.get("cmd") == "subscribe":
                            logger.info("Successfully subscribed to WebSocket channels")
                            continue
                        
                        # Handle error messages
                        if event_type == "error" or event.get("error"):
                            logger.error(f"WebSocket error: {event.get('error', event)}")
                            continue
                        
                        # Extract event data - could be in "data", "msg", or at root level
                        event_data = event.get("data") or event.get("msg") or event
                        
                        # Handle fill events (order fills)
                        if event_type == "fill":
                            order_id = event_data.get('order_id')
                            logger.info(f"Order fill received: order_id={order_id}, count={event_data.get('count')}")
                            # Process fill with aggregation to handle partial fills
                            await process_order_fill(event_data, order_id)
                            
                            # Also update odds from fill event if price update callback is available
                            # (Fill events contain current market prices)
                            if on_price_update:
                                # Extract market ticker and price info from fill event
                                ticker = event_data.get('market_ticker') or event_data.get('ticker')
                                if ticker and (event_data.get('yes_price') or event_data.get('no_price')):
                                    # Create a market-like update from fill event
                                    market_update = {
                                        'ticker': ticker,
                                        'market_ticker': ticker,
                                        'yes_price': event_data.get('yes_price'),
                                        'no_price': event_data.get('no_price'),
                                        'last_price': event_data.get('yes_price'),
                                    }
                                    await on_price_update(market_update)
                        
                        # Handle market price update events
                        elif event_type == "market" and on_price_update:
                            ticker = event_data.get('ticker') or event_data.get('market_ticker')
                            if ticker:
                                logger.debug(f"Market price update received for {ticker}")
                                await on_price_update(event_data)
                        
                        # Handle order creation/update events
                        elif event_type == "order_update" or event_type == "order":
                            status = event_data.get("status")
                            action = event_data.get("action") or event.get("action")
                            
                            logger.debug(f"Order event - status: {status}, action: {action}")
                            
                            # Check if this is a created order
                            if status in {"created", "open", "pending"} or action == "created":
                                order_id = event_data.get('order_id')
                                logger.info(f"Order created: order_id={order_id}")
                                await on_created(event_data)
                            else:
                                logger.debug(f"Ignoring order event - status: {status}, action: {action}")
                        else:
                            # Log unknown event types for debugging
                            logger.debug(f"Received unknown event type '{event_type}': {json.dumps(event)}")
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse WebSocket message: {e}")
                    except Exception as e:
                        logger.error(f"Error processing event: {e}", exc_info=True)
                        
        except websockets.ConnectionClosed as e:
            logger.warning(f"WebSocket connection closed: {e}. Reconnecting in {delay}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_reconnect_delay)
            
        except Exception as e:
            logger.error(f"WebSocket error: {e}. Reconnecting in {delay}s...", exc_info=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_reconnect_delay)

