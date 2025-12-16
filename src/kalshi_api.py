"""Kalshi REST API client for fetching market details."""
import logging
import time
from typing import Optional, List, Dict, Any

import requests

from .kalshi_auth import sign_request

logger = logging.getLogger(__name__)

# Soccer series tickers on Kalshi (use these for direct API filtering)
# Each league can have multiple series (e.g., GAME for winner/tie, SPREAD for spreads)
# Run discover_sports.py to find all available series tickers
SOCCER_SERIES_TICKERS = {
    "la_liga": [
        "KXLALIGAGAME",      # Winner/Tie markets
        "KXLALIGASPREAD",    # Spread markets
        "KXLALIGATOTAL",     # Total goals (Over/Under)
        "KXLALIGABTTS",      # Both Teams To Score
    ],
    "premier_league": [
        "KXEPLGAME",         # Winner/Tie markets  
        "KXEPLSPREAD",       # Spread markets
        "KXEPLTOTAL",        # Total goals (Over/Under)
        "KXEPLBTTS",         # Both Teams To Score
    ],
    "mls": [
        "KXMLSGAME",         # Winner/Tie markets        # Both Teams To Score
    ],
    "ucl": [
        "KXUCLGAME",         # Winner/Tie markets
        "KXUCLSPREAD",       # Spread markets
        "KXUCLTOTAL",        # Total goals (Over/Under)
        "KXUCLBTTS",         # Both Teams To Score
    ],
    "bundesliga": [
        "KXBUNDESLIGAGAME",         # Winner/Tie markets
        "KXBUNDESLIGASPREAD",       # Spread markets
        "KXBUNDESLIGATOTAL",        # Total goals (Over/Under)
        "KXBUNDESLIGABTTS",         # Both Teams To Score
    ],
}

# Ticker prefixes for searching (markets start with these)
SOCCER_TICKER_PREFIXES = {
    "la_liga": ["KXLALIGA", "LALIGA"],
    "premier_league": ["KXEPL", "KXPREMIER", "EPL"],
    "mls": ["KXMLS", "MLS"],
    "ucl": ["KXUCL", "UCL"],
    "bundesliga": ["KXBUNDESLIGA", "BUNDESLIGA"],
}

# Fallback search terms if series tickers don't work
SOCCER_SEARCH_TERMS = {
    "la_liga": ["LA LIGA", "LALIGA", "LA-LIGA"],
    "premier_league": ["PREMIER LEAGUE", "EPL", "ENGLISH PREMIER"],
}

# Market types we're interested in
SOCCER_MARKET_TYPES = ["winner", "spread", "moneyline"]

# Basketball (NBA) series tickers on Kalshi
# Based on URL pattern: kxnbagame/professional-basketball-game/kxnbagame-25dec06nopbkn
BASKETBALL_SERIES_TICKERS = {
    "nba": [
        "KXNBAGAME",      # Winner markets (moneyline)
        "KXNBASPREAD",    # Point spread markets
        "KXNBATOTAL",     # Total points (Over/Under)
    ],
}

# Ticker prefixes for basketball searching
BASKETBALL_TICKER_PREFIXES = {
    "nba": ["KXNBA", "NBA"],
}

# Fallback search terms for basketball
BASKETBALL_SEARCH_TERMS = {
    "nba": ["NBA", "PROFESSIONAL BASKETBALL", "BASKETBALL"],
}

# Basketball market types
BASKETBALL_MARKET_TYPES = ["winner", "spread", "total", "moneyline"]


def get_market_name(ticker: str, key_id: str, private_key_pem: str, ws_url: str = None) -> Optional[str]:
    """
    Fetch market name from Kalshi REST API.
    
    Args:
        ticker: Market ticker symbol
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL (demo vs production)
        
    Returns:
        Market title/name or None if fetch fails
    """
    # Determine API base URL from WebSocket URL
    if ws_url and "demo" in ws_url:
        base_url = "https://demo-api.kalshi.co"
    else:
        base_url = "https://api.elections.kalshi.com"
    
    path = f"/trade-api/v2/markets/{ticker}"
    url = base_url + path
    
    try:
        # Generate authentication headers
        timestamp_ms = str(int(time.time() * 1000))
        signature = sign_request(private_key_pem, timestamp_ms, "GET", path)
        
        headers = {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        # Market name is typically in 'title' field
        # Try multiple possible locations in the response
        market_name = (
            data.get('market', {}).get('title') or 
            data.get('title') or
            data.get('market', {}).get('subtitle') or
            data.get('subtitle')
        )
        
        if not market_name:
            logger.warning(f"Market name not found in API response for {ticker}: {list(data.keys())}")
            return None
            
        return market_name
        
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch market name for {ticker}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error fetching market name for {ticker}: {e}", exc_info=True)
        return None


# Cache market names to avoid repeated API calls
_market_cache = {}


def get_market_data(ticker: str, key_id: str, private_key_pem: str, ws_url: str = None) -> Optional[dict]:
    """
    Fetch full market data from Kalshi REST API.
    
    Args:
        ticker: Market ticker symbol
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL (demo vs production)
        
    Returns:
        Market data dictionary or None if fetch fails
    """
    # Determine API base URL from WebSocket URL
    if ws_url and "demo" in ws_url:
        base_url = "https://demo-api.kalshi.co"
    else:
        base_url = "https://api.elections.kalshi.com"
    
    path = f"/trade-api/v2/markets/{ticker}"
    url = base_url + path
    
    try:
        # Generate authentication headers
        timestamp_ms = str(int(time.time() * 1000))
        signature = sign_request(private_key_pem, timestamp_ms, "GET", path)
        
        headers = {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        return data.get('market') or data
        
    except Exception as e:
        logger.warning(f"Failed to fetch market data for {ticker}: {e}")
        return None


def get_market_name_cached(ticker: str, key_id: str, private_key_pem: str, ws_url: str = None) -> str:
    """
    Get market name with caching to reduce API calls.
    
    Returns ticker if name cannot be fetched.
    """
    if ticker in _market_cache:
        return _market_cache[ticker]
    
    market_name = get_market_name(ticker, key_id, private_key_pem, ws_url)
    if market_name:
        _market_cache[ticker] = market_name
        return market_name
    
    # Return ticker as fallback
    return ticker


def get_markets(
    key_id: str, 
    private_key_pem: str, 
    ws_url: str = None,
    status: str = "open",
    limit: int = 200,
    cursor: str = None,
    series_ticker: str = None,
    event_ticker: str = None,
) -> Dict[str, Any]:
    """
    Fetch markets from Kalshi REST API with pagination support.
    
    Args:
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL (demo vs production)
        status: Market status filter (open, closed, settled)
        limit: Maximum number of markets to return per page
        cursor: Pagination cursor
        series_ticker: Filter by series ticker
        event_ticker: Filter by event ticker
        
    Returns:
        Dictionary with 'markets' list and 'cursor' for pagination
    """
    if ws_url and "demo" in ws_url:
        base_url = "https://demo-api.kalshi.co"
    else:
        base_url = "https://api.elections.kalshi.com"
    
    path = "/trade-api/v2/markets"
    
    # Build query parameters
    params = {"status": status, "limit": limit}
    if cursor:
        params["cursor"] = cursor
    if series_ticker:
        params["series_ticker"] = series_ticker
    if event_ticker:
        params["event_ticker"] = event_ticker
    
    # Build full URL with query params
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    full_path = f"{path}?{query_string}"
    url = base_url + full_path
    
    try:
        timestamp_ms = str(int(time.time() * 1000))
        signature = sign_request(private_key_pem, timestamp_ms, "GET", full_path)
        
        headers = {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        return response.json()
        
    except Exception as e:
        logger.error(f"Failed to fetch markets: {e}")
        return {"markets": [], "cursor": None}


def get_sports_filters(
    key_id: str,
    private_key_pem: str,
    ws_url: str = None,
) -> Dict[str, Any]:
    """
    Fetch available sports filters from Kalshi API.
    
    This helps discover available sports leagues and their series tickers.
    
    Args:
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL
        
    Returns:
        Dictionary with sports filter information
    """
    if ws_url and "demo" in ws_url:
        base_url = "https://demo-api.kalshi.co"
    else:
        base_url = "https://api.elections.kalshi.com"
    
    path = "/trade-api/v2/search/filters-for-sports"
    url = base_url + path
    
    try:
        timestamp_ms = str(int(time.time() * 1000))
        signature = sign_request(private_key_pem, timestamp_ms, "GET", path)
        
        headers = {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        return response.json()
        
    except Exception as e:
        logger.error(f"Failed to fetch sports filters: {e}")
        return {}


def get_events(
    key_id: str,
    private_key_pem: str,
    ws_url: str = None,
    status: str = None,
    series_ticker: str = None,
    limit: int = 100,
    cursor: str = None,
) -> Dict[str, Any]:
    """
    Fetch events from Kalshi REST API.
    
    Args:
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL
        status: Event status filter
        series_ticker: Filter by series ticker
        limit: Maximum number of events to return
        cursor: Pagination cursor
        
    Returns:
        Dictionary with 'events' list and 'cursor' for pagination
    """
    if ws_url and "demo" in ws_url:
        base_url = "https://demo-api.kalshi.co"
    else:
        base_url = "https://api.elections.kalshi.com"
    
    path = "/trade-api/v2/events"
    
    params = {"limit": limit}
    if status:
        params["status"] = status
    if series_ticker:
        params["series_ticker"] = series_ticker
    if cursor:
        params["cursor"] = cursor
    
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    full_path = f"{path}?{query_string}"
    url = base_url + full_path
    
    try:
        timestamp_ms = str(int(time.time() * 1000))
        signature = sign_request(private_key_pem, timestamp_ms, "GET", full_path)
        
        headers = {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        return response.json()
        
    except Exception as e:
        logger.error(f"Failed to fetch events: {e}")
        return {"events": [], "cursor": None}


def get_soccer_markets(
    key_id: str,
    private_key_pem: str,
    ws_url: str = None,
    leagues: List[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch soccer markets for specified leagues (La Liga, Premier League).
    
    Uses series_ticker filtering for efficient API calls when possible.
    
    Args:
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL
        leagues: List of leagues to filter ("la_liga", "premier_league")
                 If None, fetches both.
        
    Returns:
        List of soccer market dictionaries with market details and odds
    """
    if leagues is None:
        leagues = ["la_liga", "premier_league", "mls", "bundesliga"]
    
    soccer_markets = []
    seen_tickers = set()  # Avoid duplicates across series
    
    # Try to fetch using series_ticker for each league (fast path)
    for league in leagues:
        series_tickers = SOCCER_SERIES_TICKERS.get(league, [])
        # Handle both list and legacy string format
        if isinstance(series_tickers, str):
            series_tickers = [series_tickers]
        
        for series_ticker in series_tickers:
            logger.info(f"Fetching {league} markets using series_ticker: {series_ticker}")
            cursor = None
            
            while True:
                result = get_markets(
                    key_id=key_id,
                    private_key_pem=private_key_pem,
                    ws_url=ws_url,
                    status="open",
                    limit=100,
                    cursor=cursor,
                    series_ticker=series_ticker,
                )
                
                markets = result.get("markets", [])
                if not markets:
                    break
                
                for market in markets:
                    ticker = market.get("ticker")
                    if ticker and ticker not in seen_tickers:
                        seen_tickers.add(ticker)
                        soccer_markets.append(_format_soccer_market(market, league))
                
                cursor = result.get("cursor")
                if not cursor:
                    break
    
    # If no markets found via series_ticker, try event-based search
    if not soccer_markets:
        logger.info("No markets via series_ticker, trying event search...")
        soccer_markets = _search_soccer_markets_fallback(
            key_id, private_key_pem, ws_url, leagues
        )
    
    logger.info(f"Found {len(soccer_markets)} soccer markets for leagues: {leagues}")
    return soccer_markets


def _format_soccer_market(market: Dict[str, Any], league: str) -> Dict[str, Any]:
    """Format a market dict for soccer analysis."""
    ticker = market.get("ticker", "").upper()
    title = market.get("title", "").upper()
    subtitle = market.get("subtitle", "").upper()
    series_ticker = market.get("series_ticker", "").upper()
    combined_text = f"{ticker} {title} {subtitle}"
    
    # Determine market type based on series ticker first (most reliable)
    market_type = "unknown"
    if "SPREAD" in series_ticker or "SPREAD" in ticker:
        # Spread series - "wins by over X goals"
        market_type = "spread"
    elif "TOTAL" in series_ticker or "TOTAL" in ticker:
        market_type = "total"
    elif "BTTS" in ticker or "BOTH TEAMS" in combined_text:
        market_type = "btts"
    elif "TIE" in combined_text or "DRAW" in combined_text or ticker.endswith("-TIE"):
        market_type = "tie"
    elif "WINS BY OVER" in combined_text or "WIN BY OVER" in combined_text:
        # Spread pattern: "Team wins by over X.X goals"
        market_type = "spread"
    elif "OVER" in combined_text and "GOALS" in combined_text:
        # Total goals pattern: "Over X.X goals scored"
        market_type = "total"
    elif any(t in combined_text for t in ["WINNER", "MONEYLINE", "TO WIN"]):
        market_type = "winner"
    elif combined_text.endswith("WINNER?") and "BY OVER" not in combined_text:
        market_type = "winner"
    
    return {
        "ticker": market.get("ticker"),
        "title": market.get("title"),
        "subtitle": market.get("subtitle"),
        "yes_bid": market.get("yes_bid"),
        "yes_ask": market.get("yes_ask"),
        "no_bid": market.get("no_bid"),
        "no_ask": market.get("no_ask"),
        "last_price": market.get("last_price"),
        "volume": market.get("volume"),
        "open_interest": market.get("open_interest"),
        "close_time": market.get("close_time"),
        "expiration_time": market.get("expiration_time"),
        "market_type": market_type,
        "league": league,
        "yes_sub_title": market.get("yes_sub_title"),
        "no_sub_title": market.get("no_sub_title"),
        "event_ticker": market.get("event_ticker"),
        "series_ticker": market.get("series_ticker"),
    }


def _search_soccer_markets_fallback(
    key_id: str,
    private_key_pem: str,
    ws_url: str,
    leagues: List[str],
) -> List[Dict[str, Any]]:
    """
    Fallback: Search for soccer markets by scanning events.
    
    This is slower but more reliable if series_tickers change.
    """
    soccer_markets = []
    
    # Build search terms
    search_terms = ["SOCCER", "FOOTBALL"]
    for league in leagues:
        if league in SOCCER_SEARCH_TERMS:
            search_terms.extend(SOCCER_SEARCH_TERMS[league])
    
    # Fetch events and look for soccer
    cursor = None
    checked_events = set()
    
    while True:
        result = get_events(
            key_id=key_id,
            private_key_pem=private_key_pem,
            ws_url=ws_url,
            status="open",
            limit=100,
            cursor=cursor,
        )
        
        events = result.get("events", [])
        if not events:
            break
        
        for event in events:
            event_ticker = event.get("event_ticker", "")
            if event_ticker in checked_events:
                continue
            checked_events.add(event_ticker)
            
            title = event.get("title", "").upper()
            category = event.get("category", "").upper()
            combined = f"{event_ticker} {title} {category}"
            
            # Check if this is a soccer event
            if any(term in combined.upper() for term in search_terms):
                # Determine league
                detected_league = "unknown"
                for league_name, terms in SOCCER_SEARCH_TERMS.items():
                    if league_name in leagues and any(t in combined for t in terms):
                        detected_league = league_name
                        break
                
                if detected_league == "unknown":
                    continue
                
                # Fetch markets for this event
                market_result = get_markets(
                    key_id=key_id,
                    private_key_pem=private_key_pem,
                    ws_url=ws_url,
                    status="open",
                    event_ticker=event_ticker,
                    limit=50,
                )
                
                for market in market_result.get("markets", []):
                    soccer_markets.append(_format_soccer_market(market, detected_league))
        
        cursor = result.get("cursor")
        if not cursor:
            break
    
    return soccer_markets


def format_markets_for_analysis(markets: List[Dict[str, Any]]) -> str:
    """
    Format soccer markets into a readable string for LLM analysis.
    
    Args:
        markets: List of soccer market dictionaries
        
    Returns:
        Formatted string describing the markets and their odds
    """
    if not markets:
        return "No soccer markets found for the specified leagues."
    
    # Group markets by league and then by match
    from collections import defaultdict
    by_league = defaultdict(list)
    
    for market in markets:
        league = market.get("league", "unknown")
        by_league[league].append(market)
    
    output = []
    
    for league, league_markets in by_league.items():
        league_display = league.replace("_", " ").title()
        output.append(f"\n{'='*50}")
        output.append(f"  {league_display}")
        output.append(f"{'='*50}\n")
        
        # Group by event/match
        by_event = defaultdict(list)
        for market in league_markets:
            event = market.get("event_ticker") or market.get("title", "Unknown")
            by_event[event].append(market)
        
        for event, event_markets in by_event.items():
            # Get the main match title
            main_title = event_markets[0].get("title", event)
            output.append(f"\n📅 {main_title}")
            output.append("-" * 40)
            
            for market in event_markets:
                ticker = market.get("ticker", "N/A")
                market_type = market.get("market_type", "unknown")
                yes_bid = market.get("yes_bid")
                yes_ask = market.get("yes_ask")
                yes_sub = market.get("yes_sub_title", "YES")
                no_sub = market.get("no_sub_title", "NO")
                
                # Format odds
                if yes_bid and yes_ask:
                    yes_mid = (yes_bid + yes_ask) / 2
                    no_mid = 100 - yes_mid
                    output.append(f"  [{market_type.upper()}] {ticker}")
                    output.append(f"    {yes_sub}: {yes_mid:.0f}¢ (bid: {yes_bid}¢, ask: {yes_ask}¢)")
                    output.append(f"    {no_sub}: {no_mid:.0f}¢")
                else:
                    last_price = market.get("last_price", "N/A")
                    output.append(f"  [{market_type.upper()}] {ticker}")
                    output.append(f"    Last Price: {last_price}¢")
                
                output.append("")
    
    return "\n".join(output)


# =============================================================================
# BASKETBALL (NBA) MARKET FUNCTIONS
# =============================================================================

def get_basketball_markets(
    key_id: str,
    private_key_pem: str,
    ws_url: str = None,
    leagues: List[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch basketball markets for specified leagues (currently NBA).
    
    Uses series_ticker filtering for efficient API calls when possible.
    
    Args:
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL
        leagues: List of leagues to filter (e.g., ["nba"])
                 If None, fetches all available basketball leagues.
        
    Returns:
        List of basketball market dictionaries with market details and odds
    """
    if leagues is None:
        leagues = ["nba"]
    
    basketball_markets = []
    seen_tickers = set()  # Avoid duplicates across series
    
    # Try to fetch using series_ticker for each league (fast path)
    for league in leagues:
        series_tickers = BASKETBALL_SERIES_TICKERS.get(league, [])
        # Handle both list and legacy string format
        if isinstance(series_tickers, str):
            series_tickers = [series_tickers]
        
        for series_ticker in series_tickers:
            logger.info(f"Fetching {league} basketball markets using series_ticker: {series_ticker}")
            cursor = None
            
            while True:
                result = get_markets(
                    key_id=key_id,
                    private_key_pem=private_key_pem,
                    ws_url=ws_url,
                    status="open",
                    limit=100,
                    cursor=cursor,
                    series_ticker=series_ticker,
                )
                
                markets = result.get("markets", [])
                if not markets:
                    break
                
                for market in markets:
                    ticker = market.get("ticker")
                    if ticker and ticker not in seen_tickers:
                        seen_tickers.add(ticker)
                        basketball_markets.append(_format_basketball_market(market, league))
                
                cursor = result.get("cursor")
                if not cursor:
                    break
    
    # If no markets found via series_ticker, try event-based search
    if not basketball_markets:
        logger.info("No basketball markets via series_ticker, trying event search...")
        basketball_markets = _search_basketball_markets_fallback(
            key_id, private_key_pem, ws_url, leagues
        )
    
    logger.info(f"Found {len(basketball_markets)} basketball markets for leagues: {leagues}")
    return basketball_markets


def _format_basketball_market(market: Dict[str, Any], league: str) -> Dict[str, Any]:
    """Format a market dict for basketball analysis."""
    ticker = market.get("ticker", "").upper()
    title = market.get("title", "").upper()
    subtitle = market.get("subtitle", "").upper()
    series_ticker = market.get("series_ticker", "").upper()
    combined_text = f"{ticker} {title} {subtitle}"
    
    # Determine market type based on series ticker first (most reliable)
    market_type = "unknown"
    if "SPREAD" in series_ticker or "SPREAD" in ticker:
        # Point spread markets
        market_type = "spread"
    elif "TOTAL" in series_ticker or "TOTAL" in ticker:
        # Total points (over/under)
        market_type = "total"
    elif "OVER" in combined_text and ("POINTS" in combined_text or "SCORED" in combined_text):
        # Total points pattern
        market_type = "total"
    elif "BY OVER" in combined_text or "BY MORE THAN" in combined_text:
        # Spread pattern: "Team wins by over X points"
        market_type = "spread"
    elif any(t in combined_text for t in ["WINNER", "MONEYLINE", "TO WIN", "WINS"]):
        market_type = "winner"
    elif "GAME" in series_ticker:
        # Default for KXNBAGAME series is winner/moneyline
        market_type = "winner"
    
    return {
        "ticker": market.get("ticker"),
        "title": market.get("title"),
        "subtitle": market.get("subtitle"),
        "yes_bid": market.get("yes_bid"),
        "yes_ask": market.get("yes_ask"),
        "no_bid": market.get("no_bid"),
        "no_ask": market.get("no_ask"),
        "last_price": market.get("last_price"),
        "volume": market.get("volume"),
        "open_interest": market.get("open_interest"),
        "close_time": market.get("close_time"),
        "expiration_time": market.get("expiration_time"),
        "market_type": market_type,
        "league": league,
        "yes_sub_title": market.get("yes_sub_title"),
        "no_sub_title": market.get("no_sub_title"),
        "event_ticker": market.get("event_ticker"),
        "series_ticker": market.get("series_ticker"),
    }


def _search_basketball_markets_fallback(
    key_id: str,
    private_key_pem: str,
    ws_url: str,
    leagues: List[str],
) -> List[Dict[str, Any]]:
    """
    Fallback: Search for basketball markets by scanning events.
    
    This is slower but more reliable if series_tickers change.
    """
    basketball_markets = []
    
    # Build search terms
    search_terms = ["BASKETBALL", "NBA"]
    for league in leagues:
        if league in BASKETBALL_SEARCH_TERMS:
            search_terms.extend(BASKETBALL_SEARCH_TERMS[league])
    
    # Fetch events and look for basketball
    cursor = None
    checked_events = set()
    
    while True:
        result = get_events(
            key_id=key_id,
            private_key_pem=private_key_pem,
            ws_url=ws_url,
            status="open",
            limit=100,
            cursor=cursor,
        )
        
        events = result.get("events", [])
        if not events:
            break
        
        for event in events:
            event_ticker = event.get("event_ticker", "")
            if event_ticker in checked_events:
                continue
            checked_events.add(event_ticker)
            
            title = event.get("title", "").upper()
            category = event.get("category", "").upper()
            combined = f"{event_ticker} {title} {category}"
            
            # Check if this is a basketball event
            if any(term in combined.upper() for term in search_terms):
                # Determine league
                detected_league = "unknown"
                for league_name, terms in BASKETBALL_SEARCH_TERMS.items():
                    if league_name in leagues and any(t in combined for t in terms):
                        detected_league = league_name
                        break
                
                if detected_league == "unknown":
                    # Default to NBA if we found basketball keywords
                    if "nba" in leagues:
                        detected_league = "nba"
                    else:
                        continue
                
                # Fetch markets for this event
                market_result = get_markets(
                    key_id=key_id,
                    private_key_pem=private_key_pem,
                    ws_url=ws_url,
                    status="open",
                    event_ticker=event_ticker,
                    limit=50,
                )
                
                for market in market_result.get("markets", []):
                    basketball_markets.append(_format_basketball_market(market, detected_league))
        
        cursor = result.get("cursor")
        if not cursor:
            break
    
    return basketball_markets


def format_basketball_markets_for_analysis(markets: List[Dict[str, Any]]) -> str:
    """
    Format basketball markets into a readable string for LLM analysis.
    
    Args:
        markets: List of basketball market dictionaries
        
    Returns:
        Formatted string describing the markets and their odds
    """
    if not markets:
        return "No basketball markets found for the specified leagues."
    
    # Group markets by league and then by game
    from collections import defaultdict
    by_league = defaultdict(list)
    
    for market in markets:
        league = market.get("league", "unknown")
        by_league[league].append(market)
    
    output = []
    
    for league, league_markets in by_league.items():
        league_display = league.upper()
        output.append(f"\n{'='*50}")
        output.append(f"  {league_display}")
        output.append(f"{'='*50}\n")
        
        # Group by event/game
        by_event = defaultdict(list)
        for market in league_markets:
            event = market.get("event_ticker") or market.get("title", "Unknown")
            by_event[event].append(market)
        
        for event, event_markets in by_event.items():
            # Get the main game title
            main_title = event_markets[0].get("title", event)
            output.append(f"\n🏀 {main_title}")
            output.append("-" * 40)
            
            for market in event_markets:
                ticker = market.get("ticker", "N/A")
                market_type = market.get("market_type", "unknown")
                yes_bid = market.get("yes_bid")
                yes_ask = market.get("yes_ask")
                yes_sub = market.get("yes_sub_title", "YES")
                no_sub = market.get("no_sub_title", "NO")
                
                # Format odds
                if yes_bid and yes_ask:
                    yes_mid = (yes_bid + yes_ask) / 2
                    no_mid = 100 - yes_mid
                    output.append(f"  [{market_type.upper()}] {ticker}")
                    output.append(f"    {yes_sub}: {yes_mid:.0f}¢ (bid: {yes_bid}¢, ask: {yes_ask}¢)")
                    output.append(f"    {no_sub}: {no_mid:.0f}¢")
                else:
                    last_price = market.get("last_price", "N/A")
                    output.append(f"  [{market_type.upper()}] {ticker}")
                    output.append(f"    Last Price: {last_price}¢")
                
                output.append("")
    
    return "\n".join(output)


# =============================================================================
# SHARED UTILITY FUNCTIONS
# =============================================================================

def group_markets_by_match(markets: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Group markets by match/game (works for both soccer and basketball).
    
    Extracts match identifier from ticker (e.g., KXLALIGAGAME-25DEC08OSALEV-TIE -> 25DEC08OSALEV)
    and groups all markets for the same match together.
    
    Args:
        markets: List of market dictionaries (soccer or basketball)
        
    Returns:
        Dictionary mapping match_id to match data:
        {
            "25DEC08OSALEV": {
                "match_id": "25DEC08OSALEV",
                "title": "Match title from first market",
                "league": "la_liga",
                "markets": [list of market dicts],
            }
        }
    """
    matches = {}
    
    for market in markets:
        ticker = market.get("ticker", "")
        parts = ticker.split("-")
        
        # Extract match identifier (second part of ticker)
        # e.g., KXLALIGAGAME-25DEC08OSALEV-TIE -> 25DEC08OSALEV
        # e.g., KXNBAGAME-25DEC06NOPBKN -> 25DEC06NOPBKN
        if len(parts) >= 2:
            match_id = parts[1]
        else:
            # Fallback to event_ticker or full ticker
            match_id = market.get("event_ticker") or ticker
        
        if match_id not in matches:
            # Extract a clean title - try to get team names from title
            title = market.get("title", "Unknown Match")
            
            matches[match_id] = {
                "match_id": match_id,
                "title": title,
                "league": market.get("league", "unknown"),
                "markets": [],
            }
        
        matches[match_id]["markets"].append(market)
    
    return matches

