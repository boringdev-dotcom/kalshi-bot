#!/usr/bin/env python3
"""Helper script to generate curl command for Kalshi API."""
import os
import sys
import time

from src.kalshi_auth import sign_request

def generate_curl(ticker: str, base_url: str = None):
    """Generate curl command for fetching market data."""
    from dotenv import load_dotenv
    load_dotenv()
    
    key_id = os.getenv("KALSHI_API_KEY_ID")
    private_key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")
    
    if not key_id or not private_key_pem:
        print("Error: KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PEM must be set in .env")
        sys.exit(1)
    
    if private_key_pem:
        private_key_pem = private_key_pem.replace("\\n", "\n")
    
    if base_url is None:
        # Default to production
        base_url = "https://api.elections.kalshi.com"
    
    path = f"/trade-api/v2/markets/{ticker}"
    url = base_url + path
    
    timestamp_ms = str(int(time.time() * 1000))
    signature = sign_request(private_key_pem, timestamp_ms, "GET", path)
    
    print(f"curl -X GET '{url}' \\")
    print(f"  -H 'KALSHI-ACCESS-KEY: {key_id}' \\")
    print(f"  -H 'KALSHI-ACCESS-SIGNATURE: {signature}' \\")
    print(f"  -H 'KALSHI-ACCESS-TIMESTAMP: {timestamp_ms}'")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_curl.py <TICKER> [BASE_URL]")
        print("Example: python generate_curl.py KXNBAGAME-25NOV16SACSAS-SAS")
        print("Example: python generate_curl.py KXNBAGAME-25NOV16SACSAS-SAS https://demo-api.kalshi.co")
        sys.exit(1)
    
    ticker = sys.argv[1]
    base_url = sys.argv[2] if len(sys.argv) > 2 else None
    generate_curl(ticker, base_url)

