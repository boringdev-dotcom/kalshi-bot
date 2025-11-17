"""Kalshi REST API client for fetching market details."""
import logging
import time
from typing import Optional

import requests

from .kalshi_auth import sign_request

logger = logging.getLogger(__name__)


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

