#!/usr/bin/env python3
"""Quick test script to run the sports research bot once (Soccer or Basketball)."""
import asyncio
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def test_gemini_grounding():
    """Quick test to verify Gemini grounding is working."""
    from google import genai
    from google.genai import types
    import os
    
    # Load API key from environment or .env
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("GOOGLE_API_KEY")
    
    if not api_key:
        print("❌ GOOGLE_API_KEY not found in environment")
        return
    
    print("🔍 Testing Gemini with Google Search grounding...")
    print()
    
    client = genai.Client(api_key=api_key)
    
    grounding_tool = types.Tool(
        google_search=types.GoogleSearch()
    )
    
    config = types.GenerateContentConfig(
        tools=[grounding_tool]
    )
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Who won the euro 2024?",
        config=config,
    )
    
    print("✅ Response received!")
    print(f"📝 First 200 characters: {response.text[:200]}...")
    print()
    print(f"📊 Full response length: {len(response.text)} characters")
    print()
    return response.text


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
    md.append(f"- **Prompt Version:** {result.metadata.get('prompt_version', 'v1').upper()}")
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
    print("  1. ⚽ Soccer (La Liga, Premier League, UCL, MLS)")
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
    
    # League selection for soccer
    selected_leagues = None
    prompt_version = "v1"  # Default prompt version
    
    if sport == "soccer":
        print("="*60)
        print("⚽ Select Soccer League:")
        print("="*60)
        print("  1. 🇪🇸 La Liga (Spain)")
        print("  2. 🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League (England)")
        print("  3. 🏆 UEFA Champions League")
        print("  4. 🇺🇸 MLS (USA)")
        print("  5. �🇪 Bundesliga (Germany)")
        print("  6. �🌍 All Leagues")
        print()
        
        league_map = {
            "1": ["la_liga"],
            "2": ["premier_league"],
            "3": ["ucl"],
            "4": ["mls"],
            "5": ["bundesliga"],
            "6": ["la_liga", "premier_league", "ucl", "mls", "bundesliga"],
        }
        
        try:
            league_choice = input("Enter league number (1-5): ").strip()
            selected_leagues = league_map.get(league_choice, ["la_liga", "premier_league", "ucl", "mls", "bundesliga"])
        except (ValueError, KeyboardInterrupt):
            print("Defaulting to all leagues...")
            selected_leagues = ["la_liga", "premier_league", "ucl", "mls", "bundesliga"]
        
        print()
    
    # Prompt version selection (for both sports)
    print("="*60)
    print("📝 Select Prompt Version:")
    print("="*60)
    if sport == "soccer":
        print("  1. V1 (Original) - Standard analytical prompts")
        print("  2. V2 (Rewritten) - Sharp persona-based prompts with xG, PPDA focus")
        print("  3. V3 (Rewritten) - UCL specific prompts")
    else:
        print("  1. V1 (Original) - Standard analytical prompts")
        print("  2. V2 (Rewritten) - Four Factors, role-based analysis (Quant/Scout/Situationalist/Contrarian)")
    print()
    
    try:
        version_choice = input("Enter version number (1 or 2): ").strip()
        if version_choice == "2":
            prompt_version = "v2"
            if sport == "soccer":
                print("✅ Using V2 prompts (Sharp/Quantitative approach)")
            else:
                print("✅ Using V2 prompts (Four Factors/Role-based approach)")
        elif version_choice == "3":
            prompt_version = "v3"
            print("✅ Using V3 prompts (UCL specific approach)")
        else:
            prompt_version = "v1"
            print("✅ Using V1 prompts (Original approach)")
    except (ValueError, KeyboardInterrupt):
        print("Defaulting to V1 prompts...")
        prompt_version = "v1"
    
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
        league_names = ", ".join(l.replace("_", " ").title() for l in selected_leagues)
        print(f"📊 Fetching soccer markets from Kalshi ({league_names})...")
        markets = get_soccer_markets(
            key_id=settings.kalshi_api_key_id,
            private_key_pem=settings.kalshi_private_key_pem,
            ws_url=settings.kalshi_ws_url,
            leagues=selected_leagues,
        )
        sport_emoji = "⚽"
        sport_name = "soccer"
    
    if not markets:
        print(f"❌ No {sport_name} markets found on Kalshi right now.")
        return
    
    print(f"✅ Found {len(markets)} {sport_name} markets")
    print()
    
    # Debug: Show full raw market data to find game date field
    print("🔍 DEBUG - Full raw market data (first market):")
    if markets:
        import json
        print(json.dumps(markets[0], indent=2, default=str))
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
                # Extract date from close_time or expiration_time
                close_time = m.get("close_time") or m.get("expiration_time")
                match_date = None
                if close_time:
                    try:
                        # Parse ISO format datetime (e.g., "2024-12-08T20:00:00Z")
                        parsed_date = datetime.fromisoformat(close_time.replace("Z", "+00:00")).date()
                        
                        # Fix Kalshi's incorrect year (they sometimes return 2026 instead of 2025)
                        today = datetime.now().date()
                        if parsed_date.year > today.year + 1:
                            # Year is too far in the future, correct it
                            corrected_year = today.year if parsed_date.month >= today.month else today.year + 1
                            match_date = parsed_date.replace(year=corrected_year)
                        else:
                            match_date = parsed_date
                    except (ValueError, AttributeError):
                        pass
                
                # Fallback: parse date from match_id (e.g., 25DEC08OSALEV -> Dec 8, 2025)
                if not match_date and len(match_id) >= 7:
                    try:
                        year_prefix = match_id[:2]  # "25"
                        month_str = match_id[2:5]   # "DEC"
                        day_str = match_id[5:7]     # "08"
                        month_map = {
                            "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
                            "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
                            "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
                        }
                        if month_str in month_map:
                            year = 2000 + int(year_prefix)
                            month = month_map[month_str]
                            day = int(day_str)
                            match_date = datetime(year, month, day).date()
                    except (ValueError, IndexError):
                        pass
                
                matches[match_id] = {
                    "title": m.get("title", "Unknown"),
                    "league": m.get("league", "unknown"),
                    "date": match_date,
                    "markets": []
                }
            matches[match_id]["markets"].append(m)
    
    # Group matches by date
    matches_by_date = defaultdict(list)
    for match_id, match_data in matches.items():
        match_date = match_data.get("date")
        matches_by_date[match_date].append((match_id, match_data))
    
    # Sort dates (None at the end)
    sorted_dates = sorted(
        matches_by_date.keys(),
        key=lambda d: (d is None, d if d else datetime.max.date())
    )
    
    # Helper function for date display
    def format_date_header(d):
        if d is None:
            return "📅 Unknown Date"
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        if d == today:
            return f"📅 Today ({d.strftime('%a, %b %d')})"
        elif d == tomorrow:
            return f"📅 Tomorrow ({d.strftime('%a, %b %d')})"
        return f"📅 {d.strftime('%A, %b %d')}"
    
    # Build flat list for selection while displaying grouped by date
    match_list = []
    
    # Show available matches/games grouped by date
    print("="*60)
    print(f"📅 Available {sport_name.title()} Games:")
    print("="*60)
    
    game_number = 1
    for date_key in sorted_dates:
        date_matches = matches_by_date[date_key]
        # Sort matches within date by league
        date_matches.sort(key=lambda x: x[1].get("league", "zzz"))
        
        print()
        print(f"  {format_date_header(date_key)}")
        print(f"  {'-'*40}")
        
        for match_id, match_data in date_matches:
            league = match_data["league"]
            # Get appropriate emoji for the league
            if sport == "basketball":
                league_emoji = "🏀"
            else:
                league_emoji = {
                    "la_liga": "🇪🇸",
                    "premier_league": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
                    "mls": "🇺🇸",
                    "ucl": "🏆",
                    "bundesliga": "🇩🇪",
                }.get(league, "⚽")
            print(f"    {game_number}. {league_emoji} {match_data['title']} ({len(match_data['markets'])} markets)")
            match_list.append((match_id, match_data))
            game_number += 1
    
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
    if sport == "soccer":
        version_display = "V2 (Multi-Stage xG Research)" if prompt_version == "v2" else "V1 (Original)" if prompt_version == "v1" else "V3 (UCL specific)"
    else:
        version_display = "V2 (Multi-Stage Research)" if prompt_version == "v2" else "V1 (Original)"
    print(f"📝 Prompt Version: {version_display}")
    print()
    print("Pipeline stages:")
    if sport == "basketball" and prompt_version == "v2":
        print("  0️⃣  Multi-Stage Research (5 sequential Gemini calls):")
        print("      • Stage 1: Efficiency Metrics")
        print("      • Stage 2: Betting Lines & Market Data")
        print("      • Stage 3: Injuries & Roster Status")
        print("      • Stage 4: Situational & Scheduling Factors")
        print("      • Stage 5: Head-to-Head History")
        print("  1️⃣  Analysis (4 LLMs in parallel) - ~45s")
        print("  2️⃣  Review (peer review) - ~45s")
        print("  3️⃣  Synthesis (final recommendation) - ~20s")
        print()
        print("⏳ Total estimated time: 4-6 minutes (more thorough research)...")
    elif sport == "soccer" and prompt_version == "v2":
        print("  0️⃣  Multi-Stage Research (5 sequential Gemini calls):")
        print("      • Stage 1: Form & xG Metrics")
        print("      • Stage 2: Betting Lines & Market Data")
        print("      • Stage 3: Injuries & Team News")
        print("      • Stage 4: Situational & Motivation Factors")
        print("      • Stage 5: Tactical & Style Matchup")
        print("  1️⃣  Analysis (4 LLMs in parallel) - ~45s")
        print("  2️⃣  Review (peer review) - ~45s")
        print("  3️⃣  Synthesis (final recommendation) - ~20s")
        print()
        print("⏳ Total estimated time: 4-6 minutes (more thorough research)...")
    else:
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
            # Parse team names from match title for multi-stage research (v2)
            home_team = None
            away_team = None
            game_date_str = None
            
            if prompt_version == "v2":
                # Parse teams from title like "Boston vs Milwaukee Winner?"
                # Need to clean up suffixes like "Winner?", "Winner", "Total", etc.
                clean_title = match_title
                for suffix in [" Winner?", " Winner", " Total?", " Total", " Spread?", " Spread"]:
                    clean_title = clean_title.replace(suffix, "")
                
                if " vs " in clean_title:
                    parts = clean_title.split(" vs ")
                    if len(parts) == 2:
                        away_team = parts[0].strip()
                        home_team = parts[1].strip()
                        print(f"   Away Team: {away_team}")
                        print(f"   Home Team: {home_team}")
                
                # Format game date - handle season year vs calendar year
                # Kalshi uses "25DEC26" to mean the 24-25 season, not year 2025
                today = datetime.now().date()
                game_date_str = None
                
                # Try to get date from market's close_time first (most accurate)
                for m in selected_markets:
                    close_time = m.get("close_time") or m.get("expiration_time")
                    if close_time:
                        try:
                            actual_date = datetime.fromisoformat(close_time.replace("Z", "+00:00")).date()
                            game_date_str = actual_date.strftime("%B %d, %Y")
                            break
                        except (ValueError, AttributeError):
                            pass
                
                # Fallback to parsed date with year correction
                if not game_date_str and match_data.get("date"):
                    parsed_date = match_data["date"]
                    # If parsed date is more than 6 months in the future, subtract a year
                    if parsed_date > today + timedelta(days=180):
                        corrected_date = parsed_date.replace(year=parsed_date.year - 1)
                        game_date_str = corrected_date.strftime("%B %d, %Y")
                    else:
                        game_date_str = parsed_date.strftime("%B %d, %Y")
                
                # Final fallback to today
                if not game_date_str:
                    game_date_str = today.strftime("%B %d, %Y")
                game_date_str = today.strftime("%B %d, %Y")
                print(f"   Game Date: {game_date_str}")
                
                print()
                print("🔬 Using MULTI-STAGE research (5 sequential stages)")
                print()
            
            result = await run_basketball_analysis(
                settings=settings,
                markets_text=markets_text,
                prompt_version=prompt_version,
                home_team=home_team,
                away_team=away_team,
                game_date=game_date_str,
            )
        else:
            # Parse team names from match title for multi-stage research (v2)
            home_team = None
            away_team = None
            match_date_str = None
            competition = None
            
            if prompt_version == "v2":
                # Parse teams from title like "Barcelona vs Real Madrid Winner?"
                # Need to clean up suffixes like "Winner?", "Winner", "Tie?", etc.
                clean_title = match_title
                for suffix in [" Winner?", " Winner", " Tie?", " Tie", " Draw?", " Draw"]:
                    clean_title = clean_title.replace(suffix, "")
                
                if " vs " in clean_title:
                    parts = clean_title.split(" vs ")
                    if len(parts) == 2:
                        # In soccer, format is usually "Away vs Home" on Kalshi
                        away_team = parts[0].strip()
                        home_team = parts[1].strip()
                        print(f"   Away Team: {away_team}")
                        print(f"   Home Team: {home_team}")
                
                # Get competition from league field
                league = match_data.get("league", "unknown")
                competition_map = {
                    "la_liga": "La Liga",
                    "premier_league": "Premier League",
                    "ucl": "UEFA Champions League",
                    "mls": "MLS",
                }
                competition = competition_map.get(league, league.replace("_", " ").title())
                print(f"   Competition: {competition}")
                
                # Format match date
                today = datetime.now().date()
                match_date_str = None
                
                # Try to get date from market's close_time first (most accurate)
                for m in selected_markets:
                    close_time = m.get("close_time") or m.get("expiration_time")
                    if close_time:
                        try:
                            actual_date = datetime.fromisoformat(close_time.replace("Z", "+00:00")).date()
                            match_date_str = actual_date.strftime("%B %d, %Y")
                            break
                        except (ValueError, AttributeError):
                            pass
                
                # Fallback to parsed date
                if not match_date_str and match_data.get("date"):
                    parsed_date = match_data["date"]
                    match_date_str = parsed_date.strftime("%B %d, %Y")
                
                # Final fallback to today
                if not match_date_str:
                    match_date_str = today.strftime("%B %d, %Y")

                match_date_str = "December 20, 2025"
                print(f"   Match Date: {match_date_str}")
                print()
                print("🔬 Using MULTI-STAGE research (5 sequential stages)")
                print()
            
            result = await run_soccer_analysis(
                settings=settings,
                markets_text=markets_text,
                prompt_version=prompt_version,
                home_team=home_team,
                away_team=away_team,
                competition=competition,
                match_date=match_date_str,
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
        
        # Create filename from match title (include prompt version)
        date_str = datetime.now().strftime("%Y%m%d")
        safe_title = sanitize_filename(match_title)
        filename = f"{safe_title}_{prompt_version}_{date_str}.md"
        
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
    if len(sys.argv) > 1 and sys.argv[1] == "test-grounding":
        test_gemini_grounding()
    else:
        asyncio.run(main())
