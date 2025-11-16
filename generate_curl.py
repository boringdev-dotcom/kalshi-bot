#!/usr/bin/env python3
"""Helper script to generate curl command for Kalshi API."""
import os
import sys
import time
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

def sign_request(private_key_pem: str, timestamp_ms: str, method: str, path: str) -> str:
    """Generate RSA-PSS signature for Kalshi REST API authentication."""
    key_str = private_key_pem.strip()
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
    
    message = f"{timestamp_ms}{method}{path}".encode()
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

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

