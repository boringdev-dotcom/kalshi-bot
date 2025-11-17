"""Discord webhook notifier for Kalshi order events."""
import logging
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

import requests

from .config import Settings
from .kalshi_api import get_market_name_cached, get_market_data

logger = logging.getLogger(__name__)


def format_price(price_cents: Optional[int]) -> str:
    """Convert price from cents to dollars with proper formatting."""
    if price_cents is None:
        return "N/A"
    return f"${price_cents / 100:.2f}"


def format_side(side: Optional[str]) -> str:
    """Format side to be more readable."""
    if not side:
        return "N/A"
    return side.upper()


def create_order_embed(
    order: Dict[str, Any], 
    ws_url: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Create Discord embed and content for an order notification.
    
    Args:
        order: Order data dictionary from Kalshi WebSocket (could be fill, order creation, etc.)
        ws_url: WebSocket URL to determine API base URL (demo vs production)
    
    Returns:
        Tuple of (embed_dict, content_string) or (None, None) on error
    """
    try:
        # Extract order details with fallbacks for different event formats
        ticker = order.get('market_ticker') or order.get('ticker', 'N/A')
        
        # Fetch human-readable market name from API
        # Use Settings to get properly normalized credentials
        settings = Settings()
        key_id = settings.kalshi_api_key_id
        private_key_pem = settings.kalshi_private_key_pem
        
        # Fetch market details (name and payout info) from API
        # Use cached name first to avoid blocking, then try to fetch full data
        market_data = None
        if key_id and private_key_pem and ticker != 'N/A':
            # Try cached name first (fast)
            market_name = get_market_name_cached(ticker, key_id, private_key_pem, ws_url)
            
            # If we got the ticker back (cache miss and API failed), log it
            if market_name == ticker:
                logger.debug(f"Market name fetch failed for {ticker}, using ticker as fallback")
            
            # Try to fetch full market data (may timeout, but that's OK)
            try:
                market_data = get_market_data(ticker, key_id, private_key_pem, ws_url)
                if market_data:
                    # Update name from full data if available
                    fetched_name = market_data.get('title') or market_data.get('subtitle')
                    if fetched_name:
                        market_name = fetched_name
                        logger.debug(f"Successfully fetched market name for {ticker}: {market_name}")
            except Exception as e:
                logger.debug(f"Could not fetch market data for {ticker}: {e}")
                # Continue without market_data - we have the name from cache
        else:
            market_name = ticker
            if not key_id or not private_key_pem:
                logger.warning(f"Missing Kalshi API credentials, using ticker as market name: {ticker}")
        
        action = order.get('action', '').capitalize() if order.get('action') else ''
        is_sell = action.lower() == "sell"
        
        # Determine side display text (what YES/NO actually means)
        # Strategy (in order of preference):
        # 1. Use API yes_sub_title/no_sub_title (most accurate, provided by Kalshi)
        # 2. Parse market title for team names vs. ticker suffix (for sports markets)
        # 3. Parse "Will X happen?" pattern (for prediction markets)
        # 4. Fallback to plain YES/NO
        
        raw_side = order.get('side', '')
        side = format_side(raw_side)
        side_display = side  # Default fallback
        
        if market_data and raw_side:
            market_title = market_data.get('title') or market_name or ''
            
            # Extract ticker suffix to determine which market this is
            ticker_suffix = ticker.split('-')[-1].upper() if '-' in ticker else ''
            
            # Handle special case: TIE market
            if ticker_suffix == 'TIE':
                # This is a tie market: YES = Tie happens, NO = No tie
                if raw_side.upper() == 'YES':
                    side_display = "YES - Tie"
                elif raw_side.upper() == 'NO':
                    side_display = "NO - Tie"
            # Use yes_sub_title and no_sub_title from API (most accurate)
            elif market_data.get('yes_sub_title') or market_data.get('no_sub_title'):
                yes_sub_title = market_data.get('yes_sub_title', '')
                no_sub_title = market_data.get('no_sub_title', '')
                
                if raw_side.upper() == 'YES' and yes_sub_title:
                    side_display = f"YES - {yes_sub_title}"
                elif raw_side.upper() == 'NO' and no_sub_title:
                    side_display = f"NO - {no_sub_title}"
            elif ' vs ' in market_title and 'Winner' in market_title:
                # Fallback: Parse market title and match ticker suffix to team names
                # The ticker suffix (e.g., -NGR, -COD, -SAS) indicates which team's market this is
                parts = market_title.split(' vs ')
                if len(parts) >= 2:
                    team_a = parts[0].strip()
                    team_b = parts[1].split('Winner')[0].strip()
                    
                    # Check the ticker suffix to determine which team's market this is
                    # The ticker often contains abbreviations: SAC=Sacramento, SAS=San Antonio Spurs
                    # Match more precisely by checking if suffix appears as a distinct abbreviation
                    ticker_suffix = ticker.split('-')[-1].upper() if '-' in ticker else ''
                    
                    # Try to match ticker suffix more precisely
                    # Check if suffix matches team abbreviations or key words
                    team_a_upper = team_a.upper()
                    team_b_upper = team_b.upper()
                    
                    # Check for exact abbreviation matches first (e.g., "SAS" should match "San Antonio Spurs")
                    # Look for the suffix as a standalone word or abbreviation in team names
                    matches_team_a = (
                        ticker_suffix == team_a_upper or  # Exact match
                        f" {ticker_suffix} " in f" {team_a_upper} " or  # As standalone word
                        team_a_upper.startswith(ticker_suffix) or  # Starts with suffix
                        any(word.startswith(ticker_suffix) for word in team_a_upper.split())  # Any word starts with suffix
                    )
                    matches_team_b = (
                        ticker_suffix == team_b_upper or  # Exact match
                        f" {ticker_suffix} " in f" {team_b_upper} " or  # As standalone word
                        team_b_upper.startswith(ticker_suffix) or  # Starts with suffix
                        any(word.startswith(ticker_suffix) for word in team_b_upper.split())  # Any word starts with suffix
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
                        # If both match or neither matches, prefer more specific match
                        # Check if one team name contains the suffix more prominently
                        team_a_score = sum(1 for word in team_a_upper.split() if ticker_suffix in word or word.startswith(ticker_suffix))
                        team_b_score = sum(1 for word in team_b_upper.split() if ticker_suffix in word or word.startswith(ticker_suffix))
                        
                        if team_b_score > team_a_score:
                            # team_b matches better
                            if raw_side.upper() == 'YES':
                                side_display = f"YES - {team_b}"
                            elif raw_side.upper() == 'NO':
                                side_display = f"NO - {team_b} ({team_a})"
                        elif team_a_score > team_b_score:
                            # team_a matches better
                            if raw_side.upper() == 'YES':
                                side_display = f"YES - {team_a}"
                            elif raw_side.upper() == 'NO':
                                side_display = f"NO - {team_a} ({team_b})"
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
            # Calculate percentage odds (price in cents = percentage)
            odds_percentage = price_cents
        elif price_dollars:
            price_per_contract = float(price_dollars)
            price = f"${price_per_contract:.2f}"
            # Calculate percentage odds (convert dollars to percentage)
            odds_percentage = int(float(price_dollars) * 100)
        else:
            price_per_contract = None
            price = "N/A"
            odds_percentage = None
        
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
        
        # Add odds percentage if available
        if odds_percentage is not None:
            fields.append({
                "name": "🎯 Odds",
                "value": f"**{odds_percentage}%**",
                "inline": True
            })
        
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
        
        content = f"**Order Filled:** [{market_name}]({order_link})"
        
        return embed, content
    except Exception as e:
        logger.error(f"Unexpected error creating Discord notification: {e}", exc_info=True)
        return None, None


def post_order_created(
    webhook_url: str, 
    order: Dict[str, Any], 
    ws_url: Optional[str] = None
) -> None:
    """
    Send a Discord notification via webhook when a new Kalshi order event occurs.
    
    Args:
        webhook_url: Discord webhook URL
        order: Order data dictionary from Kalshi WebSocket (could be fill, order creation, etc.)
        ws_url: WebSocket URL to determine API base URL (demo vs production)
    """
    try:
        embed, content = create_order_embed(order, ws_url)
        if not embed:
            return
        
        payload = {
            "embeds": [embed],
            "content": content
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

