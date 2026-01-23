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
        "KXNBACUP",       # Cup markets
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


# Cricket series tickers on Kalshi
# T20 International matches and other cricket formats
CRICKET_SERIES_TICKERS = {
    "t20_international": [
        "KXCRICKETT20IMATCH",    # T20 International match winner
    ],
    "ipl": [
        "KXCRICKETIPLMATCH",     # IPL match winner (if available)
    ],
}

# Ticker prefixes for cricket searching
CRICKET_TICKER_PREFIXES = {
    "t20_international": ["KXCRICKETT20I", "CRICKET", "T20"],
    "ipl": ["KXCRICKETIPL", "IPL"],
}

# Fallback search terms for cricket
CRICKET_SEARCH_TERMS = {
    "t20_international": ["T20 INTERNATIONAL", "T20I", "CRICKET"],
    "ipl": ["IPL", "INDIAN PREMIER LEAGUE"],
}

# Cricket market types
CRICKET_MARKET_TYPES = ["winner", "match_winner"]


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
                
                # Format odds - use `is not None` to handle 0 as valid price
                if yes_bid is not None and yes_ask is not None:
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
# CRICKET MARKET FUNCTIONS
# =============================================================================

def get_cricket_markets(
    key_id: str,
    private_key_pem: str,
    ws_url: str = None,
    leagues: List[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch cricket markets for specified leagues/competitions.
    
    Uses series_ticker filtering for efficient API calls when possible.
    
    Args:
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL
        leagues: List of leagues to filter (e.g., ["t20_international", "ipl"])
                 If None, fetches all available cricket leagues.
        
    Returns:
        List of cricket market dictionaries with market details and odds
    """
    if leagues is None:
        leagues = ["t20_international", "ipl"]
    
    cricket_markets = []
    seen_tickers = set()  # Avoid duplicates across series
    
    # Try to fetch using series_ticker for each league (fast path)
    for league in leagues:
        series_tickers = CRICKET_SERIES_TICKERS.get(league, [])
        # Handle both list and legacy string format
        if isinstance(series_tickers, str):
            series_tickers = [series_tickers]
        
        for series_ticker in series_tickers:
            logger.info(f"Fetching {league} cricket markets using series_ticker: {series_ticker}")
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
                        cricket_markets.append(_format_cricket_market(market, league))
                
                cursor = result.get("cursor")
                if not cursor:
                    break
    
    # If no markets found via series_ticker, try event-based search
    if not cricket_markets:
        logger.info("No cricket markets via series_ticker, trying event search...")
        cricket_markets = _search_cricket_markets_fallback(
            key_id, private_key_pem, ws_url, leagues
        )
    
    logger.info(f"Found {len(cricket_markets)} cricket markets for leagues: {leagues}")
    return cricket_markets


def _format_cricket_market(market: Dict[str, Any], league: str) -> Dict[str, Any]:
    """Format a market dict for cricket analysis."""
    ticker = market.get("ticker", "").upper()
    title = market.get("title", "").upper()
    subtitle = market.get("subtitle", "").upper()
    series_ticker = market.get("series_ticker", "").upper()
    combined_text = f"{ticker} {title} {subtitle}"
    
    # Determine market type based on series ticker first (most reliable)
    market_type = "unknown"
    if "MATCH" in series_ticker or "WINNER" in combined_text:
        # Match winner markets
        market_type = "winner"
    elif any(t in combined_text for t in ["WINNER", "TO WIN", "WINS"]):
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


def _search_cricket_markets_fallback(
    key_id: str,
    private_key_pem: str,
    ws_url: str,
    leagues: List[str],
) -> List[Dict[str, Any]]:
    """
    Fallback: Search for cricket markets by scanning events.
    
    This is slower but more reliable if series_tickers change.
    """
    cricket_markets = []
    
    # Build search terms
    search_terms = ["CRICKET", "T20", "IPL"]
    for league in leagues:
        if league in CRICKET_SEARCH_TERMS:
            search_terms.extend(CRICKET_SEARCH_TERMS[league])
    
    # Fetch events and look for cricket
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
            
            # Check if this is a cricket event
            if any(term in combined.upper() for term in search_terms):
                # Determine league
                detected_league = "unknown"
                for league_name, terms in CRICKET_SEARCH_TERMS.items():
                    if league_name in leagues and any(t in combined for t in terms):
                        detected_league = league_name
                        break
                
                if detected_league == "unknown":
                    # Default to t20_international if we found cricket keywords
                    if "t20_international" in leagues:
                        detected_league = "t20_international"
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
                    cricket_markets.append(_format_cricket_market(market, detected_league))
        
        cursor = result.get("cursor")
        if not cursor:
            break
    
    return cricket_markets


def format_cricket_markets_for_analysis(markets: List[Dict[str, Any]]) -> str:
    """
    Format cricket markets into a readable string for LLM analysis.
    
    Args:
        markets: List of cricket market dictionaries
        
    Returns:
        Formatted string describing the markets and their odds
    """
    if not markets:
        return "No cricket markets found for the specified leagues."
    
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
        output.append(f"  🏏 {league_display}")
        output.append(f"{'='*50}\n")
        
        # Group by event/match
        by_event = defaultdict(list)
        for market in league_markets:
            event = market.get("event_ticker") or market.get("title", "Unknown")
            by_event[event].append(market)
        
        for event, event_markets in by_event.items():
            # Get the main match title
            main_title = event_markets[0].get("title", event)
            output.append(f"\n🏏 {main_title}")
            output.append("-" * 40)
            
            for market in event_markets:
                ticker = market.get("ticker", "N/A")
                market_type = market.get("market_type", "unknown")
                yes_bid = market.get("yes_bid")
                yes_ask = market.get("yes_ask")
                yes_sub = market.get("yes_sub_title", "YES")
                no_sub = market.get("no_sub_title", "NO")
                
                # Format odds - use `is not None` to handle 0 as valid price
                if yes_bid is not None and yes_ask is not None:
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


def _parse_strike_from_ticker(ticker: str) -> Optional[float]:
    """
    Parse the strike value from a Kalshi ticker.
    
    Examples:
        KXNBASPREAD-25DEC23WASCHA-CHA5 -> 5.5 (Charlotte wins by over 5.5)
        KXNBATOTAL-25DEC23WASCHA-237 -> 237.5 (Over 237.5 points)
        KXNBAGAME-25DEC23WASCHA-WAS -> None (winner market, no strike)
    
    Returns:
        Strike value as float, or None if not applicable
    """
    import re
    parts = ticker.split("-")
    if len(parts) < 3:
        return None
    
    suffix = parts[-1]
    
    # For spread markets like CHA5, WAS7, extract the number
    # For total markets like 237, 249, extract the number
    match = re.search(r'(\d+)$', suffix)
    if match:
        base_value = int(match.group(1))
        # Kalshi uses whole numbers in tickers, but spreads/totals are typically .5
        return base_value + 0.5
    
    return None


def _parse_team_direction_from_ticker(ticker: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parse the team abbreviation and direction from a Kalshi ticker.
    
    Examples:
        KXNBASPREAD-25DEC23WASCHA-CHA5 -> ("CHA", "spread")
        KXNBATOTAL-25DEC23WASCHA-237 -> (None, "over")
        KXNBAGAME-25DEC23WASCHA-WAS -> ("WAS", "winner")
    
    Returns:
        Tuple of (team_abbrev or None, direction/type)
    """
    import re
    parts = ticker.split("-")
    if len(parts) < 3:
        return None, None
    
    suffix = parts[-1]
    series = parts[0] if parts else ""
    
    if "SPREAD" in series:
        # Extract team abbreviation before the number
        match = re.match(r'([A-Z]+)(\d+)?$', suffix)
        if match:
            return match.group(1), "spread"
    elif "TOTAL" in series:
        # Total markets don't have team, just "over X"
        return None, "over"
    elif "GAME" in series:
        # Winner markets have team abbreviation
        return suffix, "winner"
    
    return None, None


def format_basketball_markets_for_kalshi_trading(markets: List[Dict[str, Any]]) -> str:
    """
    Format basketball markets for Kalshi-native trading decisions.
    
    This formatter provides complete bid/ask data for both YES and NO sides,
    volume/liquidity info, and parsed strike values so the LLM can:
    - Compare specific contracts and strikes
    - Calculate EV using actual bid/ask (not mid-prices)
    - Identify liquid vs illiquid markets
    - Choose the better side (YES or NO) based on pricing
    
    Args:
        markets: List of basketball market dictionaries
        
    Returns:
        Formatted string with full Kalshi contract details
    """
    if not markets:
        return "No basketball markets found for the specified leagues."
    
    from collections import defaultdict
    by_league = defaultdict(list)
    
    for market in markets:
        league = market.get("league", "unknown")
        by_league[league].append(market)
    
    output = []
    output.append("=" * 70)
    output.append("KALSHI NBA MARKET BOARD - TRADEABLE CONTRACTS")
    output.append("=" * 70)
    output.append("")
    output.append("PRICING GUIDE:")
    output.append("  • To BUY YES: pay the 'yes_ask' price")
    output.append("  • To BUY NO: pay the 'no_ask' price (or equivalently, SELL YES at 'yes_bid')")
    output.append("  • Spread = ask - bid (tighter is better, >10¢ = illiquid)")
    output.append("  • EV = (model_prob × 100) - price_paid")
    output.append("")
    
    for league, league_markets in by_league.items():
        league_display = league.upper()
        output.append(f"\n{'='*70}")
        output.append(f"  {league_display}")
        output.append(f"{'='*70}")
        
        # Group by event/game
        by_event = defaultdict(list)
        for market in league_markets:
            event = market.get("event_ticker") or market.get("title", "Unknown")
            by_event[event].append(market)
        
        for event, event_markets in by_event.items():
            # Get the main game title
            main_title = event_markets[0].get("title", event)
            output.append(f"\n🏀 {main_title}")
            output.append("-" * 70)
            
            # Sort markets by type for better organization
            winner_markets = [m for m in event_markets if m.get("market_type") == "winner"]
            spread_markets = [m for m in event_markets if m.get("market_type") == "spread"]
            total_markets = [m for m in event_markets if m.get("market_type") == "total"]
            other_markets = [m for m in event_markets if m.get("market_type") not in ("winner", "spread", "total")]
            
            # Output each category
            for category_name, category_markets in [
                ("WINNER/MONEYLINE", winner_markets),
                ("SPREAD", spread_markets),
                ("TOTAL (OVER/UNDER)", total_markets),
                ("OTHER", other_markets),
            ]:
                if not category_markets:
                    continue
                    
                output.append(f"\n  [{category_name}]")
                
                for market in category_markets:
                    ticker = market.get("ticker", "N/A")
                    yes_bid = market.get("yes_bid")
                    yes_ask = market.get("yes_ask")
                    no_bid = market.get("no_bid")
                    no_ask = market.get("no_ask")
                    volume = market.get("volume", 0) or 0
                    open_interest = market.get("open_interest", 0) or 0
                    yes_sub = market.get("yes_sub_title", "YES")
                    no_sub = market.get("no_sub_title", "NO")
                    
                    # Parse strike from ticker
                    strike = _parse_strike_from_ticker(ticker)
                    team_abbrev, direction = _parse_team_direction_from_ticker(ticker)
                    
                    output.append(f"  ┌─ Ticker: {ticker}")
                    
                    # Show the question/statement being bet on
                    if yes_sub and yes_sub != "YES":
                        output.append(f"  │  Question: {yes_sub}?")
                    if strike is not None:
                        output.append(f"  │  Strike: {strike}")
                    if team_abbrev:
                        output.append(f"  │  Team: {team_abbrev}")
                    
                    # YES side pricing
                    if yes_bid is not None and yes_ask is not None:
                        yes_spread = yes_ask - yes_bid
                        liquidity_flag = "⚠️ WIDE" if yes_spread > 10 else "✓"
                        output.append(f"  │  YES: bid={yes_bid}¢, ask={yes_ask}¢ (spread={yes_spread}¢) {liquidity_flag}")
                    elif yes_bid is not None:
                        output.append(f"  │  YES: bid={yes_bid}¢, ask=N/A")
                    elif yes_ask is not None:
                        output.append(f"  │  YES: bid=N/A, ask={yes_ask}¢")
                    else:
                        last_price = market.get("last_price")
                        if last_price is not None:
                            output.append(f"  │  YES: last_price={last_price}¢ (no live quotes)")
                        else:
                            output.append(f"  │  YES: no pricing available")
                    
                    # NO side pricing
                    if no_bid is not None and no_ask is not None:
                        no_spread = no_ask - no_bid
                        liquidity_flag = "⚠️ WIDE" if no_spread > 10 else "✓"
                        output.append(f"  │  NO:  bid={no_bid}¢, ask={no_ask}¢ (spread={no_spread}¢) {liquidity_flag}")
                    elif no_bid is not None:
                        output.append(f"  │  NO:  bid={no_bid}¢, ask=N/A")
                    elif no_ask is not None:
                        output.append(f"  │  NO:  bid=N/A, ask={no_ask}¢")
                    else:
                        # Calculate NO from YES if available
                        if yes_bid is not None and yes_ask is not None:
                            implied_no_bid = 100 - yes_ask
                            implied_no_ask = 100 - yes_bid
                            output.append(f"  │  NO:  (implied from YES) bid≈{implied_no_bid}¢, ask≈{implied_no_ask}¢")
                        else:
                            output.append(f"  │  NO:  no pricing available")
                    
                    # Liquidity info
                    output.append(f"  │  Volume: {volume} contracts | Open Interest: {open_interest}")
                    output.append(f"  └─")
                    output.append("")
    
    output.append("")
    output.append("=" * 70)
    output.append("END OF MARKET BOARD")
    output.append("=" * 70)
    
    return "\n".join(output)


# =============================================================================
# TOTALS FILTERING FOR DEEP RESEARCH
# =============================================================================

def select_total_extremes(markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter markets to TOTAL type only and keep only extreme strikes (min + max).
    
    For NBA combo research, we only want the lowest and highest strike totals
    for each game to focus on the "far left" and "far right" of the spread.
    
    Args:
        markets: List of market dictionaries for a single game
        
    Returns:
        List containing at most 2 markets: the lowest and highest strike totals
    """
    # Filter to totals only
    totals = [m for m in markets if m.get("market_type") == "total"]
    
    if not totals:
        return []
    
    # Parse strikes and pair with markets
    markets_with_strikes = []
    for market in totals:
        ticker = market.get("ticker", "")
        strike = _parse_strike_from_ticker(ticker)
        if strike is not None:
            markets_with_strikes.append((strike, market))
    
    # If no strikes could be parsed, fall back to returning first 1-2 totals
    if not markets_with_strikes:
        return totals[:2]
    
    # Sort by strike
    markets_with_strikes.sort(key=lambda x: x[0])
    
    # Get min and max strike markets
    result = []
    
    # Min strike (lowest total line)
    result.append(markets_with_strikes[0][1])
    
    # Max strike (highest total line) - only add if different from min
    if len(markets_with_strikes) > 1:
        max_market = markets_with_strikes[-1][1]
        if max_market["ticker"] != result[0]["ticker"]:
            result.append(max_market)
    
    return result


# =============================================================================
# SPREAD EXTREMES FOR ALTERNATIVE ANALYSIS
# =============================================================================

def implied_yes_prob(market: Dict[str, Any]) -> Optional[float]:
    """
    Compute implied YES probability from market bid/ask or last_price.
    
    Priority:
      1. Midpoint of yes_bid and yes_ask (if both exist)
      2. Fallback to last_price
    
    Args:
        market: Market dictionary with pricing fields
        
    Returns:
        Implied YES probability as a float (0-100 scale), or None if unavailable
    """
    yes_bid = market.get("yes_bid")
    yes_ask = market.get("yes_ask")
    
    if yes_bid is not None and yes_ask is not None:
        return (yes_bid + yes_ask) / 2.0
    
    # Fallback to last_price
    last_price = market.get("last_price")
    if last_price is not None:
        return float(last_price)
    
    return None


def select_spread_extremes(markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter markets to SPREAD type only and keep the tail markets (max strike per team).
    
    For alternative spread analysis, we want the "blowout tails" - the highest
    strike spread market for each team. E.g., "Team A wins by >10.5" and
    "Team B wins by >8.5" are the two tails.
    
    Args:
        markets: List of market dictionaries for a single game
        
    Returns:
        List containing at most 2 markets: max strike for each team (the tails)
    """
    # Filter to spreads only
    spreads = [m for m in markets if m.get("market_type") == "spread"]
    
    if not spreads:
        return []
    
    # Parse team + strike and group by team
    # Structure: { team_abbrev: [(strike, market), ...] }
    by_team: Dict[str, List[tuple]] = {}
    
    for market in spreads:
        ticker = market.get("ticker", "")
        team_abbrev, direction = _parse_team_direction_from_ticker(ticker)
        strike = _parse_strike_from_ticker(ticker)
        
        if team_abbrev and strike is not None:
            if team_abbrev not in by_team:
                by_team[team_abbrev] = []
            by_team[team_abbrev].append((strike, market))
    
    # If no teams could be parsed, fall back to returning first 1-2 spreads
    if not by_team:
        return spreads[:2]
    
    # For each team, pick the max strike (the "tail" / blowout market)
    result = []
    for team_abbrev, strike_markets in by_team.items():
        # Sort by strike descending and pick the max
        strike_markets.sort(key=lambda x: x[0], reverse=True)
        max_strike_market = strike_markets[0][1]
        result.append(max_strike_market)
    
    return result


def pick_higher_prob_spread_extreme(
    extremes: List[Dict[str, Any]]
) -> tuple[Optional[Dict[str, Any]], Optional[float]]:
    """
    Given a list of spread extreme markets (tails), pick the one with higher implied YES probability.
    
    Args:
        extremes: List of spread tail markets (typically 2, one per team)
        
    Returns:
        Tuple of (chosen_market, implied_yes_prob) or (None, None) if no valid prices
    """
    if not extremes:
        return None, None
    
    best_market = None
    best_prob = None
    
    for market in extremes:
        prob = implied_yes_prob(market)
        if prob is not None:
            if best_prob is None or prob > best_prob:
                best_prob = prob
                best_market = market
    
    return best_market, best_prob


def compute_spread_combo_analysis(
    games_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compute alternative spread combo analysis for multiple games.
    
    For each game:
      - Select the spread extremes (max strike per team = tails)
      - Pick the tail with higher implied YES probability
    
    Then compute combined implied probability across all games.
    
    Args:
        games_data: List of game dicts, each with "markets" key containing market list
        
    Returns:
        {
            "games": [
                {
                    "title": str,
                    "tails": [market1, market2],  # the two tail markets
                    "tail_probs": [prob1, prob2],  # implied YES prob for each tail
                    "chosen_market": market,  # the higher-prob tail
                    "chosen_prob": float,  # its probability
                },
                ...
            ],
            "combined_prob": float,  # product of chosen probs (as decimal 0-1)
            "combined_prob_pct": float,  # as percentage
            "implied_fair_price_cents": float,  # combined_prob * 100
            "games_included": int,  # number of games with valid prices
        }
    """
    result_games = []
    probs_for_combo = []
    
    for game in games_data:
        title = game.get("title", "Unknown Game")
        markets = game.get("markets", [])
        
        # Get spread extremes (tails)
        tails = select_spread_extremes(markets)
        
        # Compute implied prob for each tail
        tail_probs = []
        for tail in tails:
            prob = implied_yes_prob(tail)
            tail_probs.append(prob)
        
        # Pick higher-prob tail
        chosen_market, chosen_prob = pick_higher_prob_spread_extreme(tails)
        
        game_result = {
            "title": title,
            "tails": tails,
            "tail_probs": tail_probs,
            "chosen_market": chosen_market,
            "chosen_prob": chosen_prob,
        }
        result_games.append(game_result)
        
        # Add to combo if valid
        if chosen_prob is not None:
            probs_for_combo.append(chosen_prob / 100.0)  # convert to decimal
    
    # Compute combined probability
    if probs_for_combo:
        combined_prob = 1.0
        for p in probs_for_combo:
            combined_prob *= p
        combined_prob_pct = combined_prob * 100
        implied_fair_price = combined_prob_pct  # in cents
    else:
        combined_prob = None
        combined_prob_pct = None
        implied_fair_price = None
    
    return {
        "games": result_games,
        "combined_prob": combined_prob,
        "combined_prob_pct": combined_prob_pct,
        "implied_fair_price_cents": implied_fair_price,
        "games_included": len(probs_for_combo),
    }


def format_totals_for_deep_research(
    markets: List[Dict[str, Any]],
    games_metadata: List[Dict[str, Any]],
) -> str:
    """
    Format filtered TOTAL markets for Gemini Deep Research prompt.
    
    Provides a clean, structured view of the extreme strike totals
    for each selected game in the combo.
    
    Args:
        markets: List of filtered total market dictionaries (extreme strikes only)
        games_metadata: List of game metadata dicts with title, date, teams, filtered_markets
        
    Returns:
        Formatted string for Deep Research input
    """
    output = []
    output.append("=" * 70)
    output.append("KALSHI NBA TOTALS - EXTREME STRIKES ONLY")
    output.append("=" * 70)
    output.append("")
    output.append("MARKET GUIDE:")
    output.append("  • These are TOTAL (Over/Under) markets only")
    output.append("  • Showing lowest and highest strike for each game")
    output.append("  • YES = Over the strike | NO = Under the strike")
    output.append("  • Prices in cents (e.g., 45¢ = 45% implied probability)")
    output.append("")
    
    for game in games_metadata:
        title = game.get("title", "Unknown")
        date = game.get("date")
        date_str = date.strftime("%B %d, %Y") if date else "TBD"
        away_team = game.get("away_team", "Away")
        home_team = game.get("home_team", "Home")
        filtered_markets = game.get("filtered_markets", [])
        
        output.append(f"\n{'='*70}")
        output.append(f"🏀 {title}")
        output.append(f"   Date: {date_str}")
        output.append(f"   {away_team} @ {home_team}")
        output.append("-" * 70)
        
        if not filtered_markets:
            output.append("  No total markets available for this game")
            continue
        
        for market in filtered_markets:
            ticker = market.get("ticker", "N/A")
            strike = _parse_strike_from_ticker(ticker)
            yes_bid = market.get("yes_bid")
            yes_ask = market.get("yes_ask")
            yes_sub = market.get("yes_sub_title", "Over")
            no_sub = market.get("no_sub_title", "Under")
            volume = market.get("volume", 0) or 0
            
            output.append(f"\n  Ticker: {ticker}")
            if strike is not None:
                output.append(f"  Strike: {strike} total points")
            
            # YES side (Over)
            if yes_bid is not None and yes_ask is not None:
                yes_mid = (yes_bid + yes_ask) / 2
                output.append(f"  OVER {strike if strike else 'N/A'}:")
                output.append(f"    Bid: {yes_bid}¢ | Ask: {yes_ask}¢ | Mid: {yes_mid:.0f}¢")
            elif yes_bid is not None:
                output.append(f"  OVER: Bid {yes_bid}¢")
            elif yes_ask is not None:
                output.append(f"  OVER: Ask {yes_ask}¢")
            else:
                last_price = market.get("last_price")
                if last_price is not None:
                    output.append(f"  OVER: Last price {last_price}¢")
            
            # UNDER (implied from YES)
            if yes_bid is not None and yes_ask is not None:
                under_mid = 100 - yes_mid
                output.append(f"  UNDER {strike if strike else 'N/A'}:")
                output.append(f"    Implied mid: {under_mid:.0f}¢")
            
            output.append(f"  Volume: {volume} contracts")
        
        output.append("")
    
    output.append("=" * 70)
    output.append("END OF TOTALS BOARD")
    output.append("=" * 70)
    
    return "\n".join(output)


def format_combined_extremes_for_deep_research(
    games_metadata: List[Dict[str, Any]],
) -> str:
    """
    Format both TOTAL and SPREAD extreme markets for Gemini Deep Research prompt.
    
    For each game, includes:
      - Total extremes: lowest and highest strike (over/under)
      - Spread extremes: max strike per team (blowout tails)
    
    The LLM will analyze both and recommend which market type to play per game.
    
    Args:
        games_metadata: List of game metadata dicts with:
            - title, date, away_team, home_team
            - total_extremes: list of extreme total markets
            - spread_extremes: list of extreme spread markets
        
    Returns:
        Formatted string for Deep Research input
    """
    output = []
    output.append("=" * 70)
    output.append("KALSHI NBA MARKETS - TOTALS & SPREADS EXTREMES")
    output.append("=" * 70)
    output.append("")
    output.append("MARKET GUIDE:")
    output.append("  • TOTALS: Over/Under on combined points scored")
    output.append("    - Showing lowest and highest strike for each game")
    output.append("    - YES = Over the strike | NO = Under the strike")
    output.append("  • SPREADS: Team wins by more than X points (blowout markets)")
    output.append("    - Showing highest strike per team (the 'blowout tails')")
    output.append("    - YES = Team wins by more than X | NO = They don't")
    output.append("  • Prices in cents (e.g., 45¢ = 45% implied probability)")
    output.append("")
    output.append("YOUR TASK: For each game, analyze BOTH totals and spreads,")
    output.append("then recommend whether to play TOTAL or SPREAD for that game.")
    output.append("")
    
    for game in games_metadata:
        title = game.get("title", "Unknown")
        date = game.get("date")
        date_str = date.strftime("%B %d, %Y") if date else "TBD"
        away_team = game.get("away_team", "Away")
        home_team = game.get("home_team", "Home")
        total_extremes = game.get("total_extremes", [])
        spread_extremes = game.get("spread_extremes", [])
        
        output.append(f"\n{'='*70}")
        output.append(f"🏀 {title}")
        output.append(f"   Date: {date_str}")
        output.append(f"   {away_team} @ {home_team}")
        output.append("=" * 70)
        
        # --- TOTALS SECTION ---
        output.append("\n  ┌─ TOTAL MARKETS (Over/Under) ─────────────────────────────────────")
        
        if not total_extremes:
            output.append("  │  No total markets available for this game")
        else:
            for market in total_extremes:
                ticker = market.get("ticker", "N/A")
                strike = _parse_strike_from_ticker(ticker)
                yes_bid = market.get("yes_bid")
                yes_ask = market.get("yes_ask")
                volume = market.get("volume", 0) or 0
                
                output.append(f"  │")
                output.append(f"  │  Ticker: {ticker}")
                if strike is not None:
                    output.append(f"  │  Strike: {strike} total points")
                
                if yes_bid is not None and yes_ask is not None:
                    yes_mid = (yes_bid + yes_ask) / 2
                    under_mid = 100 - yes_mid
                    output.append(f"  │  OVER:  Bid {yes_bid}¢ | Ask {yes_ask}¢ | Mid {yes_mid:.0f}¢")
                    output.append(f"  │  UNDER: Implied mid {under_mid:.0f}¢")
                elif yes_bid is not None:
                    output.append(f"  │  OVER: Bid {yes_bid}¢")
                elif yes_ask is not None:
                    output.append(f"  │  OVER: Ask {yes_ask}¢")
                else:
                    last_price = market.get("last_price")
                    if last_price is not None:
                        output.append(f"  │  OVER: Last price {last_price}¢")
                
                output.append(f"  │  Volume: {volume} contracts")
        
        output.append("  └────────────────────────────────────────────────────────────────────")
        
        # --- SPREADS SECTION ---
        output.append("\n  ┌─ SPREAD MARKETS (Blowout Tails) ────────────────────────────────")
        
        if not spread_extremes:
            output.append("  │  No spread markets available for this game")
        else:
            for market in spread_extremes:
                ticker = market.get("ticker", "N/A")
                strike = _parse_strike_from_ticker(ticker)
                team_abbrev, _ = _parse_team_direction_from_ticker(ticker)
                yes_bid = market.get("yes_bid")
                yes_ask = market.get("yes_ask")
                yes_sub = market.get("yes_sub_title", f"{team_abbrev} wins by >{strike}")
                volume = market.get("volume", 0) or 0
                
                output.append(f"  │")
                output.append(f"  │  Ticker: {ticker}")
                output.append(f"  │  {team_abbrev} wins by more than {strike} points")
                
                if yes_bid is not None and yes_ask is not None:
                    yes_mid = (yes_bid + yes_ask) / 2
                    no_mid = 100 - yes_mid
                    output.append(f"  │  YES (blowout):  Bid {yes_bid}¢ | Ask {yes_ask}¢ | Mid {yes_mid:.0f}¢")
                    output.append(f"  │  NO  (no blowout): Implied mid {no_mid:.0f}¢")
                elif yes_bid is not None:
                    output.append(f"  │  YES: Bid {yes_bid}¢")
                elif yes_ask is not None:
                    output.append(f"  │  YES: Ask {yes_ask}¢")
                else:
                    last_price = market.get("last_price")
                    if last_price is not None:
                        output.append(f"  │  YES: Last price {last_price}¢")
                
                output.append(f"  │  Volume: {volume} contracts")
        
        output.append("  └────────────────────────────────────────────────────────────────────")
        output.append("")
    
    output.append("=" * 70)
    output.append("END OF MARKETS BOARD")
    output.append("=" * 70)
    
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


# =============================================================================
# LIVE DASHBOARD API FUNCTIONS
# =============================================================================

def get_orderbook(
    ticker: str,
    key_id: str,
    private_key_pem: str,
    ws_url: str = None,
    depth: int = 0,
) -> Dict[str, Any]:
    """
    Fetch orderbook for a specific market.
    
    Args:
        ticker: Market ticker symbol
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL (demo vs production)
        depth: Number of price levels to return (0 or negative = full book)
        
    Returns:
        Orderbook dictionary with 'yes' and 'no' arrays of [price, quantity] pairs
    """
    if ws_url and "demo" in ws_url:
        base_url = "https://demo-api.kalshi.co"
    else:
        base_url = "https://api.elections.kalshi.com"
    
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    
    # Add depth parameter if specified
    params = {}
    if depth != 0:
        params["depth"] = depth
    
    if params:
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        full_path = f"{path}?{query_string}"
    else:
        full_path = path
    
    url = base_url + full_path
    
    try:
        timestamp_ms = str(int(time.time() * 1000))
        signature = sign_request(private_key_pem, timestamp_ms, "GET", full_path)
        
        headers = {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Format orderbook data
        orderbook = data.get("orderbook", data)
        return {
            "yes": orderbook.get("yes", []),
            "no": orderbook.get("no", []),
            "ticker": ticker,
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch orderbook for {ticker}: {e}")
        return {"yes": [], "no": [], "ticker": ticker}


def get_trades(
    key_id: str,
    private_key_pem: str,
    ws_url: str = None,
    ticker: str = None,
    limit: int = 100,
    cursor: str = None,
    min_ts: int = None,
    max_ts: int = None,
) -> Dict[str, Any]:
    """
    Fetch trades from Kalshi REST API.
    
    Args:
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL (demo vs production)
        ticker: Optional market ticker to filter trades
        limit: Maximum number of trades to return (max 1000)
        cursor: Pagination cursor
        min_ts: Minimum timestamp (Unix epoch seconds)
        max_ts: Maximum timestamp (Unix epoch seconds)
        
    Returns:
        Dictionary with 'trades' list and 'cursor' for pagination
    """
    if ws_url and "demo" in ws_url:
        base_url = "https://demo-api.kalshi.co"
    else:
        base_url = "https://api.elections.kalshi.com"
    
    path = "/trade-api/v2/markets/trades"
    
    # Build query parameters
    params = {"limit": min(limit, 1000)}
    if ticker:
        params["ticker"] = ticker
    if cursor:
        params["cursor"] = cursor
    if min_ts:
        params["min_ts"] = min_ts
    if max_ts:
        params["max_ts"] = max_ts
    
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
        
        data = response.json()
        
        # Format trades with consistent field names
        trades = []
        for trade in data.get("trades", []):
            formatted_trade = {
                "trade_id": trade.get("trade_id"),
                "ticker": trade.get("ticker"),
                "price": trade.get("yes_price") or trade.get("price"),
                "yes_price": trade.get("yes_price"),
                "no_price": trade.get("no_price"),
                "count": trade.get("count") or trade.get("size", 1),
                "taker_side": trade.get("taker_side"),
                "created_time": trade.get("created_time"),
            }
            trades.append(formatted_trade)
        
        return {
            "trades": trades,
            "cursor": data.get("cursor"),
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch trades: {e}")
        return {"trades": [], "cursor": None}


def get_candlesticks(
    ticker: str,
    key_id: str,
    private_key_pem: str,
    ws_url: str = None,
    series_ticker: str = None,
    period_interval: int = 1,  # Minutes per candle
    start_ts: int = None,
    end_ts: int = None,
) -> List[Dict[str, Any]]:
    """
    Fetch candlestick/OHLC data for a market.
    
    Args:
        ticker: Market ticker symbol
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL
        series_ticker: Optional series ticker
        period_interval: Minutes per candle (1, 5, 15, 60, etc.)
        start_ts: Start timestamp (Unix epoch seconds)
        end_ts: End timestamp (Unix epoch seconds)
        
    Returns:
        List of candlestick dictionaries with open, high, low, close, volume
    """
    if ws_url and "demo" in ws_url:
        base_url = "https://demo-api.kalshi.co"
    else:
        base_url = "https://api.elections.kalshi.com"
    
    path = f"/trade-api/v2/markets/{ticker}/candlesticks"
    
    # Build query parameters
    params = {"period_interval": period_interval}
    if series_ticker:
        params["series_ticker"] = series_ticker
    if start_ts:
        params["start_ts"] = start_ts
    if end_ts:
        params["end_ts"] = end_ts
    
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
        
        data = response.json()
        
        # Format candlesticks
        candlesticks = []
        for candle in data.get("candlesticks", []):
            formatted_candle = {
                "timestamp": candle.get("end_period_ts") or candle.get("ts"),
                "open": candle.get("open_price") or candle.get("open"),
                "high": candle.get("high_price") or candle.get("high"),
                "low": candle.get("low_price") or candle.get("low"),
                "close": candle.get("close_price") or candle.get("close") or candle.get("price"),
                "volume": candle.get("volume", 0),
                "yes_price": candle.get("yes_price") or candle.get("close_price") or candle.get("price"),
            }
            candlesticks.append(formatted_candle)
        
        return candlesticks
        
    except Exception as e:
        logger.error(f"Failed to fetch candlesticks for {ticker}: {e}")
        return []


def get_all_sports_markets(
    key_id: str,
    private_key_pem: str,
    ws_url: str = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch all sports markets, organized by sport/league.
    
    Returns markets for all configured sports (NBA, Soccer leagues, Cricket).
    
    Args:
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format
        ws_url: WebSocket URL to determine API base URL
        
    Returns:
        Dictionary mapping sport/league to list of market dicts:
        {
            "nba": [...],
            "bundesliga": [...],
            "la_liga": [...],
            "t20_international": [...],
            ...
        }
    """
    all_markets = {}
    
    # Fetch basketball markets
    try:
        nba_markets = get_basketball_markets(
            key_id=key_id,
            private_key_pem=private_key_pem,
            ws_url=ws_url,
            leagues=["nba"],
        )
        if nba_markets:
            all_markets["nba"] = nba_markets
    except Exception as e:
        logger.error(f"Failed to fetch NBA markets: {e}")
    
    # Fetch soccer markets for all leagues
    soccer_leagues = ["bundesliga", "la_liga", "premier_league", "mls", "ucl"]
    for league in soccer_leagues:
        try:
            soccer_markets = get_soccer_markets(
                key_id=key_id,
                private_key_pem=private_key_pem,
                ws_url=ws_url,
                leagues=[league],
            )
            if soccer_markets:
                all_markets[league] = soccer_markets
        except Exception as e:
            logger.error(f"Failed to fetch {league} markets: {e}")
    
    # Fetch cricket markets for all leagues
    cricket_leagues = ["t20_international", "ipl"]
    for league in cricket_leagues:
        try:
            cricket_markets = get_cricket_markets(
                key_id=key_id,
                private_key_pem=private_key_pem,
                ws_url=ws_url,
                leagues=[league],
            )
            if cricket_markets:
                all_markets[league] = cricket_markets
        except Exception as e:
            logger.error(f"Failed to fetch {league} cricket markets: {e}")
    
    return all_markets


def group_markets_by_event(markets: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Group markets by event (game/match).
    
    Similar to group_markets_by_match but returns more structured data
    suitable for the live dashboard.
    
    Args:
        markets: List of market dictionaries
        
    Returns:
        Dictionary mapping event_id to event data:
        {
            "26JAN19STUFRA": {
                "event_id": "26JAN19STUFRA",
                "title": "Stuttgart vs Frankfurt",
                "league": "bundesliga",
                "close_time": "2026-01-19T...",
                "markets": [
                    {"ticker": "...-STU", "subtitle": "Stuttgart", ...},
                    {"ticker": "...-TIE", "subtitle": "Tie", ...},
                    {"ticker": "...-FRA", "subtitle": "Frankfurt", ...},
                ]
            }
        }
    """
    events = {}
    
    for market in markets:
        ticker = market.get("ticker", "")
        parts = ticker.split("-")
        
        # Extract event identifier (second part of ticker)
        if len(parts) >= 2:
            event_id = parts[1]
        else:
            event_id = market.get("event_ticker") or ticker
        
        if event_id not in events:
            # Parse title to get clean event name
            title = market.get("title", "Unknown Event")
            # Remove suffixes like "Winner?", "Tie?", etc.
            for suffix in [" Winner?", " Winner", " Tie?", " Tie", " Total?", " Total"]:
                title = title.replace(suffix, "")
            
            events[event_id] = {
                "event_id": event_id,
                "title": title.strip(),
                "league": market.get("league", "unknown"),
                "close_time": market.get("close_time") or market.get("expiration_time"),
                "markets": [],
            }
        
        # Add market to event with useful fields for display
        market_info = {
            "ticker": market.get("ticker"),
            "subtitle": market.get("subtitle") or market.get("yes_sub_title") or _extract_outcome_from_ticker(ticker),
            "market_type": market.get("market_type", "unknown"),
            "yes_bid": market.get("yes_bid"),
            "yes_ask": market.get("yes_ask"),
            "no_bid": market.get("no_bid"),
            "no_ask": market.get("no_ask"),
            "last_price": market.get("last_price"),
            "volume": market.get("volume", 0),
        }
        events[event_id]["markets"].append(market_info)
    
    return events


def _extract_outcome_from_ticker(ticker: str) -> str:
    """Extract outcome name from ticker suffix (e.g., STU, TIE, FRA)."""
    parts = ticker.split("-")
    if len(parts) >= 3:
        outcome = parts[-1]
        # Remove any numbers (for spread/total tickers)
        import re
        outcome = re.sub(r'\d+', '', outcome)
        return outcome
    return "Unknown"

