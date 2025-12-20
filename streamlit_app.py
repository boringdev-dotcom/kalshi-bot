#!/usr/bin/env python3
"""Streamlit web app for Kalshi sports betting research."""
import asyncio
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

import streamlit as st

# Page config must be first Streamlit command
st.set_page_config(
    page_title="Kalshi Sports Research",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for better aesthetics
st.markdown("""
<style>
    /* Dark theme adjustments */
    .stApp {
        background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
    }
    
    /* Header styling */
    h1 {
        background: linear-gradient(90deg, #00d4ff, #7b2cbf);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Card-like containers */
    .stExpander {
        background-color: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
    }
    
    /* Button styling */
    .stButton > button {
        background: linear-gradient(90deg, #00d4ff, #7b2cbf);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 20px rgba(0, 212, 255, 0.3);
    }
    
    /* Selectbox styling */
    .stSelectbox > div > div {
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 8px;
    }
    
    /* Status container */
    .stStatus {
        background-color: rgba(255, 255, 255, 0.02);
        border-radius: 12px;
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    
    .stTabs [data-baseweb="tab"] {
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 8px 8px 0 0;
        padding: 10px 20px;
    }
    
    /* Metric cards */
    [data-testid="stMetricValue"] {
        font-size: 2rem;
        background: linear-gradient(90deg, #00d4ff, #7b2cbf);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    /* Code blocks */
    .stCodeBlock {
        background-color: rgba(0, 0, 0, 0.3);
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


def sanitize_filename(text: str) -> str:
    """Convert text to a safe filename."""
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = re.sub(r'[\s\-\.]+', '_', text)
    text = text.encode('ascii', 'ignore').decode()
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
    
    md.append(f"# {sport_emoji} {match_title}")
    md.append("")
    md.append(f"**Sport:** {sport.title()}")
    md.append(f"**Generated:** {timestamp}")
    md.append(f"**Markets Analyzed:** {len(selected_markets)}")
    md.append("")
    
    md.append("## Table of Contents")
    md.append("- [Final Recommendation](#final-recommendation)")
    md.append("- [Research Findings](#research-findings)")
    md.append("- [Individual Analyses](#individual-analyses)")
    md.append("- [Peer Reviews](#peer-reviews)")
    md.append("- [Market Data](#market-data)")
    md.append("")
    
    md.append("---")
    md.append("")
    md.append("## Final Recommendation")
    md.append("")
    md.append(result.final_recommendation)
    md.append("")
    
    md.append("---")
    md.append("")
    md.append("## Research Findings")
    md.append("")
    md.append("*Data gathered via Gemini with Google Search grounding*")
    md.append("")
    md.append(result.research)
    md.append("")
    
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
    
    md.append("---")
    md.append("")
    md.append("## Market Data")
    md.append("")
    md.append("```")
    md.append(markets_text)
    md.append("```")
    md.append("")
    
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


def parse_match_date(close_time: Optional[str], match_id: str) -> Optional[datetime]:
    """Parse match date from close_time or match_id."""
    match_date = None
    
    if close_time:
        try:
            parsed_date = datetime.fromisoformat(close_time.replace("Z", "+00:00")).date()
            today = datetime.now().date()
            if parsed_date.year > today.year + 1:
                corrected_year = today.year if parsed_date.month >= today.month else today.year + 1
                match_date = parsed_date.replace(year=corrected_year)
            else:
                match_date = parsed_date
        except (ValueError, AttributeError):
            pass
    
    # Fallback: parse date from match_id
    if not match_date and len(match_id) >= 7:
        try:
            year_prefix = match_id[:2]
            month_str = match_id[2:5]
            day_str = match_id[5:7]
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
    
    return match_date


def group_markets_by_match(markets: List[Dict]) -> Dict[str, Dict]:
    """Group markets by match/game."""
    matches = {}
    
    for m in markets:
        ticker = m.get("ticker", "")
        parts = ticker.split("-")
        if len(parts) >= 2:
            match_id = parts[1]
            if match_id not in matches:
                close_time = m.get("close_time") or m.get("expiration_time")
                match_date = parse_match_date(close_time, match_id)
                
                matches[match_id] = {
                    "title": m.get("title", "Unknown"),
                    "league": m.get("league", "unknown"),
                    "date": match_date,
                    "markets": []
                }
            matches[match_id]["markets"].append(m)
    
    return matches


def format_date_header(d: Optional[datetime]) -> str:
    """Format date for display."""
    if d is None:
        return "📅 Unknown Date"
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    if d == today:
        return f"📅 Today ({d.strftime('%a, %b %d')})"
    elif d == tomorrow:
        return f"📅 Tomorrow ({d.strftime('%a, %b %d')})"
    return f"📅 {d.strftime('%A, %b %d')}"


def get_league_emoji(sport: str, league: str) -> str:
    """Get emoji for league."""
    if sport == "basketball":
        return "🏀"
    return {
        "la_liga": "🇪🇸",
        "premier_league": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "mls": "🇺🇸",
        "ucl": "🏆",
        "bundesliga": "🇩🇪",
    }.get(league, "⚽")


def parse_teams_from_title(title: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse away and home teams from match title."""
    clean_title = title
    for suffix in [" Winner?", " Winner", " Total?", " Total", " Spread?", " Spread", " Tie?", " Tie", " Draw?", " Draw"]:
        clean_title = clean_title.replace(suffix, "")
    
    if " vs " in clean_title:
        parts = clean_title.split(" vs ")
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
    
    return None, None


@st.cache_data(ttl=300)
def fetch_markets(_settings, sport: str, leagues: Optional[List[str]] = None) -> List[Dict]:
    """Fetch markets from Kalshi (cached for 5 minutes)."""
    from src.kalshi_api import get_soccer_markets, get_basketball_markets
    
    if sport == "basketball":
        return get_basketball_markets(
            key_id=_settings.kalshi_api_key_id,
            private_key_pem=_settings.kalshi_private_key_pem,
            ws_url=_settings.kalshi_ws_url,
        )
    else:
        return get_soccer_markets(
            key_id=_settings.kalshi_api_key_id,
            private_key_pem=_settings.kalshi_private_key_pem,
            ws_url=_settings.kalshi_ws_url,
            leagues=leagues,
        )


async def run_analysis_async(
    settings,
    sport: str,
    markets_text: str,
    prompt_version: str,
    home_team: Optional[str],
    away_team: Optional[str],
    match_date_str: str,
    competition: Optional[str] = None,
):
    """Run analysis asynchronously."""
    from src.llm_council import run_basketball_analysis, run_soccer_analysis
    
    if sport == "basketball":
        return await run_basketball_analysis(
            settings=settings,
            markets_text=markets_text,
            prompt_version=prompt_version,
            home_team=home_team,
            away_team=away_team,
            game_date=match_date_str,
        )
    else:
        return await run_soccer_analysis(
            settings=settings,
            markets_text=markets_text,
            prompt_version=prompt_version,
            home_team=home_team,
            away_team=away_team,
            competition=competition,
            match_date=match_date_str,
        )


def main():
    # Header
    st.title("🎯 Kalshi Sports Research")
    st.markdown("*AI-powered sports betting analysis using LLM Council*")
    
    # Load settings
    try:
        from src.config import Settings
        settings = Settings()
    except Exception as e:
        st.error(f"Failed to load settings: {e}")
        st.info("Make sure environment variables are set: OPENROUTER_API_KEY, GOOGLE_API_KEY, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PEM")
        return
    
    # Validate required settings
    missing = []
    if not settings.openrouter_api_key:
        missing.append("OPENROUTER_API_KEY")
    if not settings.google_api_key:
        missing.append("GOOGLE_API_KEY")
    if not settings.kalshi_api_key_id:
        missing.append("KALSHI_API_KEY_ID")
    
    if missing:
        st.error(f"Missing required environment variables: {', '.join(missing)}")
        return
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Sport selection
        sport = st.selectbox(
            "🏆 Select Sport",
            options=["basketball", "soccer"],
            format_func=lambda x: "🏀 Basketball (NBA)" if x == "basketball" else "⚽ Soccer",
            index=0,
        )
        
        # League selection for soccer
        selected_leagues = None
        if sport == "soccer":
            league_options = {
                "la_liga": "🇪🇸 La Liga",
                "premier_league": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League",
                "ucl": "🏆 Champions League",
                "mls": "🇺🇸 MLS",
                "bundesliga": "🇩🇪 Bundesliga",
            }
            selected_leagues = st.multiselect(
                "🌍 Select Leagues",
                options=list(league_options.keys()),
                default=["la_liga", "premier_league", "ucl"],
                format_func=lambda x: league_options[x],
            )
            if not selected_leagues:
                selected_leagues = list(league_options.keys())
        
        # Prompt version
        st.markdown("---")
        if sport == "soccer":
            version_options = {
                "v1": "V1 - Standard analytical",
                "v2": "V2 - xG/PPDA focus",
                "v3": "V3 - UCL specific",
            }
        else:
            version_options = {
                "v1": "V1 - Standard analytical",
                "v2": "V2 - Four Factors analysis",
            }
        
        prompt_version = st.selectbox(
            "📝 Prompt Version",
            options=list(version_options.keys()),
            format_func=lambda x: version_options[x],
            index=1,  # Default to v2
        )
        
        st.markdown("---")
        st.markdown("### ℹ️ About")
        st.markdown("""
        This tool uses a **4-stage LLM Council** pipeline:
        1. 🔍 Research (Gemini + Google Search)
        2. 🧠 Analysis (4 LLMs in parallel)
        3. 👥 Peer Review
        4. 🎯 Final Synthesis
        """)
        
        if prompt_version == "v2":
            st.info("V2 uses 5-stage research for deeper analysis. Takes 4-6 minutes.")
        else:
            st.info("V1 uses single-stage research. Takes 2-3 minutes.")
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("📊 Available Games")
        
        # Fetch markets button
        if st.button("🔄 Refresh Markets", use_container_width=True):
            st.cache_data.clear()
        
        with st.spinner("Fetching markets from Kalshi..."):
            try:
                markets = fetch_markets(settings, sport, selected_leagues)
            except Exception as e:
                st.error(f"Failed to fetch markets: {e}")
                return
        
        if not markets:
            st.warning(f"No {sport} markets found on Kalshi right now.")
            return
        
        st.success(f"Found {len(markets)} {sport} markets")
        
        # Group markets by match
        matches = group_markets_by_match(markets)
        
        # Group by date
        matches_by_date = defaultdict(list)
        for match_id, match_data in matches.items():
            match_date = match_data.get("date")
            matches_by_date[match_date].append((match_id, match_data))
        
        # Sort dates
        sorted_dates = sorted(
            matches_by_date.keys(),
            key=lambda d: (d is None, d if d else datetime.max.date())
        )
        
        # Build options for selectbox
        game_options = []
        for date_key in sorted_dates:
            date_matches = matches_by_date[date_key]
            date_matches.sort(key=lambda x: x[1].get("league", "zzz"))
            
            for match_id, match_data in date_matches:
                league = match_data["league"]
                emoji = get_league_emoji(sport, league)
                date_str = format_date_header(match_data.get("date"))
                label = f"{emoji} {match_data['title']} | {date_str} | {len(match_data['markets'])} markets"
                game_options.append((match_id, match_data, label))
        
        # Game selector
        selected_idx = st.selectbox(
            "🎮 Select Game to Analyze",
            options=range(len(game_options)),
            format_func=lambda i: game_options[i][2],
        )
        
        if selected_idx is not None:
            match_id, match_data, _ = game_options[selected_idx]
            selected_markets = match_data["markets"]
            match_title = match_data["title"]
            
            # Show selected game info
            with st.expander("📋 Selected Game Details", expanded=True):
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.metric("Game", match_title)
                with col_b:
                    st.metric("Markets", len(selected_markets))
                with col_c:
                    league_display = match_data["league"].replace("_", " ").title()
                    st.metric("League", league_display)
    
    with col2:
        st.header("🚀 Run Analysis")
        
        if selected_idx is None:
            st.info("Select a game to analyze")
            return
        
        # Parse team info
        away_team, home_team = parse_teams_from_title(match_title)
        
        if away_team and home_team:
            st.markdown(f"**Away:** {away_team}")
            st.markdown(f"**Home:** {home_team}")
        
        # Competition for soccer
        competition = None
        if sport == "soccer":
            league = match_data.get("league", "unknown")
            competition_map = {
                "la_liga": "La Liga",
                "premier_league": "Premier League",
                "ucl": "UEFA Champions League",
                "mls": "MLS",
                "bundesliga": "Bundesliga",
            }
            competition = competition_map.get(league, league.replace("_", " ").title())
            st.markdown(f"**Competition:** {competition}")
        
        # Game date
        today = datetime.now().date()
        game_date = match_data.get("date") or today
        match_date_str = datetime.now().strftime("%B %d, %Y")
        st.markdown(f"**Date:** {datetime.now().strftime('%B %d, %Y')}")
        
        st.markdown("---")
        
        # Run analysis button
        if st.button("🎯 Run Analysis", type="primary", use_container_width=True):
            from src.kalshi_api import format_markets_for_analysis, format_basketball_markets_for_analysis
            
            # Format markets
            if sport == "basketball":
                markets_text = format_basketball_markets_for_analysis(selected_markets)
            else:
                markets_text = format_markets_for_analysis(selected_markets)
            
            # Run analysis with status updates
            with st.status("🔬 Running LLM Council Analysis...", expanded=True) as status:
                try:
                    if prompt_version == "v2":
                        st.write("📊 Stage 0: Multi-stage research (5 stages)...")
                    else:
                        st.write("🔍 Stage 1: Research with Gemini...")
                    
                    # Run async analysis
                    result = asyncio.run(run_analysis_async(
                        settings=settings,
                        sport=sport,
                        markets_text=markets_text,
                        prompt_version=prompt_version,
                        home_team=home_team,
                        away_team=away_team,
                        match_date_str=match_date_str,
                        competition=competition,
                    ))
                    
                    st.write("✅ Analysis complete!")
                    status.update(label="✅ Analysis Complete!", state="complete", expanded=False)
                    
                    # Store result in session state
                    st.session_state.result = result
                    st.session_state.match_title = match_title
                    st.session_state.sport = sport
                    st.session_state.markets_text = markets_text
                    st.session_state.selected_markets = selected_markets
                    
                except Exception as e:
                    status.update(label="❌ Analysis Failed", state="error")
                    st.error(f"Error during analysis: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                    return
    
    # Results section
    if hasattr(st.session_state, 'result') and st.session_state.result:
        st.markdown("---")
        st.header("📊 Analysis Results")
        
        result = st.session_state.result
        
        # Tabs for different sections
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "🎯 Recommendation",
            "🔍 Research",
            "🧠 Analyses",
            "👥 Reviews",
            "📥 Download"
        ])
        
        with tab1:
            st.markdown("## Final Recommendation")
            st.markdown(result.final_recommendation)
        
        with tab2:
            st.markdown("## Research Findings")
            st.markdown("*Data gathered via Gemini with Google Search grounding*")
            st.markdown(result.research)
        
        with tab3:
            st.markdown("## Individual Analyses")
            for model, analysis in result.analyses.items():
                model_display = model.split("/")[-1] if "/" in model else model
                with st.expander(f"📝 {model_display}", expanded=False):
                    st.markdown(analysis)
        
        with tab4:
            st.markdown("## Peer Reviews")
            for model, review in result.reviews.items():
                model_display = model.split("/")[-1] if "/" in model else model
                with st.expander(f"👁️ Review by {model_display}", expanded=False):
                    st.markdown(review)
        
        with tab5:
            st.markdown("## Download Report")
            
            # Generate markdown
            markdown_content = generate_markdown_report(
                result=result,
                match_title=st.session_state.match_title,
                sport=st.session_state.sport,
                markets_text=st.session_state.markets_text,
                selected_markets=st.session_state.selected_markets,
            )
            
            # Generate filename
            date_str = datetime.now().strftime("%Y%m%d")
            safe_title = sanitize_filename(st.session_state.match_title)
            filename = f"{safe_title}_{prompt_version}_{date_str}.md"
            
            st.download_button(
                label="📥 Download Markdown Report",
                data=markdown_content,
                file_name=filename,
                mime="text/markdown",
                use_container_width=True,
            )
            
            # Preview
            with st.expander("📄 Preview Report", expanded=False):
                st.code(markdown_content[:3000] + "..." if len(markdown_content) > 3000 else markdown_content)


if __name__ == "__main__":
    main()

