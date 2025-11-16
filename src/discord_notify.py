"""Discord webhook notifier for Kalshi order events."""
import logging
import os
import requests
from datetime import datetime
from dotenv import load_dotenv

from .kalshi_api import get_market_name_cached, get_market_data

logger = logging.getLogger(__name__)


def format_price(price_cents: int) -> str:
    """Convert price from cents to dollars with proper formatting."""
    if price_cents is None:
        return "N/A"
    return f"${price_cents / 100:.2f}"


def format_side(side: str) -> str:
    """Format side to be more readable."""
    if not side:
        return "N/A"
    return side.upper()


def post_order_created(webhook_url: str, order: dict, ws_url: str = None) -> None:
    """
    Send a Discord notification when a new Kalshi order event occurs.
    
    Args:
        webhook_url: Discord webhook URL
        order: Order data dictionary from Kalshi WebSocket (could be fill, order creation, etc.)
    """
    try:
        # Extract order details with fallbacks for different event formats
        ticker = order.get('market_ticker') or order.get('ticker', 'N/A')
        
        # Fetch human-readable market name from API
        # Load credentials from environment if not passed
        key_id = os.getenv("KALSHI_API_KEY_ID")
        private_key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")
        if private_key_pem:
            private_key_pem = private_key_pem.replace("\\n", "\n")
        
        # Fetch market details (name and payout info) from API
        # Use cached name first to avoid blocking, then try to fetch full data
        market_data = None
        if key_id and private_key_pem and ticker != 'N/A':
            # Try cached name first (fast)
            market_name = get_market_name_cached(ticker, key_id, private_key_pem, ws_url)
            
            # Try to fetch full market data (may timeout, but that's OK)
            try:
                market_data = get_market_data(ticker, key_id, private_key_pem, ws_url)
                if market_data:
                    # Update name from full data if available
                    market_name = market_data.get('title') or market_data.get('subtitle') or market_name
            except Exception as e:
                logger.debug(f"Could not fetch market data for {ticker}: {e}")
                # Continue without market_data - we have the name from cache
        else:
            market_name = ticker
        
        action = order.get('action', '').capitalize() if order.get('action') else ''
        is_sell = action.lower() == "sell"
        
        # Always use 'side' to determine what YES/NO means
        # The ticker suffix (-NGR, -COD) indicates which team's market this is
        raw_side = order.get('side', '')
        side = format_side(raw_side)
        
        # Determine what YES/NO means using ticker suffix and market API data
        # The ticker suffix (-NGR, -COD, -TIE) indicates which market this is
        # For example: KXFIFAGAME-25NOV16NGRCOD-NGR means Nigeria's market (YES = Nigeria wins)
        #              KXFIFAGAME-25NOV16ITANOR-TIE means Tie market (YES = Tie happens)
        side_display = side
        if market_data and raw_side:
            market_title = market_data.get('title') or market_name or ''
            market_subtitle = market_data.get('subtitle') or ''
            
            # Extract ticker suffix to determine which market this is
            ticker_suffix = ticker.split('-')[-1].upper() if '-' in ticker else ''
            
            # Handle special case: TIE market
            if ticker_suffix == 'TIE':
                # This is a tie market: YES = Tie happens, NO = No tie
                if raw_side.upper() == 'YES':
                    side_display = "YES - Tie"
                elif raw_side.upper() == 'NO':
                    side_display = "NO - Tie"
            # Try to use subtitle first (API-provided team name)
            elif market_subtitle and ' vs ' in market_title and 'Winner' in market_title:
                parts = market_title.split(' vs ')
                if len(parts) >= 2:
                    team_a = parts[0].strip()
                    team_b = parts[1].split('Winner')[0].strip()
                    
                    # Check if subtitle matches one of the teams
                    if market_subtitle.strip() == team_a:
                        # This is team_a's market
                        if raw_side.upper() == 'YES':
                            side_display = f"YES - {team_a}"
                        elif raw_side.upper() == 'NO':
                            side_display = f"NO - {team_a} ({team_b})"
                    elif market_subtitle.strip() == team_b:
                        # This is team_b's market
                        if raw_side.upper() == 'YES':
                            side_display = f"YES - {team_b}"
                        elif raw_side.upper() == 'NO':
                            side_display = f"NO - {team_b} ({team_a})"
                    else:
                        # Subtitle doesn't match exactly, use subtitle directly
                        if raw_side.upper() == 'YES':
                            side_display = f"YES - {market_subtitle}"
                        elif raw_side.upper() == 'NO':
                            side_display = f"NO - {market_subtitle}"
            elif ' vs ' in market_title and 'Winner' in market_title:
                # Fallback: Parse market title and match ticker suffix to team names
                # The ticker suffix (e.g., -NGR, -COD) indicates which team's market this is
                parts = market_title.split(' vs ')
                if len(parts) >= 2:
                    team_a = parts[0].strip()
                    team_b = parts[1].split('Winner')[0].strip()
                    
                    # Check the ticker suffix to determine which team's market this is
                    ticker_suffix = ticker.split('-')[-1].upper() if '-' in ticker else ''
                    
                    # Try to match ticker suffix with team names (generic approach)
                    # Extract key words from team names and check if suffix matches
                    team_a_words = [word.upper()[:3] for word in team_a.split() if len(word) >= 3]
                    team_b_words = [word.upper()[:3] for word in team_b.split() if len(word) >= 3]
                    
                    # Check if ticker suffix matches any part of team names
                    matches_team_a = (
                        ticker_suffix in team_a.upper() or
                        any(ticker_suffix.startswith(word) or word.startswith(ticker_suffix[:3]) 
                            for word in team_a_words if len(ticker_suffix) >= 3)
                    )
                    matches_team_b = (
                        ticker_suffix in team_b.upper() or
                        any(ticker_suffix.startswith(word) or word.startswith(ticker_suffix[:3]) 
                            for word in team_b_words if len(ticker_suffix) >= 3)
                    )
                    
                    # Determine which team's market this is
                    if matches_team_a and not matches_team_b:
                        # This is team_a's market: YES = team_a wins, NO = team_b wins
                        if raw_side.upper() == 'YES':
                            side_display = f"YES - {team_a}"
                        elif raw_side.upper() == 'NO':
                            side_display = f"NO - {team_a} ({team_b})"
                    elif matches_team_b and not matches_team_a:
                        # This is team_b's market: YES = team_b wins, NO = team_a wins
                        if raw_side.upper() == 'YES':
                            side_display = f"YES - {team_b}"
                        elif raw_side.upper() == 'NO':
                            side_display = f"NO - {team_b} ({team_a})"
                    else:
                        # Fallback: assume first team (original behavior)
                        if raw_side.upper() == 'YES':
                            side_display = f"YES - {team_a}"
                        elif raw_side.upper() == 'NO':
                            side_display = f"NO - {team_a}"
            elif 'Will ' in market_title or '?' in market_title:
                # Pattern: "Will X happen?" -> YES = X happens, NO = X doesn't happen
                # Extract the main subject
                if 'Will ' in market_title:
                    subject = market_title.split('Will ')[1].split('?')[0].split(' happen')[0].strip()
                    if raw_side.upper() == 'YES':
                        side_display = f"YES ({subject})"
                    elif raw_side.upper() == 'NO':
                        side_display = f"NO ({subject} won't happen)"
        
        # Fill events use "count", order events might use "size" or "initial_count"
        count = order.get('count') or order.get('size') or order.get('initial_count', 'N/A')
        
        # Price handling - fill events use "yes_price" (in cents), order events might use "price" or "yes_price_dollars"
        price_cents = order.get('yes_price') or order.get('no_price')
        price_dollars = order.get('yes_price_dollars') or order.get('no_price_dollars')
        
        if price_cents:
            price_per_contract = price_cents / 100
            price = format_price(price_cents)
        elif price_dollars:
            price_per_contract = float(price_dollars)
            price = f"${price_per_contract:.2f}"
        else:
            price_per_contract = None
            price = "N/A"
        
        # Calculate total dollar amount
        # For BUY: this is what you paid
        # For SELL: this is what you received
        # (is_sell already determined above)
        
        # Check if we have pre-calculated total amount from aggregation (for partial fills)
        total_amount_cents = order.get('total_amount_cents')
        if total_amount_cents is not None:
            # Use the aggregated total amount (more accurate for partial fills)
            total_amount = total_amount_cents / 100
            if is_sell:
                total_display = f"${total_amount:.2f} (received)"
            else:
                total_display = f"${total_amount:.2f}"
        elif price_per_contract is not None and count != 'N/A':
            try:
                total_amount = price_per_contract * int(count)
                if is_sell:
                    total_display = f"${total_amount:.2f} (received)"
                else:
                    total_display = f"${total_amount:.2f}"
            except (ValueError, TypeError):
                total_display = "N/A"
        else:
            total_display = "N/A"
        
        # Calculate potential payout if order hits (only for BUY orders)
        # For SELL orders, you already got paid, so no potential payout
        total_payout = None
        if not is_sell and market_data and count != 'N/A' and price_per_contract is not None:
            try:
                contract_count = int(count)
                # If YES side, payout is $1 per contract if it hits
                # If NO side, payout is $1 per contract if it hits
                # Total payout = number of contracts * $1
                if side == "YES":
                    total_payout = contract_count * 1.0  # $1 per contract if YES wins
                elif side == "NO":
                    total_payout = contract_count * 1.0  # $1 per contract if NO wins
            except (ValueError, TypeError):
                pass
        
        # Build market/order link
        # Kalshi URL format: https://demo.kalshi.co/markets/{slug}/{title-slug}/{ticker-base}
        # Example: https://demo.kalshi.co/markets/kxbtc/bitcoin-range/kxbtc-25nov1615
        if market_data:
            # Try to get URL fields from market data
            slug = market_data.get('slug') or market_data.get('category_slug')
            title_slug = market_data.get('title_slug') or market_data.get('subtitle_slug')
            
            # Extract ticker base (remove suffix like -B88375)
            # Format is usually: CATEGORY-DATE-SUFFIX (e.g., KXBTC-25NOV1615-B88375)
            ticker_parts = ticker.split('-')
            if len(ticker_parts) >= 2:
                # Take first two parts: CATEGORY-DATE
                ticker_base = '-'.join(ticker_parts[:2]).lower()
            else:
                ticker_base = ticker.lower()
            
            # Construct URL if we have the necessary parts
            # Determine website base URL from WebSocket URL
            # Always use kalshi.com for production (not elections.kalshi.com)
            if ws_url and "demo" in ws_url:
                website_base = "https://demo.kalshi.co"
            else:
                website_base = "https://kalshi.com"
            
            if slug and title_slug:
                order_link = f"{website_base}/markets/{slug}/{title_slug}/{ticker_base}"
            else:
                # Fallback: try to construct from ticker
                # Extract category from ticker (e.g., "KXBTC" -> "kxbtc")
                category = ticker_parts[0].lower() if ticker_parts else ticker.lower()
                order_link = f"{website_base}/markets/{category}/{ticker_base}"
        else:
            # Fallback: construct basic URL from ticker
            ticker_parts = ticker.split('-')
            category = ticker_parts[0].lower() if ticker_parts else ticker.lower()
            # Extract ticker base (first two parts)
            if len(ticker_parts) >= 2:
                ticker_base = '-'.join(ticker_parts[:2]).lower()
            else:
                ticker_base = ticker.lower()
            
            # Determine website base URL from WebSocket URL
            # Always use kalshi.com for production (not elections.kalshi.com)
            if ws_url and "demo" in ws_url:
                website_base = "https://demo.kalshi.co"
            else:
                website_base = "https://kalshi.com"
            
            order_link = f"{website_base}/markets/{category}/{ticker_base}"
        
        # Format timestamp if available
        timestamp = order.get('timestamp') or order.get('created_time')
        if timestamp:
            try:
                # Try to parse and format timestamp
                if isinstance(timestamp, str):
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                else:
                    formatted_time = str(timestamp)
            except:
                formatted_time = str(timestamp)
        else:
            formatted_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        
        # Determine if this was a partial fill (multiple fills for same order)
        is_partial = order.get('is_partial', False)
        fill_count = order.get('fill_count', 1)
        
        # Create Discord embed for better formatting
        title = "🎯 Kalshi Order Filled"
        if is_partial:
            title = f"🎯 Kalshi Order Filled ({fill_count} partial fills)"
        
        # Build fields list
        fields = [
            {
                "name": "📊 Market",
                "value": f"**{market_name}**",
                "inline": False
            },
            {
                "name": "📈 Side",
                "value": f"**{side_display}**",
                "inline": True
            },
            {
                "name": "⚡ Action",
                "value": f"**{action}**" if action else "N/A",
                "inline": True
            },
        ]
        
        # Add time field
        fields.append({
            "name": "🕐 Time",
            "value": formatted_time,
            "inline": False
        })
        
        # Create Discord embed
        embed = {
            "title": title,
            "color": 0x00ff00 if side == "YES" else 0xff0000,  # Green for YES, Red for NO
            "fields": fields,
            "footer": {
                "text": "Kalshi Trading Bot"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        payload = {
            "embeds": [embed],
            "content": f"**Order Filled:** [{market_name}]({order_link})"
        }
        
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        order_id = order.get('order_id', 'N/A')
        logger.info(f"Discord notification sent for order {order_id}")
    except requests.RequestException as e:
        logger.error(f"Failed to send Discord notification: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending Discord notification: {e}", exc_info=True)

