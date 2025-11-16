"""Kalshi WebSocket client for subscribing to order events."""
import asyncio
import base64
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)

KALSHI_WS_PATH = "/trade-api/ws/v2"


def sign_ws(private_key_pem: str, timestamp_ms: str, method: str, path: str) -> str:
    """
    Generate RSA-PSS signature for Kalshi WebSocket authentication.
    
    Args:
        private_key_pem: RSA private key in PEM format (as string)
        timestamp_ms: Timestamp in milliseconds as string
        method: HTTP method (GET for WebSocket)
        path: WebSocket path
        
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
        # Provide helpful error message with key diagnostics
        key_preview = key_str[:200] if len(key_str) > 200 else key_str
        key_start = key_str[:50] if len(key_str) > 50 else key_str
        logger.error(f"Private key format diagnostics:")
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


async def stream_orders(
    ws_url: str,
    key_id: str,
    private_key_pem: str,
    on_created: callable,
    reconnect_delay: float = 1.0,
    max_reconnect_delay: float = 30.0,
) -> None:
    """
    Connect to Kalshi WebSocket and stream order events.
    
    Automatically reconnects on connection loss with exponential backoff.
    Deduplicates multiple fill events for the same order_id.
    
    Args:
        ws_url: WebSocket URL (e.g., wss://demo-api.kalshi.co/trade-api/ws/v2)
        key_id: Kalshi API key ID
        private_key_pem: RSA private key in PEM format (as string)
        on_created: Async callback function called when an order is created/filled
        reconnect_delay: Initial reconnect delay in seconds
        max_reconnect_delay: Maximum reconnect delay in seconds
    """
    # Track fills per order_id to aggregate partial fills
    order_fills = defaultdict(list)  # order_id -> list of fill events
    fill_timeouts = {}  # order_id -> asyncio.Task for timeout
    
    async def process_order_fill(fill_data: dict, order_id: str):
        """Process a fill event, aggregating partial fills."""
        # Add this fill to the list for this order
        order_fills[order_id].append(fill_data)
        
        # Cancel any existing timeout for this order
        if order_id in fill_timeouts:
            fill_timeouts[order_id].cancel()
        
        # Wait a short time (500ms) to see if more fills come in for the same order
        async def send_aggregated_notification():
            await asyncio.sleep(0.5)  # Wait for potential additional fills
            
            if order_id in order_fills:
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
                
                # Clean up
                del order_fills[order_id]
                if order_id in fill_timeouts:
                    del fill_timeouts[order_id]
        
        # Schedule the aggregated notification
        fill_timeouts[order_id] = asyncio.create_task(send_aggregated_notification())
    
    delay = reconnect_delay
    
    while True:
        try:
            # Generate authentication headers
            timestamp_ms = str(int(time.time() * 1000))
            signature = sign_ws(private_key_pem, timestamp_ms, "GET", KALSHI_WS_PATH)
            
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
                
                # Subscribe to order events
                # Based on Kalshi docs, try "fill" channel first (for order fills)
                # If you want order creation events, we might need a different channel
                subscribe_message = {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["fill"]
                    }
                }
                await ws.send(json.dumps(subscribe_message))
                logger.info(f"Sent subscription message: {json.dumps(subscribe_message)}")
                logger.info("Note: 'fill' channel will notify on order fills. For order creation, we may need a different channel.")
                
                # Reset reconnect delay on successful connection
                delay = reconnect_delay
                
                # Listen for messages
                async for raw_message in ws:
                    try:
                        event = json.loads(raw_message)
                        event_type = event.get("type", "unknown")
                        logger.info(f"Received WebSocket event: type={event_type}, full_event={json.dumps(event, indent=2)}")
                        
                        # Handle subscription confirmation
                        if event_type == "subscribed" or event.get("cmd") == "subscribe":
                            logger.info("Successfully subscribed to orders channel")
                            continue
                        
                        # Handle error messages
                        if event_type == "error" or event.get("error"):
                            logger.error(f"WebSocket error message: {event}")
                            continue
                        
                        # Extract event data - could be in "data", "msg", or at root level
                        event_data = event.get("data") or event.get("msg") or event
                        
                        # Handle fill events (order fills)
                        if event_type == "fill":
                            order_id = event_data.get('order_id')
                            logger.info(f"Order fill received: {order_id}, count: {event_data.get('count')}")
                            # Process fill with aggregation to handle partial fills
                            await process_order_fill(event_data, order_id)
                        
                        # Handle order creation/update events
                        elif event_type == "order_update" or event_type == "order":
                            status = event_data.get("status")
                            action = event_data.get("action") or event.get("action")
                            
                            logger.info(f"Order event - status: {status}, action: {action}")
                            
                            # Check if this is a created order
                            if status in {"created", "open", "pending"} or action == "created":
                                logger.info(f"Order created: {event_data.get('order_id')}")
                                await on_created(event_data)
                            else:
                                logger.info(f"Ignoring order event - status: {status}, action: {action}")
                        else:
                            # Log unknown event types for debugging
                            logger.info(f"Received event type '{event_type}' - full event: {json.dumps(event, indent=2)}")
                            
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

