"""Discord bot for sports betting research (Soccer & Basketball) using LLM Council."""
import asyncio
import logging
from datetime import datetime
from typing import Optional
import signal
import sys

import discord
from discord import app_commands
from discord.ext import tasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from .config import Settings
from .kalshi_api import (
    get_soccer_markets,
    get_basketball_markets,
    format_markets_for_analysis,
    format_basketball_markets_for_analysis,
    group_markets_by_match,
)
from .llm_council import run_soccer_analysis, run_basketball_analysis, CouncilResult
from .discord_embeds import (
    create_analysis_embeds,
    create_error_embed,
    create_no_markets_embed,
    batch_embeds_by_size,
)

logger = logging.getLogger(__name__)


class SportsResearchBot(discord.Client):
    """Discord bot for sports betting research (Soccer & Basketball)."""
    
    def __init__(self, settings: Settings, *args, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, *args, **kwargs)
        
        self.settings = settings
        self.tree = app_commands.CommandTree(self)
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.channel_id = settings.discord_channel_id_int
        self.channel: Optional[discord.TextChannel] = None
        # Fallback to webhook if no bot token
        self.webhook_url = settings.discord_webhook_url
        self._analysis_lock = asyncio.Lock()
    
    async def setup_hook(self):
        """Set up slash commands and scheduler."""
        # Register commands
        await self.tree.sync()
        logger.info("Slash commands synced")
        
        # Set up scheduler for daily analysis
        self._setup_scheduler()
    
    def _setup_scheduler(self):
        """Set up the APScheduler for daily analysis."""
        timezone = pytz.timezone(self.settings.research_schedule_timezone)
        
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        
        # Schedule daily analysis
        trigger = CronTrigger(
            hour=self.settings.research_schedule_hour,
            minute=self.settings.research_schedule_minute,
            timezone=timezone,
        )
        
        self.scheduler.add_job(
            self._run_scheduled_analysis,
            trigger=trigger,
            id="daily_soccer_analysis",
            name="Daily Soccer Analysis",
            replace_existing=True,
        )
        
        self.scheduler.start()
        logger.info(
            f"Scheduler started. Daily analysis at "
            f"{self.settings.research_schedule_hour:02d}:{self.settings.research_schedule_minute:02d} "
            f"{self.settings.research_schedule_timezone}"
        )
    
    async def on_ready(self):
        """Called when bot is ready."""
        logger.info(f"Research bot logged in as {self.user}")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        
        # Get the channel for posting analysis
        if self.channel_id:
            self.channel = self.get_channel(self.channel_id)
            if self.channel:
                logger.info(f"Research bot connected to channel: {self.channel.name}")
            else:
                logger.error(f"Could not find channel with ID {self.channel_id}")
    
    async def _run_scheduled_analysis(self):
        """Run the scheduled daily analysis."""
        logger.info("Running scheduled daily soccer analysis...")
        try:
            await self.run_analysis_and_post()
        except Exception as e:
            logger.error(f"Scheduled analysis failed: {e}", exc_info=True)
    
    async def run_analysis_and_post(
        self,
        interaction: Optional[discord.Interaction] = None,
        leagues: Optional[list] = None,
    ) -> Optional[CouncilResult]:
        """
        Run soccer analysis and post results.
        
        Args:
            interaction: Discord interaction if triggered by command
            leagues: List of leagues to analyze (default: both)
            
        Returns:
            CouncilResult if successful, None otherwise
        """
        async with self._analysis_lock:
            try:
                # Defer interaction if provided
                if interaction and not interaction.response.is_done():
                    await interaction.response.defer(thinking=True)
                
                # Fetch soccer markets from Kalshi
                logger.info("Fetching soccer markets from Kalshi...")
                markets = get_soccer_markets(
                    key_id=self.settings.kalshi_api_key_id,
                    private_key_pem=self.settings.kalshi_private_key_pem,
                    ws_url=self.settings.kalshi_ws_url,
                    leagues=leagues,
                )
                
                if not markets:
                    logger.warning("No soccer markets found")
                    embed = create_no_markets_embed()
                    
                    if interaction:
                        await interaction.followup.send(embed=embed)
                    elif self.channel:
                        await self._send_to_channel(embeds=[embed])
                    elif self.webhook_url:
                        await self._send_webhook(embeds=[embed])
                    
                    return None
                
                # Format markets for analysis
                markets_text = format_markets_for_analysis(markets)
                logger.info(f"Found {len(markets)} soccer markets")
                
                # Run LLM Council analysis
                logger.info("Running LLM Council analysis...")
                result = await run_soccer_analysis(
                    settings=self.settings,
                    markets_text=markets_text,
                )
                
                # Create Discord embeds (without individual analyses to keep size down)
                embeds = create_analysis_embeds(result, markets, include_details=False)
                
                # Batch embeds to stay under Discord's 6000 char limit per message
                batches = batch_embeds_by_size(embeds)
                
                # Send results
                if interaction:
                    # Send to interaction channel
                    if batches:
                        await interaction.followup.send(embeds=batches[0])
                        for batch in batches[1:]:
                            await interaction.channel.send(embeds=batch)
                
                elif self.channel:
                    # Send via bot to configured channel
                    await self._send_to_channel_batched(batches)
                
                elif self.webhook_url:
                    # Fallback: Send via webhook
                    await self._send_webhook_batched(batches)
                
                logger.info("Analysis posted successfully")
                return result
                
            except Exception as e:
                logger.error(f"Analysis failed: {e}", exc_info=True)
                error_embed = create_error_embed(str(e))
                
                if interaction:
                    await interaction.followup.send(embed=error_embed)
                elif self.channel:
                    await self._send_to_channel(embeds=[error_embed])
                elif self.webhook_url:
                    await self._send_webhook(embeds=[error_embed])
                
                return None
    
    async def run_basketball_analysis_and_post(
        self,
        interaction: Optional[discord.Interaction] = None,
        leagues: Optional[list] = None,
    ) -> Optional[CouncilResult]:
        """
        Run NBA basketball analysis and post results.
        
        Args:
            interaction: Discord interaction if triggered by command
            leagues: List of leagues to analyze (default: ["nba"])
            
        Returns:
            CouncilResult if successful, None otherwise
        """
        async with self._analysis_lock:
            try:
                # Defer interaction if provided
                if interaction and not interaction.response.is_done():
                    await interaction.response.defer(thinking=True)
                
                # Fetch basketball markets from Kalshi
                logger.info("Fetching NBA basketball markets from Kalshi...")
                markets = get_basketball_markets(
                    key_id=self.settings.kalshi_api_key_id,
                    private_key_pem=self.settings.kalshi_private_key_pem,
                    ws_url=self.settings.kalshi_ws_url,
                    leagues=leagues,
                )
                
                if not markets:
                    logger.warning("No basketball markets found")
                    embed = create_no_markets_embed(sport="basketball")
                    
                    if interaction:
                        await interaction.followup.send(embed=embed)
                    elif self.channel:
                        await self._send_to_channel(embeds=[embed])
                    elif self.webhook_url:
                        await self._send_webhook(embeds=[embed])
                    
                    return None
                
                # Format markets for analysis
                markets_text = format_basketball_markets_for_analysis(markets)
                logger.info(f"Found {len(markets)} basketball markets")
                
                # Run LLM Council analysis
                logger.info("Running LLM Council basketball analysis...")
                result = await run_basketball_analysis(
                    settings=self.settings,
                    markets_text=markets_text,
                )
                
                # Create Discord embeds (without individual analyses to keep size down)
                embeds = create_analysis_embeds(result, markets, include_details=False, sport="basketball")
                
                # Batch embeds to stay under Discord's 6000 char limit per message
                batches = batch_embeds_by_size(embeds)
                
                # Send results
                if interaction:
                    # Send to interaction channel
                    if batches:
                        await interaction.followup.send(embeds=batches[0])
                        for batch in batches[1:]:
                            await interaction.channel.send(embeds=batch)
                
                elif self.channel:
                    # Send via bot to configured channel
                    await self._send_to_channel_batched(batches)
                
                elif self.webhook_url:
                    # Fallback: Send via webhook
                    await self._send_webhook_batched(batches)
                
                logger.info("Basketball analysis posted successfully")
                return result
                
            except Exception as e:
                logger.error(f"Basketball analysis failed: {e}", exc_info=True)
                error_embed = create_error_embed(str(e))
                
                if interaction:
                    await interaction.followup.send(embed=error_embed)
                elif self.channel:
                    await self._send_to_channel(embeds=[error_embed])
                elif self.webhook_url:
                    await self._send_webhook(embeds=[error_embed])
                
                return None
    
    async def _send_to_channel(self, embeds: list, content: str = None):
        """Send message via Discord bot to configured channel."""
        if not self.channel:
            logger.error("No channel configured for sending messages")
            return
        
        try:
            # Discord limits: 10 embeds per message
            for i in range(0, len(embeds), 10):
                batch = embeds[i:i+10]
                msg_content = content if i == 0 else None
                await self.channel.send(content=msg_content, embeds=batch)
            logger.info(f"Analysis posted to channel {self.channel.name}")
        except Exception as e:
            logger.error(f"Failed to send to channel: {e}")
    
    async def _send_webhook(self, embeds: list, content: str = None):
        """Send message via Discord webhook (fallback)."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            # Discord webhook limits: 10 embeds per message
            for i in range(0, len(embeds), 10):
                batch = embeds[i:i+10]
                payload = {
                    "embeds": [e.to_dict() for e in batch],
                }
                if content and i == 0:
                    payload["content"] = content
                
                try:
                    response = await client.post(
                        self.webhook_url,
                        json=payload,
                        timeout=30.0,
                    )
                    response.raise_for_status()
                except Exception as e:
                    logger.error(f"Failed to send webhook: {e}")
    
    async def _send_to_channel_batched(self, batches: list, content: str = None):
        """Send pre-batched embeds via Discord bot to configured channel."""
        if not self.channel:
            logger.error("No channel configured for sending messages")
            return
        
        try:
            for i, batch in enumerate(batches):
                msg_content = content if i == 0 else None
                await self.channel.send(content=msg_content, embeds=batch)
            logger.info(f"Analysis posted to channel {self.channel.name} ({len(batches)} messages)")
        except Exception as e:
            logger.error(f"Failed to send to channel: {e}")
    
    async def _send_webhook_batched(self, batches: list, content: str = None):
        """Send pre-batched embeds via Discord webhook (fallback)."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            for i, batch in enumerate(batches):
                payload = {
                    "embeds": [e.to_dict() for e in batch],
                }
                if content and i == 0:
                    payload["content"] = content
                
                try:
                    response = await client.post(
                        self.webhook_url,
                        json=payload,
                        timeout=30.0,
                    )
                    response.raise_for_status()
                except Exception as e:
                    logger.error(f"Failed to send webhook: {e}")


class GameSelectView(discord.ui.View):
    """View with dropdown to select a game for analysis."""
    
    def __init__(
        self,
        matches: dict,
        bot: "SportsResearchBot",
        sport: str = "soccer",
        timeout: float = 180.0,
    ):
        super().__init__(timeout=timeout)
        self.matches = matches
        self.bot = bot
        self.sport = sport
        
        # Create the select menu
        select = discord.ui.Select(
            placeholder="Select a game to analyze...",
            min_values=1,
            max_values=1,
            options=self._create_options(),
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    def _create_options(self) -> list:
        """Create select options from matches."""
        options = []
        
        for match_id, match_data in list(self.matches.items())[:25]:  # Discord limit: 25 options
            title = match_data.get("title", "Unknown Match")
            league = match_data.get("league", "unknown")
            num_markets = len(match_data.get("markets", []))
            
            # League emoji (supports both soccer and basketball)
            league_emoji = {
                "la_liga": "🇪🇸",
                "premier_league": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
                "mls": "🇺🇸",
                "nba": "🏀",
                "bundesliga": "🇩🇪",
            }.get(league, "🏀" if self.sport == "basketball" else "⚽")
            
            # Truncate title if too long (Discord limit: 100 chars for label)
            label = f"{league_emoji} {title}"
            if len(label) > 100:
                label = label[:97] + "..."
            
            # Description (Discord limit: 100 chars)
            league_display = league.upper() if league == "nba" else league.replace('_', ' ').title()
            description = f"{num_markets} markets • {league_display}"
            if len(description) > 100:
                description = description[:97] + "..."
            
            options.append(discord.SelectOption(
                label=label,
                value=match_id,
                description=description,
            ))
        
        return options
    
    async def select_callback(self, interaction: discord.Interaction):
        """Handle game selection."""
        selected_match_id = interaction.data["values"][0]
        match_data = self.matches.get(selected_match_id)
        
        if not match_data:
            await interaction.response.send_message(
                "❌ Could not find the selected game. Please try again.",
                ephemeral=True,
            )
            return
        
        # Acknowledge selection and show loading state
        await interaction.response.defer(thinking=True)
        
        try:
            # Get markets for this specific game
            markets = match_data.get("markets", [])
            title = match_data.get("title", "Unknown Match")
            
            logger.info(f"Running {self.sport} analysis for: {title} ({len(markets)} markets)")
            
            # Format markets for analysis and run appropriate analysis
            if self.sport == "basketball":
                markets_text = format_basketball_markets_for_analysis(markets)
                result = await run_basketball_analysis(
                    settings=self.bot.settings,
                    markets_text=markets_text,
                )
            else:
                markets_text = format_markets_for_analysis(markets)
                result = await run_soccer_analysis(
                    settings=self.bot.settings,
                    markets_text=markets_text,
                )
            
            # Create Discord embeds (without details to keep size manageable)
            embeds = create_analysis_embeds(result, markets, include_details=False, sport=self.sport)
            
            # Batch embeds to stay under Discord's 6000 char limit per message
            batches = batch_embeds_by_size(embeds)
            
            # Send first batch as followup
            if batches:
                await interaction.followup.send(embeds=batches[0])
                
                # Send remaining batches as regular messages
                for batch in batches[1:]:
                    await interaction.channel.send(embeds=batch)
            
            logger.info(f"Analysis posted for: {title} ({len(batches)} messages)")
            
        except Exception as e:
            logger.error(f"Analysis failed for {selected_match_id}: {e}", exc_info=True)
            error_embed = create_error_embed(str(e))
            await interaction.followup.send(embed=error_embed)
        
        # Disable the view after selection
        self.stop()
    
    async def on_timeout(self):
        """Called when the view times out."""
        # Optionally disable all items
        for item in self.children:
            item.disabled = True


# Create bot instance and commands
_bot_instance: Optional[SportsResearchBot] = None

# Keep legacy alias
SoccerResearchBot = SportsResearchBot


def create_bot(settings: Settings) -> SportsResearchBot:
    """Create and configure the research bot."""
    global _bot_instance
    
    bot = SportsResearchBot(settings)
    _bot_instance = bot
    
    # Register slash commands
    @bot.tree.command(name="analyze", description="Run soccer betting analysis")
    @app_commands.describe(
        league="Which league to analyze (default: all)",
    )
    @app_commands.choices(league=[
        app_commands.Choice(name="All (La Liga + Premier League)", value="all"),
        app_commands.Choice(name="La Liga only", value="la_liga"),
        app_commands.Choice(name="Premier League only", value="premier_league"),
        app_commands.Choice(name="MLS only", value="mls"),
    ])
    async def analyze_command(
        interaction: discord.Interaction,
        league: str = "all",
    ):
        """Slash command to run soccer analysis on demand."""
        leagues = None if league == "all" else [league]
        await bot.run_analysis_and_post(interaction=interaction, leagues=leagues)
    
    @bot.tree.command(name="nba", description="Run NBA basketball betting analysis")
    async def nba_command(interaction: discord.Interaction):
        """Slash command to run NBA basketball analysis on demand."""
        await bot.run_basketball_analysis_and_post(interaction=interaction, leagues=["nba"])
    
    @bot.tree.command(name="nba_games", description="List available NBA games and pick one to analyze")
    async def nba_games_command(interaction: discord.Interaction):
        """Slash command to list NBA games and select one for analysis."""
        await interaction.response.defer(thinking=True)
        
        try:
            # Fetch NBA basketball markets from Kalshi
            logger.info("Fetching NBA basketball markets for /nba_games command")
            markets = get_basketball_markets(
                key_id=bot.settings.kalshi_api_key_id,
                private_key_pem=bot.settings.kalshi_private_key_pem,
                ws_url=bot.settings.kalshi_ws_url,
                leagues=["nba"],
            )
            
            if not markets:
                embed = create_no_markets_embed(sport="basketball")
                await interaction.followup.send(embed=embed)
                return
            
            # Group markets by game
            matches = group_markets_by_match(markets)
            
            if not matches:
                embed = create_no_markets_embed(sport="basketball")
                await interaction.followup.send(embed=embed)
                return
            
            logger.info(f"Found {len(matches)} NBA games available")
            
            # Create embed showing available games
            embed = discord.Embed(
                title="🏀 Available NBA Games",
                description=f"Found **{len(matches)}** games with open markets.\n\nSelect a game from the dropdown below to run a full LLM Council analysis.",
                color=0x1D428A,  # NBA blue
            )
            
            # Add summary
            total_markets = sum(len(m.get("markets", [])) for m in matches.values())
            embed.add_field(
                name="📊 Summary",
                value=f"🏀 NBA: {len(matches)} games ({total_markets} markets)",
                inline=False,
            )
            
            embed.set_footer(text="⏳ Analysis takes 2-3 minutes per game")
            
            # Create and send the view with dropdown
            view = GameSelectView(matches=matches, bot=bot, sport="basketball")
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"Error in /nba_games command: {e}", exc_info=True)
            error_embed = create_error_embed(str(e))
            await interaction.followup.send(embed=error_embed)
    
    @bot.tree.command(name="status", description="Check research bot status")
    async def status_command(interaction: discord.Interaction):
        """Check bot status and next scheduled run."""
        embed = discord.Embed(
            title="🤖 Sports Research Bot Status",
            color=0x00ff00,
        )
        
        embed.add_field(
            name="Status",
            value="✅ Online",
            inline=True,
        )
        
        embed.add_field(
            name="Supported Sports",
            value="⚽ Soccer (La Liga, EPL, MLS)\n🏀 Basketball (NBA)",
            inline=True,
        )
        
        if bot.scheduler:
            job = bot.scheduler.get_job("daily_soccer_analysis")
            if job and job.next_run_time:
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M %Z")
                embed.add_field(
                    name="Next Scheduled Run",
                    value=next_run,
                    inline=True,
                )
        
        embed.add_field(
            name="Council Models",
            value="\n".join([
                "• openai/gpt-4o",
                "• anthropic/claude-sonnet-4",
                "• google/gemini-3-pro-preview",
                "• x-ai/grok-3-mini-beta",
            ]),
            inline=False,
        )
        
        embed.add_field(
            name="Research Model",
            value="Gemini 2.5 Flash (Google Search grounding)",
            inline=False,
        )
        
        await interaction.response.send_message(embed=embed)
    
    @bot.tree.command(name="games", description="List available soccer games and pick one to analyze")
    @app_commands.describe(
        league="Which league to show games for (default: all)",
    )
    @app_commands.choices(league=[
        app_commands.Choice(name="All leagues", value="all"),
        app_commands.Choice(name="La Liga only", value="la_liga"),
        app_commands.Choice(name="Premier League only", value="premier_league"),
        app_commands.Choice(name="MLS only", value="mls"),
    ])
    async def games_command(
        interaction: discord.Interaction,
        league: str = "all",
    ):
        """Slash command to list soccer games and select one for analysis."""
        await interaction.response.defer(thinking=True)
        
        try:
            # Determine leagues to fetch
            leagues = None if league == "all" else [league]
            
            # Fetch soccer markets from Kalshi
            logger.info(f"Fetching soccer markets for /games command (leagues: {leagues})")
            markets = get_soccer_markets(
                key_id=bot.settings.kalshi_api_key_id,
                private_key_pem=bot.settings.kalshi_private_key_pem,
                ws_url=bot.settings.kalshi_ws_url,
                leagues=leagues,
            )
            
            if not markets:
                embed = create_no_markets_embed(sport="soccer")
                await interaction.followup.send(embed=embed)
                return
            
            # Group markets by match
            matches = group_markets_by_match(markets)
            
            if not matches:
                embed = create_no_markets_embed(sport="soccer")
                await interaction.followup.send(embed=embed)
                return
            
            logger.info(f"Found {len(matches)} games available")
            
            # Create embed showing available games
            embed = discord.Embed(
                title="⚽ Available Soccer Games",
                description=f"Found **{len(matches)}** games with open markets.\n\nSelect a game from the dropdown below to run a full LLM Council analysis.",
                color=0x5865F2,
            )
            
            # Add summary of games by league
            league_counts = {}
            for match_data in matches.values():
                l = match_data.get("league", "unknown")
                league_counts[l] = league_counts.get(l, 0) + 1
            
            league_summary = []
            for l, count in league_counts.items():
                emoji = {"la_liga": "🇪🇸", "premier_league": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "mls": "🇺🇸", "bundesliga": "🇩🇪"}.get(l, "⚽")
                league_summary.append(f"{emoji} {l.replace('_', ' ').title()}: {count} games")
            
            embed.add_field(
                name="📊 By League",
                value="\n".join(league_summary) or "No games found",
                inline=False,
            )
            
            embed.set_footer(text="⏳ Analysis takes 2-3 minutes per game")
            
            # Create and send the view with dropdown
            view = GameSelectView(matches=matches, bot=bot, sport="soccer")
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"Error in /games command: {e}", exc_info=True)
            error_embed = create_error_embed(str(e))
            await interaction.followup.send(embed=error_embed)
    
    return bot


async def run_research_bot():
    """Main entry point for the research bot."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Load settings
    settings = Settings()
    
    # Validate required settings
    missing = settings.validate_research_bot_required()
    if missing:
        logger.error(f"Missing required settings: {', '.join(missing)}")
        sys.exit(1)
    
    # Create bot
    bot = create_bot(settings)
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        logger.info("Shutting down...")
        if bot.scheduler:
            bot.scheduler.shutdown()
        asyncio.create_task(bot.close())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run bot
    logger.info("Starting Sports Research Bot (Soccer & Basketball)...")
    
    if settings.discord_bot_token:
        await bot.start(settings.discord_bot_token)
    else:
        # Webhook-only mode: run scheduler without Discord bot connection
        logger.info("Running in webhook-only mode (no Discord bot token)")
        
        # Run initial analysis
        await bot.run_analysis_and_post()
        
        # Keep scheduler running
        try:
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass


async def run_analysis_once():
    """Run a single analysis (no scheduler)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    settings = Settings()
    
    missing = settings.validate_research_bot_required()
    if missing:
        logger.error(f"Missing required settings: {', '.join(missing)}")
        return None
    
    bot = create_bot(settings)
    result = await bot.run_analysis_and_post()
    
    return result


def main():
    """Entry point for the research bot CLI."""
    asyncio.run(run_research_bot())


if __name__ == "__main__":
    main()

