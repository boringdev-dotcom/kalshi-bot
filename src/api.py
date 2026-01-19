"""FastAPI application for Kalshi Live Market Dashboard."""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import Settings
from .kalshi_api import (
    get_all_sports_markets,
    get_orderbook,
    get_trades,
    get_candlesticks,
    get_market_data,
    group_markets_by_event,
    SOCCER_SERIES_TICKERS,
    BASKETBALL_SERIES_TICKERS,
)
from .kalshi_ws_client import (
    MarketDataStore,
    get_data_store,
)

logger = logging.getLogger(__name__)

# Global settings and data store
settings: Optional[Settings] = None
data_store: Optional[MarketDataStore] = None
ws_task: Optional[asyncio.Task] = None
active_subscriptions: set = set()

# Cache for markets data to avoid rate limiting
_markets_cache: Optional[List[dict]] = None
_markets_cache_time: float = 0
MARKETS_CACHE_TTL = 60.0  # Cache markets for 60 seconds


# =============================================================================
# Pydantic Models for API responses
# =============================================================================

class MarketInfo(BaseModel):
    ticker: str
    subtitle: str
    market_type: str
    yes_bid: Optional[int] = None
    yes_ask: Optional[int] = None
    no_bid: Optional[int] = None
    no_ask: Optional[int] = None
    last_price: Optional[int] = None
    volume: int = 0


class EventInfo(BaseModel):
    event_id: str
    title: str
    league: str
    close_time: Optional[str] = None
    markets: List[MarketInfo]


class LeagueInfo(BaseModel):
    league_id: str
    display_name: str
    sport: str
    events: List[EventInfo]


class OrderbookLevel(BaseModel):
    price: int
    quantity: int


class OrderbookResponse(BaseModel):
    ticker: str
    yes: List[OrderbookLevel]
    no: List[OrderbookLevel]


class TradeInfo(BaseModel):
    trade_id: Optional[str] = None
    ticker: str
    price: Optional[int] = None
    yes_price: Optional[int] = None
    no_price: Optional[int] = None
    count: int = 1
    taker_side: Optional[str] = None
    created_time: Optional[str] = None


class CandlestickInfo(BaseModel):
    timestamp: Optional[str] = None
    open: Optional[int] = None
    high: Optional[int] = None
    low: Optional[int] = None
    close: Optional[int] = None
    volume: int = 0
    yes_price: Optional[int] = None


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    websocket_connected: bool
    active_subscriptions: int


# =============================================================================
# Lifespan management
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global settings, data_store
    
    # Startup
    try:
        settings = Settings()
        data_store = get_data_store()
        logger.info("FastAPI application started")
    except Exception as e:
        logger.error(f"Failed to initialize settings: {e}")
        settings = None
    
    yield
    
    # Shutdown
    global ws_task
    if ws_task and not ws_task.done():
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
    logger.info("FastAPI application shutdown")


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="Kalshi Live Market Dashboard API",
    description="Real-time market data API for Kalshi trading",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Helper Functions
# =============================================================================

def get_settings() -> Settings:
    """Get settings, raising error if not initialized."""
    if settings is None:
        raise HTTPException(status_code=500, detail="Settings not initialized")
    return settings


def format_league_display_name(league_id: str) -> str:
    """Convert league_id to display name."""
    display_names = {
        "nba": "NBA Basketball",
        "bundesliga": "Bundesliga",
        "la_liga": "La Liga",
        "premier_league": "Premier League",
        "mls": "MLS",
        "ucl": "UEFA Champions League",
    }
    return display_names.get(league_id, league_id.replace("_", " ").title())


def get_sport_for_league(league_id: str) -> str:
    """Get sport type for a league."""
    if league_id == "nba":
        return "basketball"
    return "soccer"


# =============================================================================
# REST Endpoints
# =============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        websocket_connected=ws_task is not None and not ws_task.done(),
        active_subscriptions=len(active_subscriptions),
    )


@app.get("/api/leagues", response_model=List[dict])
async def get_leagues():
    """Get list of available leagues/sports."""
    leagues = []
    
    # Basketball leagues
    for league_id in BASKETBALL_SERIES_TICKERS.keys():
        leagues.append({
            "league_id": league_id,
            "display_name": format_league_display_name(league_id),
            "sport": "basketball",
        })
    
    # Soccer leagues
    for league_id in SOCCER_SERIES_TICKERS.keys():
        leagues.append({
            "league_id": league_id,
            "display_name": format_league_display_name(league_id),
            "sport": "soccer",
        })
    
    return leagues


@app.get("/api/markets")
async def get_markets(league: Optional[str] = None):
    """
    Get all available markets, optionally filtered by league.
    
    Returns markets grouped by event. Data is cached for 60 seconds to avoid rate limiting.
    """
    global _markets_cache, _markets_cache_time
    
    s = get_settings()
    current_time = time.time()
    
    # Check if we have valid cached data
    if _markets_cache is not None and (current_time - _markets_cache_time) < MARKETS_CACHE_TTL:
        logger.debug("Returning cached markets data")
        # Filter by league if requested
        if league:
            return [l for l in _markets_cache if l["league_id"] == league]
        return _markets_cache
    
    try:
        # Fetch fresh data in thread pool to avoid blocking
        all_markets = await asyncio.to_thread(
            get_all_sports_markets,
            key_id=s.kalshi_api_key_id,
            private_key_pem=s.kalshi_private_key_pem,
            ws_url=s.kalshi_ws_url,
        )
        
        result = []
        
        for league_id, markets in all_markets.items():
            # Group markets by event
            events = group_markets_by_event(markets)
            
            event_list = []
            for event_id, event_data in events.items():
                event_list.append({
                    "event_id": event_id,
                    "title": event_data["title"],
                    "league": league_id,
                    "close_time": event_data.get("close_time"),
                    "markets": event_data["markets"],
                })
            
            if event_list:
                result.append({
                    "league_id": league_id,
                    "display_name": format_league_display_name(league_id),
                    "sport": get_sport_for_league(league_id),
                    "events": event_list,
                })
        
        # Update cache
        _markets_cache = result
        _markets_cache_time = current_time
        logger.info(f"Markets cache updated with {len(result)} leagues")
        
        # Filter by league if requested
        if league:
            return [l for l in result if l["league_id"] == league]
        return result
        
    except Exception as e:
        logger.error(f"Failed to fetch markets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/markets/{ticker}")
async def get_market(ticker: str):
    """Get details for a specific market."""
    s = get_settings()
    
    try:
        market = get_market_data(
            ticker=ticker,
            key_id=s.kalshi_api_key_id,
            private_key_pem=s.kalshi_private_key_pem,
            ws_url=s.kalshi_ws_url,
        )
        
        if not market:
            raise HTTPException(status_code=404, detail=f"Market {ticker} not found")
        
        return market
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch market {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/markets/{ticker}/orderbook", response_model=OrderbookResponse)
async def get_market_orderbook(ticker: str, depth: int = Query(default=0, ge=0, le=100)):
    """Get orderbook for a specific market."""
    s = get_settings()
    
    try:
        orderbook = get_orderbook(
            ticker=ticker,
            key_id=s.kalshi_api_key_id,
            private_key_pem=s.kalshi_private_key_pem,
            ws_url=s.kalshi_ws_url,
            depth=depth,
        )
        
        # Format response
        return OrderbookResponse(
            ticker=ticker,
            yes=[OrderbookLevel(price=level[0], quantity=level[1]) for level in orderbook.get("yes", [])],
            no=[OrderbookLevel(price=level[0], quantity=level[1]) for level in orderbook.get("no", [])],
        )
        
    except Exception as e:
        logger.error(f"Failed to fetch orderbook for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/markets/{ticker}/trades")
async def get_market_trades(
    ticker: str,
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: Optional[str] = None,
):
    """Get recent trades for a specific market."""
    s = get_settings()
    
    try:
        result = get_trades(
            key_id=s.kalshi_api_key_id,
            private_key_pem=s.kalshi_private_key_pem,
            ws_url=s.kalshi_ws_url,
            ticker=ticker,
            limit=limit,
            cursor=cursor,
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to fetch trades for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/markets/{ticker}/candlesticks")
async def get_market_candlesticks(
    ticker: str,
    period_interval: int = Query(default=1, ge=1),
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
):
    """Get candlestick/OHLC data for a specific market."""
    s = get_settings()
    
    try:
        candlesticks = get_candlesticks(
            ticker=ticker,
            key_id=s.kalshi_api_key_id,
            private_key_pem=s.kalshi_private_key_pem,
            ws_url=s.kalshi_ws_url,
            period_interval=period_interval,
            start_ts=start_ts,
            end_ts=end_ts,
        )
        
        return {"candlesticks": candlesticks}
        
    except Exception as e:
        logger.error(f"Failed to fetch candlesticks for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WebSocket Connection Manager - Simple Initial Data Only
# =============================================================================

class ConnectionManager:
    """
    Manage WebSocket connections.
    
    Strategy: Send initial data on subscribe, let frontend poll for updates if needed.
    This avoids rate limiting issues from continuous REST polling.
    """
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, set] = {}
        self._lock = asyncio.Lock()
        # Cache for initial data to avoid repeated fetches
        self._orderbook_cache: Dict[str, tuple] = {}  # ticker -> (data, timestamp)
        self._trades_cache: Dict[str, tuple] = {}  # ticker -> (data, timestamp)
        self.CACHE_TTL = 10.0  # Cache data for 10 seconds
    
    async def connect(self, websocket: WebSocket):
        """Accept and track a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
            self.subscriptions[websocket] = set()
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")
    
    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            self.subscriptions.pop(websocket, None)
        logger.info(f"WebSocket client disconnected. Total: {len(self.active_connections)}")
    
    async def subscribe(self, websocket: WebSocket, tickers: List[str]):
        """Subscribe a connection to market tickers."""
        async with self._lock:
            if websocket in self.subscriptions:
                self.subscriptions[websocket].update(tickers)
        logger.info(f"Client subscribed to {len(tickers)} tickers")
    
    async def unsubscribe(self, websocket: WebSocket, tickers: List[str]):
        """Unsubscribe a connection from market tickers."""
        async with self._lock:
            if websocket in self.subscriptions:
                self.subscriptions[websocket].difference_update(tickers)
        logger.info(f"Client unsubscribed from {len(tickers)} tickers")
    
    async def send_to_client(self, websocket: WebSocket, message: dict) -> bool:
        """Send message to a specific client. Returns False if failed."""
        try:
            await asyncio.wait_for(websocket.send_json(message), timeout=5.0)
            return True
        except asyncio.TimeoutError:
            logger.warning("WebSocket send timeout")
            return False
        except Exception as e:
            error_msg = str(e)
            if "close" not in error_msg.lower():
                logger.debug(f"Failed to send to client: {e}")
            return False
    
    async def broadcast_to_subscribers(self, ticker: str, message: dict):
        """Send message to all clients subscribed to this ticker."""
        async with self._lock:
            subscribers = [
                ws for ws, subs in list(self.subscriptions.items())
                if ticker in subs
            ]
        
        if not subscribers:
            return
        
        # Send to all subscribers concurrently
        tasks = [self.send_to_client(ws, message) for ws in subscribers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Track failed connections for cleanup
        failed = []
        for ws, result in zip(subscribers, results):
            if result is False or isinstance(result, Exception):
                failed.append(ws)
        
        # Clean up failed connections
        for ws in failed:
            await self.disconnect(ws)
    
    def get_all_subscribed_tickers(self) -> set:
        """Get all tickers that any client is subscribed to."""
        all_tickers = set()
        for subs in self.subscriptions.values():
            all_tickers.update(subs)
        return all_tickers
    
    async def get_cached_orderbook(self, ticker: str, s: Settings) -> Optional[dict]:
        """Get orderbook from cache or fetch fresh."""
        now = time.time()
        
        # Check cache
        if ticker in self._orderbook_cache:
            data, ts = self._orderbook_cache[ticker]
            if now - ts < self.CACHE_TTL:
                return data
        
        # Fetch fresh
        try:
            orderbook = await asyncio.to_thread(
                get_orderbook,
                ticker=ticker,
                key_id=s.kalshi_api_key_id,
                private_key_pem=s.kalshi_private_key_pem,
                ws_url=s.kalshi_ws_url,
            )
            self._orderbook_cache[ticker] = (orderbook, now)
            return orderbook
        except Exception as e:
            logger.debug(f"Failed to fetch orderbook for {ticker}: {e}")
            return None
    
    async def get_cached_trades(self, ticker: str, s: Settings, limit: int = 50) -> Optional[list]:
        """Get trades from cache or fetch fresh."""
        now = time.time()
        
        # Check cache
        if ticker in self._trades_cache:
            data, ts = self._trades_cache[ticker]
            if now - ts < self.CACHE_TTL:
                return data
        
        # Fetch fresh
        try:
            trades_result = await asyncio.to_thread(
                get_trades,
                key_id=s.kalshi_api_key_id,
                private_key_pem=s.kalshi_private_key_pem,
                ws_url=s.kalshi_ws_url,
                ticker=ticker,
                limit=limit,
            )
            trades = trades_result.get("trades", [])
            self._trades_cache[ticker] = (trades, now)
            return trades
        except Exception as e:
            logger.debug(f"Failed to fetch trades for {ticker}: {e}")
            return None


manager = ConnectionManager()


@app.websocket("/ws/market-data")
async def websocket_market_data(websocket: WebSocket):
    """
    WebSocket endpoint for real-time market data.
    
    Client sends JSON messages:
    - {"action": "subscribe", "tickers": ["TICKER1", "TICKER2"]}
    - {"action": "unsubscribe", "tickers": ["TICKER1"]}
    - {"action": "ping"} - keepalive
    
    Server sends JSON messages:
    - {"type": "orderbook", "ticker": "TICKER", "data": {...}}
    - {"type": "trade", "ticker": "TICKER", "data": {...}}
    - {"type": "trades_history", "ticker": "TICKER", "data": [...]}
    - {"type": "pong"} - keepalive response
    """
    await manager.connect(websocket)
    
    try:
        while True:
            # Receive message from client with timeout for keepalive
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0  # 60 second timeout
                )
            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue
            
            try:
                message = json.loads(data)
                action = message.get("action")
                tickers = message.get("tickers", [])
                
                # Handle ping/pong keepalive
                if action == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue
                
                if action == "subscribe" and tickers:
                    await manager.subscribe(websocket, tickers)
                    
                    # Send initial data for tickers - fetch sequentially to avoid rate limiting
                    # Only fetch first 5 tickers initially, rest will load on demand
                    s = get_settings()
                    tickers_to_fetch = tickers[:5]  # Limit initial fetch
                    
                    for ticker in tickers_to_fetch:
                        # Check if still connected
                        if websocket not in manager.active_connections:
                            break
                        
                        try:
                            # Use cached data when possible
                            orderbook = await manager.get_cached_orderbook(ticker, s)
                            trades = await manager.get_cached_trades(ticker, s, limit=50)
                            
                            if orderbook:
                                await websocket.send_json({
                                    "type": "orderbook",
                                    "ticker": ticker,
                                    "data": orderbook,
                                })
                            
                            if trades:
                                await websocket.send_json({
                                    "type": "trades_history",
                                    "ticker": ticker,
                                    "data": trades,
                                })
                            
                            # Small delay to avoid rate limiting
                            await asyncio.sleep(0.2)
                            
                        except Exception as e:
                            error_msg = str(e)
                            if "close" in error_msg.lower():
                                break
                            logger.debug(f"Failed to fetch data for {ticker}: {e}")
                    
                    # Send subscribed confirmation if still connected
                    if websocket in manager.active_connections:
                        try:
                            await websocket.send_json({
                                "type": "subscribed",
                                "tickers": tickers,
                            })
                        except Exception:
                            pass
                    
                elif action == "unsubscribe" and tickers:
                    await manager.unsubscribe(websocket, tickers)
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "tickers": tickers,
                    })
                
                elif action == "refresh" and tickers:
                    # Refresh data for specific tickers (on-demand updates)
                    s = get_settings()
                    tickers_to_refresh = tickers[:3]  # Limit to 3 at a time
                    
                    for ticker in tickers_to_refresh:
                        if websocket not in manager.active_connections:
                            break
                        
                        try:
                            # Clear cache to force fresh fetch
                            manager._orderbook_cache.pop(ticker, None)
                            manager._trades_cache.pop(ticker, None)
                            
                            orderbook = await manager.get_cached_orderbook(ticker, s)
                            trades = await manager.get_cached_trades(ticker, s, limit=20)
                            
                            if orderbook:
                                await websocket.send_json({
                                    "type": "orderbook",
                                    "ticker": ticker,
                                    "data": orderbook,
                                })
                            
                            if trades:
                                await websocket.send_json({
                                    "type": "trades",
                                    "ticker": ticker,
                                    "data": trades,
                                })
                            
                            await asyncio.sleep(0.3)  # Avoid rate limiting
                            
                        except Exception as e:
                            logger.debug(f"Failed to refresh {ticker}: {e}")
                    
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown action: {action}",
                    })
                    
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON",
                })
                
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)


# =============================================================================
# Polling endpoint for simpler clients
# =============================================================================

@app.get("/api/live/{ticker}")
async def get_live_data(ticker: str):
    """
    Get current live data for a market (orderbook + recent trades).
    
    This is a polling alternative to WebSocket for simpler integrations.
    """
    s = get_settings()
    
    try:
        # Get orderbook
        orderbook = get_orderbook(
            ticker=ticker,
            key_id=s.kalshi_api_key_id,
            private_key_pem=s.kalshi_private_key_pem,
            ws_url=s.kalshi_ws_url,
        )
        
        # Get recent trades
        trades_result = get_trades(
            key_id=s.kalshi_api_key_id,
            private_key_pem=s.kalshi_private_key_pem,
            ws_url=s.kalshi_ws_url,
            ticker=ticker,
            limit=50,
        )
        
        # Get market data
        market = get_market_data(
            ticker=ticker,
            key_id=s.kalshi_api_key_id,
            private_key_pem=s.kalshi_private_key_pem,
            ws_url=s.kalshi_ws_url,
        )
        
        return {
            "ticker": ticker,
            "market": market,
            "orderbook": orderbook,
            "trades": trades_result.get("trades", []),
            "timestamp": datetime.now().isoformat(),
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch live data for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/live-multi")
async def get_live_data_multi(tickers: str = Query(..., description="Comma-separated list of tickers")):
    """
    Get current live data for multiple markets at once.
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    
    if not ticker_list:
        raise HTTPException(status_code=400, detail="No tickers provided")
    
    if len(ticker_list) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 tickers at once")
    
    s = get_settings()
    results = {}
    
    for ticker in ticker_list:
        try:
            # Get orderbook
            orderbook = get_orderbook(
                ticker=ticker,
                key_id=s.kalshi_api_key_id,
                private_key_pem=s.kalshi_private_key_pem,
                ws_url=s.kalshi_ws_url,
            )
            
            # Get recent trades
            trades_result = get_trades(
                key_id=s.kalshi_api_key_id,
                private_key_pem=s.kalshi_private_key_pem,
                ws_url=s.kalshi_ws_url,
                ticker=ticker,
                limit=20,
            )
            
            results[ticker] = {
                "orderbook": orderbook,
                "trades": trades_result.get("trades", []),
            }
        except Exception as e:
            logger.error(f"Failed to fetch live data for {ticker}: {e}")
            results[ticker] = {"error": str(e)}
    
    return {
        "data": results,
        "timestamp": datetime.now().isoformat(),
    }
