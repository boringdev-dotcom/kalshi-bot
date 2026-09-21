"""RSA-PSS signing for Kalshi REST and WebSocket."""

from __future__ import annotations

import base64
import logging
import time

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

WS_PATH = "/trade-api/ws/v2"


def load_private_key(private_key_pem: str):
    key_str = private_key_pem.strip()
    private_key = None
    last_error: Exception | None = None

    try:
        private_key = serialization.load_pem_private_key(
            key_str.encode(),
            password=None,
            backend=default_backend(),
        )
    except ValueError as exc:
        last_error = exc
        if not key_str.startswith("-----"):
            try:
                key_lines = [key_str[i : i + 64] for i in range(0, len(key_str), 64)]
                wrapped = (
                    "-----BEGIN PRIVATE KEY-----\n"
                    + "\n".join(key_lines)
                    + "\n-----END PRIVATE KEY-----"
                )
                private_key = serialization.load_pem_private_key(
                    wrapped.encode(),
                    password=None,
                    backend=default_backend(),
                )
            except ValueError:
                pass

    if private_key is None:
        try:
            if "BEGIN PRIVATE KEY" in key_str:
                rsa_pem = key_str.replace("BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY").replace(
                    "END PRIVATE KEY", "END RSA PRIVATE KEY"
                )
                private_key = serialization.load_pem_private_key(
                    rsa_pem.encode(),
                    password=None,
                    backend=default_backend(),
                )
            elif not key_str.startswith("-----"):
                key_lines = [key_str[i : i + 64] for i in range(0, len(key_str), 64)]
                wrapped = (
                    "-----BEGIN RSA PRIVATE KEY-----\n"
                    + "\n".join(key_lines)
                    + "\n-----END RSA PRIVATE KEY-----"
                )
                private_key = serialization.load_pem_private_key(
                    wrapped.encode(),
                    password=None,
                    backend=default_backend(),
                )
            else:
                private_key = serialization.load_pem_private_key(
                    key_str.encode(),
                    password=None,
                    backend=default_backend(),
                )
        except ValueError as exc:
            last_error = exc

    if private_key is None:
        raise ValueError(
            f"Could not parse KALSHI_PRIVATE_KEY_PEM. Last error: {last_error}. "
            "Expected PKCS#8 or PKCS#1 PEM."
        )
    return private_key


def sign_request(private_key_pem: str, timestamp_ms: str, method: str, path: str) -> str:
    private_key = load_private_key(private_key_pem)
    message = f"{timestamp_ms}{method}{path}".encode()
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def auth_headers(key_id: str, private_key_pem: str, method: str, path: str) -> dict[str, str]:
    timestamp_ms = str(int(time.time() * 1000))
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": sign_request(private_key_pem, timestamp_ms, method, path),
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
    }
