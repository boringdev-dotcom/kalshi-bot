"""Shared Kalshi API authentication utilities."""
import base64
import logging

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)


def load_private_key(private_key_pem: str):
    """
    Load RSA private key from PEM string, handling multiple formats.
    
    Supports:
    - PKCS#8 format: -----BEGIN PRIVATE KEY-----
    - PKCS#1 format: -----BEGIN RSA PRIVATE KEY-----
    - Base64 without headers (will add headers automatically)
    
    Args:
        private_key_pem: RSA private key in PEM format (as string)
        
    Returns:
        Loaded private key object
        
    Raises:
        ValueError: If the key cannot be loaded in any format
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
                key_with_headers = (
                    "-----BEGIN PRIVATE KEY-----\n"
                    + "\n".join(key_lines)
                    + "\n-----END PRIVATE KEY-----"
                )
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
                key_str_rsa = key_str.replace(
                    "BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY"
                ).replace("END PRIVATE KEY", "END RSA PRIVATE KEY")
                private_key = serialization.load_pem_private_key(
                    key_str_rsa.encode(),
                    password=None,
                    backend=default_backend()
                )
            elif not key_str.startswith("-----"):
                # Try PKCS#1 headers
                key_lines = [key_str[i:i+64] for i in range(0, len(key_str), 64)]
                key_with_headers = (
                    "-----BEGIN RSA PRIVATE KEY-----\n"
                    + "\n".join(key_lines)
                    + "\n-----END RSA PRIVATE KEY-----"
                )
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
        # Provide helpful error message with key diagnostics
        key_preview = key_str[:200] if len(key_str) > 200 else key_str
        key_start = key_str[:50] if len(key_str) > 50 else key_str
        logger.error("Private key format diagnostics:")
        logger.error(f"  Key length: {len(key_str)} characters")
        logger.error(f"  Starts with: {repr(key_start)}")
        logger.error(f"  Contains 'BEGIN': {'BEGIN' in key_str}")
        logger.error(f"  Contains 'PRIVATE': {'PRIVATE' in key_str}")
        logger.error(f"  Contains 'CERTIFICATE': {'CERTIFICATE' in key_str}")
        raise ValueError(
            f"Could not parse private key. Last error: {last_error}\n"
            f"Key preview: {key_preview}\n"
            f"Please ensure your KALSHI_PRIVATE_KEY_PEM is in PEM format.\n"
            f"Expected formats:\n"
            f"  - PKCS#8: -----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
            f"  - PKCS#1: -----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n"
            f"If Kalshi provided a certificate file, you need the private key, not the certificate."
        )
    
    return private_key


def sign_request(private_key_pem: str, timestamp_ms: str, method: str, path: str) -> str:
    """
    Generate RSA-PSS signature for Kalshi API authentication.
    
    Works for both REST API and WebSocket authentication.
    
    Args:
        private_key_pem: RSA private key in PEM format (as string)
        timestamp_ms: Timestamp in milliseconds as string
        method: HTTP method (GET, POST, etc.) - use "GET" for WebSocket
        path: API path (e.g., /trade-api/v2/markets/{ticker} or /trade-api/ws/v2)
        
    Returns:
        Base64-encoded signature string
    """
    private_key = load_private_key(private_key_pem)
    
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

