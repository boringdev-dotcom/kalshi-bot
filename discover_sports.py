#!/usr/bin/env python3
"""Discover available sports and leagues on Kalshi."""
import json
from collections import defaultdict
from src.config import Settings
from src.kalshi_api import get_markets, get_sports_filters, SOCCER_SERIES_TICKERS

def main():
    settings = Settings()
    
    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_pem:
        print("❌ Missing Kalshi API credentials in .env")
        return
    
    print("🔍 Discovering all soccer series tickers on Kalshi...")
    print()
    
    # First, try the sports filters API
    print("="*60)
    print("📡 Checking sports filters API...")
    print("="*60)
    
    sports_filters = get_sports_filters(
        key_id=settings.kalshi_api_key_id,
        private_key_pem=settings.kalshi_private_key_pem,
        ws_url=settings.kalshi_ws_url,
    )
    
    if sports_filters:
        print("\n📋 Sports filters response:")
        print(json.dumps(sports_filters, indent=2))
    else:
        print("\n⚠️  No sports filters returned (API may not support this)")
    
    print()
    
    # Scan all markets to discover soccer-related series tickers
    print("="*60)
    print("📡 Scanning all open markets for soccer series tickers...")
    print("="*60)
    
    cursor = None
    soccer_markets = []
    all_series = set()
    all_sports_series = set()  # Any sports-related series
    series_to_markets = defaultdict(list)
    sample_markets = []  # Keep some samples to understand naming
    pages = 0
    total_scanned = 0
    
    # Soccer-related prefixes to look for in tickers and series
    soccer_prefixes = ["KXLALIGA", "KXEPL", "KXPREMIER", "LALIGA", "EPL", "SOCCER", "FUTBOL", "MLS", "CHAMPIONS", "BUNDESLIGA", "SERIE", "KXUCLGAME"]
    soccer_terms = ["LA LIGA", "PREMIER LEAGUE", "LALIGA", "EPL", "SOCCER", "FUTBOL", "FOOTBALL", "MLS", "CHAMPIONS LEAGUE", "BUNDESLIGA", "SERIE A", "VS", "SPREAD", "ARSENAL", "MANCHESTER", "LIVERPOOL", "CHELSEA", "REAL MADRID", "BARCELONA"]
    
    # Broader sports terms to help discover naming patterns
    sports_prefixes = ["KX", "GAME", "SPREAD", "NFL", "NBA", "NHL", "MLB", "UFC", "BOXING", "TENNIS", "GOLF", "SPORT"]
    
    while pages < 20:  # Scan up to 20 pages
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
        
        total_scanned += len(markets)
        
        for market in markets:
            ticker = market.get("ticker", "").upper()
            series_ticker = market.get("series_ticker", "").upper()
            title = market.get("title", "").upper()
            
            # Keep some sample markets for debugging
            if len(sample_markets) < 50:
                sample_markets.append(market)
            
            # Track any sports-looking series
            if series_ticker and any(p in series_ticker for p in sports_prefixes):
                all_sports_series.add(series_ticker)
            
            # Check if this is a soccer-related market
            is_soccer = (
                any(prefix in ticker for prefix in soccer_prefixes) or
                any(prefix in series_ticker for prefix in soccer_prefixes) or
                any(term in title for term in soccer_terms)
            )
            
            if is_soccer and series_ticker:
                all_series.add(series_ticker)
                soccer_markets.append(market)
                series_to_markets[series_ticker].append(market)
        
        cursor = result.get("cursor")
        if not cursor:
            break
        pages += 1
        print(f"   Scanned {total_scanned} markets...", end="\r")
    
    print(f"\n\n✅ Scanned {total_scanned} total markets")
    print(f"⚽ Found {len(soccer_markets)} soccer-related markets")
    print()
    
    # Display discovered series tickers
    print("="*60)
    print("📋 DISCOVERED SOCCER SERIES TICKERS:")
    print("="*60)
    
    if all_series:
        # Categorize by league
        la_liga_series = sorted([s for s in all_series if "LALIGA" in s])
        epl_series = sorted([s for s in all_series if "EPL" in s or "PREMIER" in s])
        other_series = sorted([s for s in all_series if s not in la_liga_series and s not in epl_series])
        
        if la_liga_series:
            print("\n🇪🇸 La Liga Series:")
            for series in la_liga_series:
                count = len(series_to_markets[series])
                print(f"   - {series} ({count} markets)")
        
        if epl_series:
            print("\n🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League Series:")
            for series in epl_series:
                count = len(series_to_markets[series])
                print(f"   - {series} ({count} markets)")
        
        if other_series:
            print("\n🌍 Other Soccer Series:")
            for series in other_series:
                count = len(series_to_markets[series])
                print(f"   - {series} ({count} markets)")
        
        # Show sample markets from each series
        print()
        print("="*60)
        print("📊 SAMPLE MARKETS BY SERIES:")
        print("="*60)
        
        for series in sorted(all_series):
            markets = series_to_markets[series]
            print(f"\n{series}:")
            for market in markets[:3]:  # Show up to 3 samples per series
                print(f"  📈 {market.get('title')}")
                print(f"     Ticker: {market.get('ticker')}")
                print(f"     Subtitle: {market.get('subtitle', 'N/A')}")
                print(f"     Yes: {market.get('yes_bid')}¢ / {market.get('yes_ask')}¢")
        
        # Print code snippet for updating SOCCER_SERIES_TICKERS
        print()
        print("="*60)
        print("📝 SUGGESTED CODE UPDATE for kalshi_api.py:")
        print("="*60)
        print()
        print("SOCCER_SERIES_TICKERS = {")
        if la_liga_series:
            print(f'    "la_liga": {la_liga_series},')
        if epl_series:
            print(f'    "premier_league": {epl_series},')
        print("}")
    else:
        print("\n⚠️  No soccer series tickers found!")
        print("   This might mean no soccer markets are currently open.")
        
        # Show sports-related series that were found (helps understand naming)
        if all_sports_series:
            print()
            print("="*60)
            print("🏀 OTHER SPORTS SERIES FOUND (for reference):")
            print("="*60)
            for series in sorted(all_sports_series)[:30]:
                print(f"   - {series}")
        
        # Search sample markets for anything sports-related
        sports_keywords = ["GAME", "SPREAD", "WINNER", "NFL", "NBA", "NHL", "MLB", "SOCCER", 
                         "FOOTBALL", "VS", "MATCH", "TEAM", "SCORE", "GOALS", "LEAGUE"]
        sports_found = []
        for market in sample_markets:
            ticker = market.get("ticker", "").upper()
            title = market.get("title", "").upper()
            series = market.get("series_ticker", "").upper() if market.get("series_ticker") else ""
            combined = f"{ticker} {title} {series}"
            if any(kw in combined for kw in sports_keywords):
                sports_found.append(market)
        
        if sports_found:
            print()
            print("="*60)
            print("🏈 SPORTS-RELATED MARKETS FOUND IN SAMPLES:")
            print("="*60)
            for market in sports_found[:20]:
                print(f"\n  📈 {market.get('title')}")
                print(f"     Ticker: {market.get('ticker')}")
                print(f"     Series: {market.get('series_ticker')}")
                print(f"     Subtitle: {market.get('subtitle', 'N/A')}")
        
        # Show sample markets to understand naming conventions
        print()
        print("="*60)
        print("📊 SAMPLE MARKETS (to understand naming):")
        print("="*60)
        for market in sample_markets[:15]:
            print(f"\n  📈 {market.get('title')}")
            print(f"     Ticker: {market.get('ticker')}")
            print(f"     Series: {market.get('series_ticker')}")
            print(f"     Subtitle: {market.get('subtitle', 'N/A')}")
    
    # Try fetching directly from known series tickers
    print()
    print("="*60)
    print("🎯 TRYING DIRECT SERIES TICKER FETCHES:")
    print("="*60)
    
    known_series = [
        "KXLALIGAGAME", "KXLALIGASPREAD", "KXLALIGA", "KXUCLGAME", "KXUCLSPREAD", "KXUCLTOTAL", "KXUCLBTTS",
        "KXEPLGAME", "KXEPLSPREAD", "KXEPL",
        "KXNFLGAME", "KXNFLSPREAD", 
        "KXNBAGAME", "KXNBASPREAD",
        "KXCRICKETT20IMATCH", "KXCRICKETIPLMATCH",  # Cricket series
    ]
    
    for series in known_series:
        result = get_markets(
            key_id=settings.kalshi_api_key_id,
            private_key_pem=settings.kalshi_private_key_pem,
            ws_url=settings.kalshi_ws_url,
            status="open",
            series_ticker=series,
            limit=10,
        )
        markets = result.get("markets", [])
        if markets:
            print(f"\n✅ {series}: Found {len(markets)} markets!")
            for m in markets[:3]:
                print(f"    - {m.get('ticker')}: {m.get('title')}")
        else:
            print(f"   ❌ {series}: No markets")
    
    print()
    print("="*60)
    print(f"✅ Discovery complete!")
    print("="*60)


if __name__ == "__main__":
    main()
