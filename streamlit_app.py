#!/usr/bin/env python3
"""Streamlit web app for Kalshi NBA Combo Deep Research."""
import asyncio
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

import streamlit as st

# Page config must be first Streamlit command
st.set_page_config(
    page_title="Kalshi NBA Combo Research",
    page_icon="🏀",
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


def generate_combo_markdown_report(
    result,
    selected_games: List[Dict],
    markets_text: str,
    selected_markets: list,
) -> str:
    """Generate a markdown report from the two-stage combo analysis."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    md = []
    
    # Title
    game_count = len(selected_games)
    md.append(f"# 🏀 NBA Combo Analysis ({game_count} games)")
    md.append("")
    md.append(f"**Generated:** {timestamp}")
    md.append(f"**Games:** {game_count}")
    md.append(f"**Total Markets (filtered):** {len(selected_markets)}")
    md.append("**Mode:** Two-Stage (Research + Deep Research Analysis)")
    md.append("")
    
    # List selected games
    md.append("## Selected Games")
    md.append("")
    for game in selected_games:
        date_str = game.get("date").strftime("%b %d") if game.get("date") else "TBD"
        md.append(f"- **{game['title']}** ({date_str})")
    md.append("")
    
    # TOC
    md.append("## Table of Contents")
    md.append("- [Combo Recommendations](#combo-recommendations)")
    md.append("- [Research Data](#research-data)")
    md.append("- [Market Data](#market-data)")
    md.append("")
    
    # Deep Research analysis (the combo recommendations)
    md.append("---")
    md.append("")
    md.append("## Combo Recommendations")
    md.append("")
    md.append("*Analysis by Gemini Deep Research Agent*")
    md.append("")
    md.append(result.final_recommendation)
    md.append("")
    
    # Research data gathered in Stage 1
    md.append("---")
    md.append("")
    md.append("## Research Data")
    md.append("")
    md.append("*Gathered via Gemini with Google Search grounding (Stage 1)*")
    md.append("")
    md.append(result.research)
    md.append("")
    
    # Market Data
    md.append("---")
    md.append("")
    md.append("## Market Data")
    md.append("")
    md.append("*Kalshi TOTAL markets (extreme strikes only)*")
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
    md.append(f"- **Research Model:** {result.metadata.get('research_model', 'Gemini Deep Research')}")
    md.append(f"- **Sport:** NBA Basketball")
    md.append(f"- **Mode:** Deep Research (single agent)")
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
def fetch_nba_markets(_settings) -> List[Dict]:
    """Fetch NBA basketball markets from Kalshi (cached for 5 minutes)."""
    from src.kalshi_api import get_basketball_markets
    
    return get_basketball_markets(
        key_id=_settings.kalshi_api_key_id,
        private_key_pem=_settings.kalshi_private_key_pem,
        ws_url=_settings.kalshi_ws_url,
    )


def main():
    # Header
    st.title("🏀 Kalshi NBA Combo Research")
    st.markdown("*Gemini Deep Research for NBA totals betting analysis*")
    
    # Load settings
    try:
        from src.config import Settings
        settings = Settings()
    except Exception as e:
        st.error(f"Failed to load settings: {e}")
        st.info("Make sure environment variables are set: GOOGLE_API_KEY, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PEM")
        return
    
    # Validate required settings
    missing = []
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
        
        st.markdown("### 🏀 NBA Only")
        st.info("This tool is focused on NBA games with TOTAL markets only.")
        
        st.markdown("---")
        st.markdown("### ℹ️ About")
        st.markdown("""
        This tool uses **Gemini Deep Research Agent** to:
        1. 🔍 Research selected NBA games via web search
        2. 📊 Analyze TOTAL (over/under) markets
        3. 🎯 Generate combo betting recommendations
        
        **Market Filter:** Only extreme strike totals (lowest + highest per game)
        """)
        
        st.markdown("---")
        st.caption("Powered by Gemini Deep Research Agent")
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("📊 Available NBA Games")
        
        # Fetch markets button
        if st.button("🔄 Refresh Markets", use_container_width=True):
            st.cache_data.clear()
        
        with st.spinner("Fetching NBA markets from Kalshi..."):
            try:
                markets = fetch_nba_markets(settings)
            except Exception as e:
                st.error(f"Failed to fetch markets: {e}")
                return
        
        if not markets:
            st.warning("No NBA markets found on Kalshi right now.")
            return
        
        st.success(f"Found {len(markets)} NBA markets")
        
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
        
        # Build options for multiselect
        game_options = {}  # match_id -> (match_data, label)
        for date_key in sorted_dates:
            date_matches = matches_by_date[date_key]
            date_matches.sort(key=lambda x: x[1].get("title", ""))
            
            for match_id, match_data in date_matches:
                date_str = format_date_header(match_data.get("date"))
                # Count total markets for this game
                total_market_count = len([m for m in match_data["markets"] if m.get("market_type") == "total"])
                label = f"🏀 {match_data['title']} | {date_str} | {total_market_count} totals"
                game_options[match_id] = (match_data, label)
        
        # Multi-select for games
        selected_match_ids = st.multiselect(
            "🎮 Select Games for Combo Analysis",
            options=list(game_options.keys()),
            format_func=lambda mid: game_options[mid][1],
            help="Select multiple games to analyze as a combo bet",
        )
        
        # Show selected games info
        if selected_match_ids:
            selected_games = [game_options[mid][0] for mid in selected_match_ids]
            
            with st.expander("📋 Selected Games", expanded=True):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.metric("Games Selected", len(selected_match_ids))
                with col_b:
                    # Count filtered markets (totals only, will be filtered to extremes)
                    all_totals = []
                    for game in selected_games:
                        totals = [m for m in game["markets"] if m.get("market_type") == "total"]
                        all_totals.extend(totals)
                    st.metric("Total Markets", len(all_totals))
                
                st.markdown("**Selected:**")
                for game in selected_games:
                    date_str = game.get("date").strftime("%b %d") if game.get("date") else "TBD"
                    st.markdown(f"- {game['title']} ({date_str})")
        else:
            st.info("👆 Select one or more games above to analyze")
    
    with col2:
        st.header("🚀 Run Deep Research")
        
        if not selected_match_ids:
            st.info("Select games to analyze")
            return
        
        # Show games summary
        st.markdown(f"**{len(selected_match_ids)} game(s) selected**")
        
        for mid in selected_match_ids:
            game = game_options[mid][0]
            away_team, home_team = parse_teams_from_title(game["title"])
            if away_team and home_team:
                st.markdown(f"- {away_team} @ {home_team}")
        
        st.markdown("---")
        
        # Run button
        if st.button("🎯 Run Deep Research", type="primary", use_container_width=True):
            from src.kalshi_api import select_total_extremes, format_totals_for_deep_research
            
            # Collect markets from all selected games and filter to extreme totals
            selected_games = [game_options[mid][0] for mid in selected_match_ids]
            all_filtered_markets = []
            games_metadata = []
            
            for game in selected_games:
                # Filter to extreme totals for this game
                game_markets = game["markets"]
                filtered = select_total_extremes(game_markets)
                all_filtered_markets.extend(filtered)
                
                # Parse teams
                away_team, home_team = parse_teams_from_title(game["title"])
                games_metadata.append({
                    "title": game["title"],
                    "date": game.get("date"),
                    "away_team": away_team,
                    "home_team": home_team,
                    "filtered_markets": filtered,
                })
            
            # Format markets for Deep Research
            markets_text = format_totals_for_deep_research(all_filtered_markets, games_metadata)
            
            # Run two-stage analysis
            with st.status("🔬 Running NBA Combo Analysis...", expanded=True) as status:
                try:
                    st.write(f"📊 Selected {len(selected_match_ids)} games for combo analysis")
                    st.write(f"📈 Using {len(all_filtered_markets)} extreme total markets")
                    st.write("")
                    st.write("**Stage 1: Gathering Research Data**")
                    st.write("🔍 Running multi-stage research for each game (Gemini + Google Search)...")
                    st.write(f"   This will research {len(games_metadata)} games × 5 stages each")
                    st.write("")
                    st.write("**Stage 2: Deep Research Analysis**")
                    st.write("🧠 Deep Research Agent will analyze all data and produce combo recommendations")
                    st.write("")
                    st.write("⏳ Total time: ~5-10 minutes depending on number of games...")
                    
                    from src.llm_council import run_nba_combo_deep_research
                    
                    result = asyncio.run(run_nba_combo_deep_research(
                        settings=settings,
                        markets_text=markets_text,
                        games_metadata=games_metadata,
                    ))
                    
                    st.write("")
                    st.write("✅ Analysis complete!")
                    status.update(label="✅ Combo Analysis Complete!", state="complete", expanded=False)
                    
                    # Store result in session state
                    st.session_state.result = result
                    st.session_state.selected_games = selected_games
                    st.session_state.markets_text = markets_text
                    st.session_state.selected_markets = all_filtered_markets
                    
                except Exception as e:
                    status.update(label="❌ Deep Research Failed", state="error")
                    st.error(f"Error during Deep Research: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                    return
    
    # Results section
    if hasattr(st.session_state, 'result') and st.session_state.result:
        st.markdown("---")
        
        result = st.session_state.result
        
        st.header("📊 Combo Analysis Results")
        
        # Tabs for results
        tab1, tab2, tab3, tab4 = st.tabs([
            "🎯 Recommendations",
            "🔍 Research",
            "📈 Market Data",
            "📥 Download"
        ])
        
        with tab1:
            st.markdown("## Combo Recommendations")
            st.markdown("*Analysis by Gemini Deep Research Agent*")
            st.markdown(result.final_recommendation)
        
        with tab2:
            st.markdown("## Research Data")
            st.markdown("*Gathered via Gemini with Google Search grounding (Stage 1)*")
            st.markdown(result.research)
        
        with tab3:
            st.markdown("## Filtered Market Data")
            st.markdown("*Kalshi TOTAL markets (extreme strikes only)*")
            st.code(st.session_state.markets_text)
        
        with tab4:
            st.markdown("## Download Report")
            
            # Generate markdown
            markdown_content = generate_combo_markdown_report(
                result=result,
                selected_games=st.session_state.selected_games,
                markets_text=st.session_state.markets_text,
                selected_markets=st.session_state.selected_markets,
            )
            
            # Generate filename
            date_str = datetime.now().strftime("%Y%m%d")
            game_count = len(st.session_state.selected_games)
            filename = f"nba_combo_{game_count}games_analysis_{date_str}.md"
            
            st.download_button(
                label="📥 Download Report",
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
