"""Kalshi WebSocket client for subscribing to order events and market data."""
import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Callable, Optional, List, Dict, Any

import websockets

from .kalshi_auth import sign_request

logger = logging.getLogger(__name__)

KALSHI_WS_PATH = "/trade-api/ws/v2"

# Type aliases for async callbacks
# These are async functions that take the specified arguments
OrderCallback = Callable[[dict, Optional[str]], None]  # async (order, ws_url) -> None
PriceUpdateCallback = Callable[[dict], None]  # async (market_update) -> None
OrderbookCallback = Callable[[str, dict], None]  # async (ticker, orderbook) -> None
TradeCallback = Callable[[str, dict], None]  # async (ticker, trade) -> None
TickerCallback = Callable[[str, dict], None]  # async (ticker, ticker_data) -> None


@dataclass
class MarketDataStore:
    """
    Thread-safe data store for WebSocket market data.
    
    Used to share data between the WebSocket background thread and Streamlit.
    """
    # Orderbooks: ticker -> {"yes": [[price, qty], ...], "no": [[price, qty], ...]}
    orderbooks: Dict[str, Dict[str, List[List[int]]]] = field(default_factory=dict)
    
    # Trades: ticker -> list of trade dicts (most recent first)
    trades: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    
    # Ticker data (best bid/ask): ticker -> {"yes_bid": int, "yes_ask": int, ...}
    ticker_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Price history for charts: ticker -> list of (timestamp, price) tuples
    price_history: Dict[str, List[tuple]] = field(default_factory=dict)
    
    # Lock for thread-safe access
    _lock: Lock = field(default_factory=Lock)
    
    # Max trades to keep per market
    max_trades: int = 500
    
    # Max price history points per market
    max_price_history: int = 1000
    
    def update_orderbook(self, ticker: str, orderbook: Dict[str, Any]) -> None:
        """Update orderbook for a market (thread-safe)."""
        with self._lock:
            self.orderbooks[ticker] = orderbook
    
    def apply_orderbook_delta(self, ticker: str, delta: Dict[str, Any]) -> None:
        """Apply incremental orderbook update (thread-safe)."""
        with self._lock:
            if ticker not in self.orderbooks:
                # Need snapshot first
                return
            
            # Delta format: {"yes": [[price, qty_change], ...], "no": [...]}
            for side in ["yes", "no"]:
                if side not in delta:
                    continue
                for price, qty in delta.get(side, []):
                    # Find and update or insert
                    found = False
                    for i, (p, q) in enumerate(self.orderbooks[ticker].get(side, [])):
                        if p == price:
                            if qty == 0:
                                # Remove level
                                self.orderbooks[ticker][side].pop(i)
                            else:
                                # Update quantity
                                self.orderbooks[ticker][side][i] = [price, qty]
                            found = True
                            break
                    if not found and qty > 0:
                        # Insert new level
                        if side not in self.orderbooks[ticker]:
                            self.orderbooks[ticker][side] = []
                        self.orderbooks[ticker][side].append([price, qty])
                        # Sort by price (descending for bids, ascending for asks)
                        self.orderbooks[ticker][side].sort(
                            key=lambda x: x[0], 
                            reverse=(side == "yes")
                        )
    
    def add_trade(self, ticker: str, trade: Dict[str, Any]) -> None:
        """Add a trade to the history (thread-safe)."""
        with self._lock:
            if ticker not in self.trades:
                self.trades[ticker] = []
            
            # Add timestamp if not present
            if "created_time" not in trade and "timestamp" not in trade:
                trade["created_time"] = datetime.now().isoformat()
            
            # Insert at beginning (most recent first)
            self.trades[ticker].insert(0, trade)
            
            # Trim to max size
            if len(self.trades[ticker]) > self.max_trades:
                self.trades[ticker] = self.trades[ticker][:self.max_trades]
            
            # Also add to price history
            price = trade.get("yes_price") or trade.get("price")
            if price is not None:
                timestamp = trade.get("created_time") or trade.get("timestamp") or datetime.now().isoformat()
                if ticker not in self.price_history:
                    self.price_history[ticker] = []
                self.price_history[ticker].append((timestamp, price))
                if len(self.price_history[ticker]) > self.max_price_history:
                    self.price_history[ticker] = self.price_history[ticker][-self.max_price_history:]
    
    def update_ticker(self, ticker: str, data: Dict[str, Any]) -> None:
        """Update ticker data (best bid/ask) (thread-safe)."""
        with self._lock:
            self.ticker_data[ticker] = data
            
            # Add to price history if we have a price
            price = data.get("yes_price") or data.get("last_price")
            if price is not None:
                timestamp = datetime.now().isoformat()
                if ticker not in self.price_history:
                    self.price_history[ticker] = []
                self.price_history[ticker].append((timestamp, price))
                if len(self.price_history[ticker]) > self.max_price_history:
                    self.price_history[ticker] = self.price_history[ticker][-self.max_price_history:]
    
    def get_orderbook(self, ticker: str) -> Optional[Dict[str, List[List[int]]]]:
        """Get orderbook for a market (thread-safe)."""
        with self._lock:
            return self.orderbooks.get(ticker, {}).copy() if ticker in self.orderbooks else None
    
    def get_trades(self, ticker: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent trades for a market (thread-safe)."""
        with self._lock:
            return self.trades.get(ticker, [])[:limit].copy()
    
    def get_all_trades(self, tickers: List[str], limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent trades for multiple markets, merged and sorted (thread-safe)."""
        with self._lock:
            all_trades = []
            for ticker in tickers:
                for trade in self.trades.get(ticker, []):
                    trade_copy = trade.copy()
                    trade_copy["ticker"] = ticker
                    all_trades.append(trade_copy)
            
            # Sort by time (most recent first)
            all_trades.sort(
                key=lambda t: t.get("created_time") or t.get("timestamp") or "",
                reverse=True
            )
            return all_trades[:limit]
    
    def get_ticker_data(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get ticker data (thread-safe)."""
        with self._lock:
            return self.ticker_data.get(ticker, {}).copy() if ticker in self.ticker_data else None
    
    def get_price_history(self, ticker: str) -> List[tuple]:
        """Get price history for a market (thread-safe)."""
        with self._lock:
            return self.price_history.get(ticker, []).copy()
    
    def clear_market(self, ticker: str) -> None:
        """Clear all data for a market (thread-safe)."""
        with self._lock:
            self.orderbooks.pop(ticker, None)
            self.trades.pop(ticker, None)
            self.ticker_data.pop(ticker, None)
            self.price_history.pop(ticker, None)
    
    def clear_all(self) -> None:
        """Clear all data (thread-safe)."""
        with self._lock:
            self.orderbooks.clear()
            self.trades.clear()
            self.ticker_data.clear()
            self.price_history.clear()


# Global data store instance for sharing between WebSocket and Streamlit
_global_data_store: Optional[MarketDataStore] = None
_global_data_store_lock = Lock()


def get_data_store() -> MarketDataStore:
    """Get the global data store instance (creates one if needed)."""
    global _global_data_store
    with _global_data_store_lock:
        if _global_data_store is None:
            _global_data_store = MarketDataStore()
        return _global_data_store


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
                
                # Track market channel subscription status
                market_channel_subscribed = False
                market_subscription_id = 2
                
                # Subscribe to market price updates if callback provided
                # Note: Market channel may not be available in all environments
                if on_price_update:
                    subscribe_market = {
                        "id": market_subscription_id,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["market"]
                        }
                    }
                    await ws.send(json.dumps(subscribe_market))
                    logger.info("Attempting to subscribe to market channel for price updates")
                    # Note: If this fails with "Unknown channel name", market updates won't work
                    # but fill events will still contain price information and will be used instead
                
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
                            # Check if this is a market channel subscription confirmation
                            if event.get("id") == market_subscription_id:
                                market_channel_subscribed = True
                                logger.info("Market channel subscription confirmed")
                            else:
                                logger.info("Successfully subscribed to WebSocket channels")
                            continue
                        
                        # Handle error messages
                        if event_type == "error" or event.get("error"):
                            error_id = event.get("id")
                            error_msg = event.get("msg") or event.get("error", {})
                            
                            # Check if this is the market channel subscription error
                            if error_id == market_subscription_id:
                                # Market channel not available - this is expected in some environments
                                error_code = error_msg.get("code") if isinstance(error_msg, dict) else None
                                error_text = error_msg.get("msg") if isinstance(error_msg, dict) else str(error_msg)
                                
                                if error_code == 8 and "Unknown channel name" in str(error_text):
                                    logger.warning(
                                        "Market channel not available - price updates will use fill events only. "
                                        "This is normal if the market channel is not supported in your environment."
                                    )
                                    market_channel_subscribed = False
                                    continue
                            
                            # Log other errors normally
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


async def stream_market_data(
    ws_url: str,
    key_id: str,
    private_key_pem: str,
    market_tickers: List[str],
    data_store: Optional[MarketDataStore] = None,
    on_orderbook: Optional[OrderbookCallback] = None,
    on_trade: Optional[TradeCallback] = None,
    on_ticker: Optional[TickerCallback] = None,
    reconnect_delay: float = 1.0,
    max_reconnect_delay: float = 30.0,
) -> None:
    """
    Connect to Kalshi WebSocket and stream market data for specified tickers.
    
    Subscribes to orderbook_snapshot, orderbook_delta, trade, and ticker channels
    for the specified market tickers.
    
    Args:
        ws_url: WebSocket URL (e.g., wss://api.elections.kalshi.com/trade-api/ws/v2)
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format (as string)
        market_tickers: List of market ticker symbols to subscribe to
        data_store: Optional MarketDataStore to automatically store updates
        on_orderbook: Optional callback for orderbook updates (ticker, orderbook_data)
        on_trade: Optional callback for trade events (ticker, trade_data)
        on_ticker: Optional callback for ticker updates (ticker, ticker_data)
        reconnect_delay: Initial reconnect delay in seconds
        max_reconnect_delay: Maximum reconnect delay in seconds
    """
    if not market_tickers:
        logger.warning("No market tickers provided, nothing to subscribe to")
        return
    
    # Use global data store if none provided
    if data_store is None:
        data_store = get_data_store()
    
    delay = reconnect_delay
    subscription_id = 1
    
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
            
            logger.info(f"Connecting to Kalshi WebSocket for market data: {ws_url}")
            
            async with websockets.connect(
                ws_url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
            ) as ws:
                logger.info(f"Connected to Kalshi WebSocket, subscribing to {len(market_tickers)} markets")
                
                # Subscribe to channels for each market ticker
                for ticker in market_tickers:
                    # Subscribe to orderbook_snapshot (will also get deltas)
                    subscribe_orderbook = {
                        "id": subscription_id,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["orderbook_delta"],
                            "market_ticker": ticker
                        }
                    }
                    await ws.send(json.dumps(subscribe_orderbook))
                    logger.debug(f"Subscribed to orderbook for {ticker}")
                    subscription_id += 1
                    
                    # Subscribe to trades
                    subscribe_trades = {
                        "id": subscription_id,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["trade"],
                            "market_ticker": ticker
                        }
                    }
                    await ws.send(json.dumps(subscribe_trades))
                    logger.debug(f"Subscribed to trades for {ticker}")
                    subscription_id += 1
                    
                    # Subscribe to ticker (best bid/ask)
                    subscribe_ticker = {
                        "id": subscription_id,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["ticker"],
                            "market_ticker": ticker
                        }
                    }
                    await ws.send(json.dumps(subscribe_ticker))
                    logger.debug(f"Subscribed to ticker for {ticker}")
                    subscription_id += 1
                
                logger.info(f"Subscribed to all channels for {len(market_tickers)} markets")
                
                # Reset reconnect delay on successful connection
                delay = reconnect_delay
                
                # Listen for messages
                async for raw_message in ws:
                    try:
                        event = json.loads(raw_message)
                        event_type = event.get("type", "unknown")
                        
                        # Handle subscription confirmation
                        if event_type == "subscribed" or event.get("cmd") == "subscribe":
                            logger.debug(f"Subscription confirmed: {event}")
                            continue
                        
                        # Handle error messages
                        if event_type == "error" or event.get("error"):
                            error_msg = event.get("msg") or event.get("error", {})
                            logger.warning(f"WebSocket error: {error_msg}")
                            continue
                        
                        # Extract event data and ticker
                        event_data = event.get("msg") or event.get("data") or event
                        ticker = (
                            event_data.get("market_ticker") or 
                            event_data.get("ticker") or
                            event.get("market_ticker")
                        )
                        
                        # Handle orderbook snapshot
                        if event_type == "orderbook_snapshot":
                            if ticker:
                                orderbook = {
                                    "yes": event_data.get("yes", []),
                                    "no": event_data.get("no", [])
                                }
                                data_store.update_orderbook(ticker, orderbook)
                                logger.debug(f"Orderbook snapshot received for {ticker}")
                                if on_orderbook:
                                    await on_orderbook(ticker, orderbook)
                        
                        # Handle orderbook delta
                        elif event_type == "orderbook_delta":
                            if ticker:
                                delta = {
                                    "yes": event_data.get("yes", []),
                                    "no": event_data.get("no", [])
                                }
                                data_store.apply_orderbook_delta(ticker, delta)
                                logger.debug(f"Orderbook delta received for {ticker}")
                                if on_orderbook:
                                    # Return the full updated orderbook
                                    updated_book = data_store.get_orderbook(ticker)
                                    if updated_book:
                                        await on_orderbook(ticker, updated_book)
                        
                        # Handle trade events
                        elif event_type == "trade":
                            if ticker:
                                trade_data = {
                                    "trade_id": event_data.get("trade_id"),
                                    "ticker": ticker,
                                    "price": event_data.get("price") or event_data.get("yes_price"),
                                    "yes_price": event_data.get("yes_price") or event_data.get("price"),
                                    "no_price": event_data.get("no_price"),
                                    "count": event_data.get("count") or event_data.get("size") or 1,
                                    "taker_side": event_data.get("taker_side") or event_data.get("side"),
                                    "created_time": event_data.get("created_time") or event_data.get("ts") or datetime.now().isoformat(),
                                }
                                data_store.add_trade(ticker, trade_data)
                                logger.debug(f"Trade received for {ticker}: {trade_data.get('count')} @ {trade_data.get('price')}¢")
                                if on_trade:
                                    await on_trade(ticker, trade_data)
                        
                        # Handle ticker updates (best bid/ask)
                        elif event_type == "ticker":
                            if ticker:
                                ticker_data = {
                                    "ticker": ticker,
                                    "yes_bid": event_data.get("yes_bid"),
                                    "yes_ask": event_data.get("yes_ask"),
                                    "no_bid": event_data.get("no_bid"),
                                    "no_ask": event_data.get("no_ask"),
                                    "last_price": event_data.get("last_price") or event_data.get("yes_price"),
                                    "volume": event_data.get("volume"),
                                }
                                data_store.update_ticker(ticker, ticker_data)
                                logger.debug(f"Ticker update for {ticker}: bid={ticker_data.get('yes_bid')} ask={ticker_data.get('yes_ask')}")
                                if on_ticker:
                                    await on_ticker(ticker, ticker_data)
                        
                        else:
                            # Log unknown event types for debugging
                            logger.debug(f"Received event type '{event_type}': {json.dumps(event)[:200]}")
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse WebSocket message: {e}")
                    except Exception as e:
                        logger.error(f"Error processing market data event: {e}", exc_info=True)
                        
        except websockets.ConnectionClosed as e:
            logger.warning(f"WebSocket connection closed: {e}. Reconnecting in {delay}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_reconnect_delay)
            
        except Exception as e:
            logger.error(f"WebSocket error: {e}. Reconnecting in {delay}s...", exc_info=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_reconnect_delay)


def start_market_data_stream_thread(
    ws_url: str,
    key_id: str,
    private_key_pem: str,
    market_tickers: List[str],
    data_store: Optional[MarketDataStore] = None,
) -> asyncio.AbstractEventLoop:
    """
    Start the market data stream in a background thread.
    
    This is useful for Streamlit integration where we need the WebSocket
    running in a separate thread.
    
    Args:
        ws_url: WebSocket URL
        key_id: Kalshi API key ID
        private_key_pem: RSA private key
        market_tickers: List of market tickers to subscribe to
        data_store: Optional MarketDataStore (uses global if not provided)
    
    Returns:
        The event loop running in the background thread
    """
    import threading
    
    if data_store is None:
        data_store = get_data_store()
    
    loop = asyncio.new_event_loop()
    
    def run_stream():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            stream_market_data(
                ws_url=ws_url,
                key_id=key_id,
                private_key_pem=private_key_pem,
                market_tickers=market_tickers,
                data_store=data_store,
            )
        )
    
    thread = threading.Thread(target=run_stream, daemon=True)
    thread.start()
    logger.info(f"Started market data stream thread for {len(market_tickers)} markets")
    
    return loop

