#!/usr/bin/env python3
"""Quick test script to run the sports research bot once (Soccer or Basketball)."""
import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def sanitize_filename(text: str) -> str:
    """Convert text to a safe filename."""
    # Remove or replace invalid characters
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    # Replace spaces and special chars with underscores
    text = re.sub(r'[\s\-\.]+', '_', text)
    # Remove any non-ASCII characters
    text = text.encode('ascii', 'ignore').decode()
    # Limit length
    return text[:50].strip('_').lower()


def generate_markdown_report(
    result,
    match_title: str,
    sport: str,
    markets_text: str,
    selected_markets: list,
) -> str:
    """Generate a markdown report from the analysis result."""
    sport_emoji = "🏀" if sport == "basketball" else "⚽"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    md = []
    
    # Header
    md.append(f"# {sport_emoji} {match_title}")
    md.append("")
    md.append(f"**Sport:** {sport.title()}")
    md.append(f"**Generated:** {timestamp}")
    md.append(f"**Markets Analyzed:** {len(selected_markets)}")
    md.append("")
    
    # Table of Contents
    md.append("## Table of Contents")
    md.append("- [Final Recommendation](#final-recommendation)")
    md.append("- [Research Findings](#research-findings)")
    md.append("- [Individual Analyses](#individual-analyses)")
    md.append("- [Peer Reviews](#peer-reviews)")
    md.append("- [Market Data](#market-data)")
    md.append("")
    
    # Final Recommendation (most important, at the top)
    md.append("---")
    md.append("")
    md.append("## Final Recommendation")
    md.append("")
    md.append(result.final_recommendation)
    md.append("")
    
    # Research Findings
    md.append("---")
    md.append("")
    md.append("## Research Findings")
    md.append("")
    md.append("*Data gathered via Gemini with Google Search grounding*")
    md.append("")
    md.append(result.research)
    md.append("")
    
    # Individual Analyses
    md.append("---")
    md.append("")
    md.append("## Individual Analyses")
    md.append("")
    
    for model, analysis in result.analyses.items():
        model_display = model.split("/")[-1] if "/" in model else model
        md.append(f"### {model_display}")
        md.append("")
        md.append(analysis)
        md.append("")
    
    # Peer Reviews
    md.append("---")
    md.append("")
    md.append("## Peer Reviews")
    md.append("")
    
    for model, review in result.reviews.items():
        model_display = model.split("/")[-1] if "/" in model else model
        md.append(f"### Review by {model_display}")
        md.append("")
        md.append(review)
        md.append("")
    
    # Market Data
    md.append("---")
    md.append("")
    md.append("## Market Data")
    md.append("")
    md.append("```")
    md.append(markets_text)
    md.append("```")
    md.append("")
    
    # Metadata
    md.append("---")
    md.append("")
    md.append("## Metadata")
    md.append("")
    md.append(f"- **Research Model:** {result.metadata.get('research_model', 'N/A')}")
    md.append(f"- **Council Models:** {', '.join(result.metadata.get('council_models', []))}")
    md.append(f"- **Chairman Model:** {result.metadata.get('chairman_model', 'N/A')}")
    md.append(f"- **Sport:** {result.metadata.get('sport', sport)}")
    md.append("")
    
    return "\n".join(md)


async def main():
    from src.config import Settings
    from src.kalshi_api import (
        get_soccer_markets,
        get_basketball_markets,
        format_markets_for_analysis,
        format_basketball_markets_for_analysis,
    )
    from src.llm_council import run_soccer_analysis, run_basketball_analysis
    
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
    
    # Sport selection
    print("="*60)
    print("🏆 Select Sport to Analyze:")
    print("="*60)
    print("  1. ⚽ Soccer (La Liga, Premier League, MLS)")
    print("  2. 🏀 Basketball (NBA)")
    print()
    
    try:
        sport_choice = input("Enter sport number (1 or 2): ").strip()
        if sport_choice == "2":
            sport = "basketball"
        else:
            sport = "soccer"
    except (ValueError, KeyboardInterrupt):
        print("Defaulting to soccer...")
        sport = "soccer"
    
    print()
    
    # Fetch markets based on selected sport
    if sport == "basketball":
        print("📊 Fetching NBA basketball markets from Kalshi...")
        markets = get_basketball_markets(
            key_id=settings.kalshi_api_key_id,
            private_key_pem=settings.kalshi_private_key_pem,
            ws_url=settings.kalshi_ws_url,
        )
        sport_emoji = "🏀"
        sport_name = "basketball"
    else:
        print("📊 Fetching soccer markets from Kalshi...")
        markets = get_soccer_markets(
            key_id=settings.kalshi_api_key_id,
            private_key_pem=settings.kalshi_private_key_pem,
            ws_url=settings.kalshi_ws_url,
        )
        sport_emoji = "⚽"
        sport_name = "soccer"
    
    if not markets:
        print(f"❌ No {sport_name} markets found on Kalshi right now.")
        return
    
    print(f"✅ Found {len(markets)} {sport_name} markets")
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
    
    # Show available matches/games
    print("="*60)
    print(f"📅 Available {sport_name.title()} Games:")
    print("="*60)
    
    match_list = list(matches.items())
    for i, (match_id, match_data) in enumerate(match_list):
        league = match_data["league"]
        # Get appropriate emoji for the league
        if sport == "basketball":
            league_emoji = "🏀"
        else:
            league_emoji = {
                "la_liga": "🇪🇸",
                "premier_league": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
                "mls": "🇺🇸",
            }.get(league, "⚽")
        print(f"  {i+1}. {league_emoji} {match_data['title']} ({len(match_data['markets'])} markets)")
    
    print()
    
    # Let user choose which match to analyze
    print("Which game do you want to analyze?")
    print()
    
    try:
        choice = input(f"Enter game number (1-{len(match_list)}): ").strip()
        choice_idx = int(choice) - 1
        if choice_idx < 0 or choice_idx >= len(match_list):
            print(f"Invalid choice. Using game 1...")
            choice_idx = 0
        selected_match = match_list[choice_idx]
    except (ValueError, KeyboardInterrupt):
        print("Using game 1...")
        selected_match = match_list[0]
    
    # Build market data for selected match
    match_id, match_data = selected_match
    selected_markets = match_data["markets"]
    match_title = match_data["title"]
    
    print()
    print(f"📋 Analyzing: {match_title}")
    print(f"   Markets: {len(selected_markets)}")
    
    # Format markets for analysis
    if sport == "basketball":
        markets_text = format_basketball_markets_for_analysis(selected_markets)
    else:
        markets_text = format_markets_for_analysis(selected_markets)
    
    print()
    print("="*60)
    print(f"{sport_emoji} Running LLM Council {sport_name.title()} Analysis")
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
        # Run the appropriate analysis
        if sport == "basketball":
            result = await run_basketball_analysis(
                settings=settings,
                markets_text=markets_text,
            )
        else:
            result = await run_soccer_analysis(
                settings=settings,
                markets_text=markets_text,
            )
        
        # Generate markdown report
        print()
        print("📝 Generating markdown report...")
        
        markdown_content = generate_markdown_report(
            result=result,
            match_title=match_title,
            sport=sport,
            markets_text=markets_text,
            selected_markets=selected_markets,
        )
        
        # Create filename from match title
        date_str = datetime.now().strftime("%Y%m%d")
        safe_title = sanitize_filename(match_title)
        filename = f"{safe_title}_{date_str}.md"
        
        # Save to file
        output_path = Path(filename)
        output_path.write_text(markdown_content, encoding="utf-8")
        
        print()
        print("="*60)
        print("✅ Analysis complete!")
        print("="*60)
        print()
        print(f"📄 Report saved to: {output_path.absolute()}")
        print()
        print("Cost estimate: ~$0.10-0.30 depending on response lengths")
        print()
        
        # Show preview of final recommendation
        print("="*60)
        print("🎯 FINAL RECOMMENDATION (Preview)")
        print("="*60)
        preview = result.final_recommendation[:1500]
        if len(result.final_recommendation) > 1500:
            preview += "\n\n... [See full report in markdown file]"
        print(preview)
        print()
        
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
