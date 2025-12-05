"""Discord embed formatters for soccer research bot."""
from datetime import datetime
from typing import List, Dict, Any, Optional
import re

import discord

from .llm_council import CouncilResult


# Color scheme
COLOR_PRIMARY = 0x5865F2    # Discord blurple
COLOR_SUCCESS = 0x57F287    # Green
COLOR_WARNING = 0xFEE75C    # Yellow
COLOR_ERROR = 0xED4245      # Red
COLOR_LA_LIGA = 0xEE8707    # Orange (La Liga colors)
COLOR_PREMIER = 0x3D195B    # Purple (Premier League colors)


def truncate_text(text: str, max_length: int = 1024) -> str:
    """Truncate text to fit Discord embed field limits."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def extract_recommendations(text: str) -> List[Dict[str, str]]:
    """
    Extract betting recommendations from the synthesis text.
    
    Looks for patterns like:
    - Pick: TICKER-XXX YES/NO
    - Confidence: High/Medium/Low
    """
    recommendations = []
    
    # Look for pick patterns
    pick_pattern = r"(?:Pick|Recommendation)[:\s]+([A-Z0-9-]+)\s+(YES|NO)"
    confidence_pattern = r"Confidence[:\s]+(High|Medium|Low)"
    
    picks = re.findall(pick_pattern, text, re.IGNORECASE)
    confidences = re.findall(confidence_pattern, text, re.IGNORECASE)
    
    for i, (ticker, side) in enumerate(picks):
        rec = {
            "ticker": ticker.upper(),
            "side": side.upper(),
            "confidence": confidences[i] if i < len(confidences) else "Unknown",
        }
        recommendations.append(rec)
    
    return recommendations


def create_header_embed() -> discord.Embed:
    """Create the header embed for the analysis."""
    embed = discord.Embed(
        title="⚽ Soccer Betting Analysis",
        description="**LLM Council Analysis Report**\n\nMultiple AI models have analyzed today's matches and reached a consensus.",
        color=COLOR_PRIMARY,
        timestamp=datetime.utcnow(),
    )
    
    embed.add_field(
        name="📊 Analysis Pipeline",
        value=(
            "1️⃣ **Research**: Web search for match data\n"
            "2️⃣ **Analysis**: 4 LLMs analyze independently\n"
            "3️⃣ **Review**: Models peer-review each other\n"
            "4️⃣ **Synthesis**: Chairman compiles recommendation"
        ),
        inline=False,
    )
    
    embed.set_footer(text="Kalshi Soccer Research Bot")
    
    return embed


def create_markets_embed(markets: List[Dict[str, Any]]) -> discord.Embed:
    """Create embed showing available markets."""
    embed = discord.Embed(
        title="📈 Kalshi Soccer Markets",
        color=COLOR_PRIMARY,
    )
    
    # Group by league
    la_liga = [m for m in markets if m.get("league") == "la_liga"]
    premier = [m for m in markets if m.get("league") == "premier_league"]
    other = [m for m in markets if m.get("league") not in ("la_liga", "premier_league")]
    
    if la_liga:
        la_liga_text = []
        for m in la_liga[:5]:  # Limit to 5
            ticker = m.get("ticker", "N/A")
            title = m.get("title", "Unknown")
            yes_bid = m.get("yes_bid", "?")
            la_liga_text.append(f"• **{title}**\n  `{ticker}` | YES: {yes_bid}¢")
        
        embed.add_field(
            name="🇪🇸 La Liga",
            value="\n".join(la_liga_text) or "No markets",
            inline=False,
        )
    
    if premier:
        premier_text = []
        for m in premier[:5]:
            ticker = m.get("ticker", "N/A")
            title = m.get("title", "Unknown")
            yes_bid = m.get("yes_bid", "?")
            premier_text.append(f"• **{title}**\n  `{ticker}` | YES: {yes_bid}¢")
        
        embed.add_field(
            name="🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League",
            value="\n".join(premier_text) or "No markets",
            inline=False,
        )
    
    if other:
        other_text = [f"• `{m.get('ticker')}`: {m.get('title')}" for m in other[:3]]
        embed.add_field(
            name="Other Markets",
            value="\n".join(other_text),
            inline=False,
        )
    
    embed.add_field(
        name="Total Markets",
        value=f"**{len(markets)}** soccer markets found",
        inline=True,
    )
    
    return embed


def create_research_embed(research: str) -> discord.Embed:
    """Create embed for research findings."""
    embed = discord.Embed(
        title="🔍 Research Findings",
        description="Data gathered via web search (Perplexity Sonar Pro)",
        color=COLOR_PRIMARY,
    )
    
    # Split research into chunks if needed
    chunks = []
    current_chunk = ""
    
    for line in research.split("\n"):
        if len(current_chunk) + len(line) + 1 > 1000:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += "\n" + line if current_chunk else line
    
    if current_chunk:
        chunks.append(current_chunk)
    
    # Add first few chunks as fields
    for i, chunk in enumerate(chunks[:3]):
        embed.add_field(
            name=f"Research Part {i + 1}" if i > 0 else "Key Findings",
            value=truncate_text(chunk, 1024),
            inline=False,
        )
    
    if len(chunks) > 3:
        embed.set_footer(text=f"Showing 3 of {len(chunks)} research sections")
    
    return embed


def create_recommendation_embed(result: CouncilResult) -> discord.Embed:
    """Create the main recommendation embed."""
    embed = discord.Embed(
        title="🎯 Council Recommendation",
        description="**Final betting recommendations from the LLM Council**",
        color=COLOR_SUCCESS,
        timestamp=datetime.utcnow(),
    )
    
    synthesis = result.final_recommendation
    
    # Try to extract structured recommendations
    recommendations = extract_recommendations(synthesis)
    
    if recommendations:
        rec_text = []
        for rec in recommendations[:5]:  # Limit to 5
            confidence_emoji = {
                "HIGH": "🟢",
                "MEDIUM": "🟡",
                "LOW": "🔴",
            }.get(rec["confidence"].upper(), "⚪")
            
            rec_text.append(
                f"{confidence_emoji} **{rec['ticker']}** → {rec['side']}\n"
                f"   Confidence: {rec['confidence']}"
            )
        
        embed.add_field(
            name="📋 Recommendations",
            value="\n\n".join(rec_text) or "See analysis below",
            inline=False,
        )
    
    # Add synthesis summary (truncated)
    # Extract first few paragraphs
    paragraphs = [p.strip() for p in synthesis.split("\n\n") if p.strip()]
    summary = "\n\n".join(paragraphs[:2])
    
    embed.add_field(
        name="📝 Analysis Summary",
        value=truncate_text(summary, 1024),
        inline=False,
    )
    
    # Add metadata
    embed.add_field(
        name="🤖 Council Composition",
        value=(
            f"**Research**: {result.metadata.get('research_model', 'N/A')}\n"
            f"**Analysts**: {len(result.analyses)} models\n"
            f"**Chairman**: {result.metadata.get('chairman_model', 'N/A')}"
        ),
        inline=True,
    )
    
    embed.set_footer(text="⚠️ This is AI-generated analysis. Always do your own research.")
    
    return embed


def create_analysis_detail_embed(
    model: str,
    analysis: str,
    is_review: bool = False,
) -> discord.Embed:
    """Create embed for individual model analysis."""
    # Clean model name for display
    model_display = model.split("/")[-1] if "/" in model else model
    
    embed = discord.Embed(
        title=f"{'📝 Review' if is_review else '🧠 Analysis'} - {model_display}",
        color=COLOR_PRIMARY if not is_review else COLOR_WARNING,
    )
    
    # Split into chunks
    content = truncate_text(analysis, 4000)
    
    # Add as field(s)
    if len(content) <= 1024:
        embed.add_field(
            name="Analysis",
            value=content,
            inline=False,
        )
    else:
        # Split into multiple fields
        chunks = [content[i:i+1024] for i in range(0, len(content), 1024)]
        for i, chunk in enumerate(chunks[:4]):  # Max 4 fields
            embed.add_field(
                name=f"Part {i + 1}" if i > 0 else "Analysis",
                value=chunk,
                inline=False,
            )
    
    return embed


def create_analysis_embeds(
    result: CouncilResult,
    markets: List[Dict[str, Any]],
    include_details: bool = True,
) -> List[discord.Embed]:
    """
    Create all embeds for an analysis result.
    
    Args:
        result: CouncilResult from the LLM Council
        markets: List of market dictionaries
        include_details: Whether to include individual model analyses
        
    Returns:
        List of Discord embeds
    """
    embeds = []
    
    # Header
    embeds.append(create_header_embed())
    
    # Markets overview
    embeds.append(create_markets_embed(markets))
    
    # Main recommendation
    embeds.append(create_recommendation_embed(result))
    
    # Research findings (abbreviated)
    embeds.append(create_research_embed(result.research))
    
    # Individual analyses (if requested and space permits)
    if include_details:
        # Add a couple of representative analyses
        for model, analysis in list(result.analyses.items())[:2]:
            embeds.append(create_analysis_detail_embed(model, analysis))
    
    return embeds


def create_error_embed(error_message: str) -> discord.Embed:
    """Create an error embed."""
    embed = discord.Embed(
        title="❌ Analysis Error",
        description="An error occurred during the analysis.",
        color=COLOR_ERROR,
        timestamp=datetime.utcnow(),
    )
    
    embed.add_field(
        name="Error Details",
        value=f"```{truncate_text(error_message, 1000)}```",
        inline=False,
    )
    
    embed.set_footer(text="Please try again later or contact support.")
    
    return embed


def create_no_markets_embed() -> discord.Embed:
    """Create embed for when no markets are found."""
    embed = discord.Embed(
        title="📭 No Soccer Markets Found",
        description=(
            "No open soccer markets were found for La Liga or Premier League on Kalshi.\n\n"
            "This could mean:\n"
            "• No matches are scheduled for today\n"
            "• Markets haven't opened yet\n"
            "• Markets have already closed"
        ),
        color=COLOR_WARNING,
        timestamp=datetime.utcnow(),
    )
    
    embed.set_footer(text="Try again later when new markets are available.")
    
    return embed


def create_status_embed(
    is_online: bool = True,
    next_run: Optional[str] = None,
    last_run: Optional[str] = None,
) -> discord.Embed:
    """Create a status embed."""
    embed = discord.Embed(
        title="🤖 Research Bot Status",
        color=COLOR_SUCCESS if is_online else COLOR_ERROR,
    )
    
    embed.add_field(
        name="Status",
        value="✅ Online" if is_online else "❌ Offline",
        inline=True,
    )
    
    if next_run:
        embed.add_field(
            name="Next Scheduled Run",
            value=next_run,
            inline=True,
        )
    
    if last_run:
        embed.add_field(
            name="Last Run",
            value=last_run,
            inline=True,
        )
    
    return embed

