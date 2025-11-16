"""Kalshi REST API client for fetching market details."""
import base64
import hashlib
import hmac
import logging
import os
import time
from functools import lru_cache
from typing import Optional

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)


def sign_request(private_key_pem: str, timestamp_ms: str, method: str, path: str) -> str:
    """
    Generate RSA-PSS signature for Kalshi REST API authentication.
    
    Args:
        private_key_pem: RSA private key in PEM format (as string)
        timestamp_ms: Timestamp in milliseconds as string
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g., /trade-api/v2/markets/{ticker})
        
    Returns:
        Base64-encoded signature string
    """
    # Normalize the private key string
    key_str = private_key_pem.strip()
    
    # Try to load the private key - handle multiple formats
    private_key = None
    last_error = None
    
    # Try PKCS#8 format (PRIVATE KEY) - most common
    try:
        private_key = serialization.load_pem_private_key(
            key_str.encode(),
            password=None,
            backend=default_backend()
        )
    except ValueError as e:
        last_error = e
        # If it's base64 without headers, try adding PKCS#8 headers
        if not key_str.startswith("-----"):
            try:
                # Split into 64-char lines for proper PEM format
                key_lines = [key_str[i:i+64] for i in range(0, len(key_str), 64)]
                key_with_headers = f"-----BEGIN PRIVATE KEY-----\n" + "\n".join(key_lines) + "\n-----END PRIVATE KEY-----"
                private_key = serialization.load_pem_private_key(
                    key_with_headers.encode(),
                    password=None,
                    backend=default_backend()
                )
            except ValueError:
                pass
    
    # If PKCS#8 failed, try PKCS#1 format (RSA PRIVATE KEY)
    if private_key is None:
        try:
            # If it has PKCS#8 headers, try replacing with PKCS#1
            if "BEGIN PRIVATE KEY" in key_str:
                key_str_rsa = key_str.replace("BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY").replace("END PRIVATE KEY", "END RSA PRIVATE KEY")
                private_key = serialization.load_pem_private_key(
                    key_str_rsa.encode(),
                    password=None,
                    backend=default_backend()
                )
            elif not key_str.startswith("-----"):
                # Try PKCS#1 headers
                key_lines = [key_str[i:i+64] for i in range(0, len(key_str), 64)]
                key_with_headers = f"-----BEGIN RSA PRIVATE KEY-----\n" + "\n".join(key_lines) + "\n-----END RSA PRIVATE KEY-----"
                private_key = serialization.load_pem_private_key(
                    key_with_headers.encode(),
                    password=None,
                    backend=default_backend()
                )
            else:
                private_key = serialization.load_pem_private_key(
                    key_str.encode(),
                    password=None,
                    backend=default_backend()
                )
        except ValueError as e:
            last_error = e
    
    if private_key is None:
        raise ValueError(f"Could not load private key: {last_error}")
    
    # Create the message to sign: timestamp + method + path
    message = f"{timestamp_ms}{method}{path}".encode()
    
    # Sign using RSA-PSS
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    
    # Return base64-encoded signature
    return base64.b64encode(signature).decode('utf-8')


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
        market_name = data.get('market', {}).get('title') or data.get('title')
        return market_name
        
    except Exception as e:
        logger.warning(f"Failed to fetch market name for {ticker}: {e}")
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

