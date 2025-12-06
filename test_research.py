#!/usr/bin/env python3
"""Quick test script to run the soccer research bot once."""
import asyncio
import logging

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

async def main():
    from src.config import Settings
    from src.kalshi_api import get_soccer_markets, format_markets_for_analysis
    from src.llm_council import run_soccer_analysis
    
    settings = Settings()
    
    # Check required settings
    if not settings.openrouter_api_key:
        print("❌ Missing OPENROUTER_API_KEY in .env")
        print("   Get your key at https://openrouter.ai/")
        return
    
    if not settings.google_api_key:
        print("❌ Missing GOOGLE_API_KEY in .env")
        print("   Get your key at https://aistudio.google.com/apikey")
        return
    
    if not settings.kalshi_api_key_id:
        print("❌ Missing KALSHI_API_KEY_ID in .env")
        return
    
    print("✅ Configuration OK (OpenRouter + Google Gemini + Kalshi)")
    print()
    
    # Step 1: Fetch soccer markets from Kalshi
    print("📊 Fetching soccer markets from Kalshi...")
    markets = get_soccer_markets(
        key_id=settings.kalshi_api_key_id,
        private_key_pem=settings.kalshi_private_key_pem,
        ws_url=settings.kalshi_ws_url,
    )
    
    if not markets:
        print("❌ No soccer markets found on Kalshi right now.")
        return
    
    print(f"✅ Found {len(markets)} soccer markets")
    print()
    
    # Group markets by match (event)
    matches = {}
    for m in markets:
        # Extract match identifier from ticker (e.g., KXLALIGAGAME-25DEC08OSALEV-TIE -> 25DEC08OSALEV)
        ticker = m.get("ticker", "")
        parts = ticker.split("-")
        if len(parts) >= 2:
            match_id = parts[1]  # e.g., 25DEC08OSALEV
            if match_id not in matches:
                matches[match_id] = {
                    "title": m.get("title", "Unknown"),
                    "league": m.get("league", "unknown"),
                    "markets": []
                }
            matches[match_id]["markets"].append(m)
    
    # Show available matches
    print("="*60)
    print("📅 Available Matches:")
    print("="*60)
    
    match_list = list(matches.items())
    for i, (match_id, match_data) in enumerate(match_list):
        league_emoji = "🇪🇸" if match_data["league"] == "la_liga" else "🏴󠁧󠁢󠁥󠁮󠁧󠁿"
        print(f"  {i+1}. {league_emoji} {match_data['title']} ({len(match_data['markets'])} markets)")
    
    print()
    
    # Let user choose which match to analyze
    print("Which match do you want to analyze?")
    print()
    
    try:
        choice = input(f"Enter match number (1-{len(match_list)}): ").strip()
        choice_idx = int(choice) - 1
        if choice_idx < 0 or choice_idx >= len(match_list):
            print(f"Invalid choice. Using match 1...")
            choice_idx = 0
        selected_match = match_list[choice_idx]
    except (ValueError, KeyboardInterrupt):
        print("Using match 1...")
        selected_match = match_list[0]
    
    # Build market data for selected match
    match_id, match_data = selected_match
    selected_markets = match_data["markets"]
    
    print()
    print(f"📋 Analyzing: {match_data['title']}")
    print(f"   Markets: {len(selected_markets)}")
    
    # Format markets for analysis
    markets_text = format_markets_for_analysis(selected_markets)
    
    print()
    print("="*60)
    print("🧠 Running LLM Council Analysis")
    print("="*60)
    print()
    print("Pipeline stages:")
    print("  1️⃣  Research (Gemini + Google Search grounding) - ~30s")
    print("  2️⃣  Analysis (4 LLMs in parallel) - ~45s")
    print("  3️⃣  Review (peer review) - ~45s")
    print("  4️⃣  Synthesis (final recommendation) - ~20s")
    print()
    print("⏳ Total estimated time: 2-3 minutes...")
    print()
    
    try:
        result = await run_soccer_analysis(
            settings=settings,
            markets_text=markets_text,
        )
        
        print()
        print("="*60)
        print("🔍 RESEARCH FINDINGS (Gemini + Google Search)")
        print("="*60)
        # Show first 1500 chars of research
        research_preview = result.research[:1500]
        if len(result.research) > 1500:
            research_preview += "\n... [truncated, full research available]"
        print(research_preview)
        
        print()
        print("="*60)
        print("🎯 FINAL COUNCIL RECOMMENDATION")
        print("="*60)
        print(result.final_recommendation)
        
        print()
        print("="*60)
        print("✅ Analysis complete!")
        print("="*60)
        print()
        print("Cost estimate: ~$0.10-0.30 depending on response lengths")
        print()
        
        # Optional: show individual analyses
        response = input("Show individual model analyses? (y/n): ").strip().lower()
        if response == 'y':
            for model, analysis in result.analyses.items():
                print()
                print(f"{'='*60}")
                print(f"📝 {model}")
                print(f"{'='*60}")
                print(analysis[:2000] + "..." if len(analysis) > 2000 else analysis)
        
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
