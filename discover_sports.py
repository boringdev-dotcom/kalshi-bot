#!/usr/bin/env python3
"""Discover available sports and leagues on Kalshi."""
import json
from src.config import Settings
from src.kalshi_api import get_markets, SOCCER_SERIES_TICKERS

def main():
    settings = Settings()
    
    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_pem:
        print("❌ Missing Kalshi API credentials in .env")
        return
    
    print("🔍 Searching for soccer markets on Kalshi...")
    print()
    
    # Known soccer series tickers
    print("📋 Checking known soccer series tickers:")
    print(f"   La Liga: {SOCCER_SERIES_TICKERS['la_liga']}")
    print(f"   Premier League: {SOCCER_SERIES_TICKERS['premier_league']}")
    print()
    
    # Try fetching La Liga markets directly
    print("="*60)
    print("⚽ Fetching La Liga markets (KXLALIGAGAME)...")
    print("="*60)
    
    result = get_markets(
        key_id=settings.kalshi_api_key_id,
        private_key_pem=settings.kalshi_private_key_pem,
        ws_url=settings.kalshi_ws_url,
        status="open",
        series_ticker="KXLALIGAGAME",
        limit=50,
    )
    
    la_liga_markets = result.get("markets", [])
    print(f"\nFound {len(la_liga_markets)} La Liga markets")
    
    if la_liga_markets:
        for market in la_liga_markets[:5]:
            print(f"\n  📊 {market.get('title')}")
            print(f"     Ticker: {market.get('ticker')}")
            print(f"     Yes: {market.get('yes_bid')}¢ / {market.get('yes_ask')}¢")
            print(f"     Subtitle: {market.get('subtitle')}")
    
    # Try fetching Premier League markets
    print()
    print("="*60)
    print("⚽ Fetching Premier League markets (KXEPLGAME)...")
    print("="*60)
    
    result = get_markets(
        key_id=settings.kalshi_api_key_id,
        private_key_pem=settings.kalshi_private_key_pem,
        ws_url=settings.kalshi_ws_url,
        status="open",
        series_ticker="KXEPLGAME",
        limit=50,
    )
    
    epl_markets = result.get("markets", [])
    print(f"\nFound {len(epl_markets)} Premier League markets")
    
    if epl_markets:
        for market in epl_markets[:5]:
            print(f"\n  📊 {market.get('title')}")
            print(f"     Ticker: {market.get('ticker')}")
            print(f"     Yes: {market.get('yes_bid')}¢ / {market.get('yes_ask')}¢")
            print(f"     Subtitle: {market.get('subtitle')}")
    
    # If no markets found via series, search by ticker prefix
    if not la_liga_markets and not epl_markets:
        print()
        print("="*60)
        print("🔍 No markets via series_ticker, scanning all markets...")
        print("="*60)
        
        # Fetch more markets and filter by ticker prefix
        cursor = None
        soccer_markets = []
        pages = 0
        
        while pages < 10:  # Limit pages to avoid long waits
            result = get_markets(
                key_id=settings.kalshi_api_key_id,
                private_key_pem=settings.kalshi_private_key_pem,
                ws_url=settings.kalshi_ws_url,
                status="open",
                limit=200,
                cursor=cursor,
            )
            
            markets = result.get("markets", [])
            if not markets:
                break
            
            for market in markets:
                ticker = market.get("ticker", "").upper()
                title = market.get("title", "").upper()
                
                # Check for soccer-related tickers
                if any(prefix in ticker for prefix in ["KXLALIGA", "KXEPL", "KXPREMIER", "SOCCER", "FUTBOL"]):
                    soccer_markets.append(market)
                elif any(term in title for term in ["LA LIGA", "PREMIER LEAGUE", "LALIGA"]):
                    soccer_markets.append(market)
            
            cursor = result.get("cursor")
            if not cursor:
                break
            pages += 1
        
        print(f"\nFound {len(soccer_markets)} soccer-related markets by scanning")
        
        if soccer_markets:
            # Show unique series tickers found
            series = set(m.get("series_ticker") for m in soccer_markets if m.get("series_ticker"))
            print(f"\n📋 Series tickers found: {series}")
            
            for market in soccer_markets[:10]:
                print(f"\n  📊 {market.get('title')}")
                print(f"     Ticker: {market.get('ticker')}")
                print(f"     Series: {market.get('series_ticker')}")
    
    print()
    print("="*60)
    total = len(la_liga_markets) + len(epl_markets)
    print(f"✅ Total soccer markets found: {total}")
    print("="*60)


if __name__ == "__main__":
    main()
