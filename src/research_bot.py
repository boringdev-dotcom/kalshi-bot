"""Discord bot for soccer betting research using LLM Council."""
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
from .kalshi_api import get_soccer_markets, format_markets_for_analysis
from .llm_council import run_soccer_analysis, CouncilResult
from .discord_embeds import (
    create_analysis_embeds,
    create_error_embed,
    create_no_markets_embed,
)

logger = logging.getLogger(__name__)


class SoccerResearchBot(discord.Client):
    """Discord bot for soccer betting research."""
    
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
                
                # Create Discord embeds
                embeds = create_analysis_embeds(result, markets)
                
                # Send results
                if interaction:
                    # Send to interaction channel
                    await interaction.followup.send(embeds=embeds[:10])  # Discord limit
                    
                    # If there are more embeds, send follow-up messages
                    for i in range(10, len(embeds), 10):
                        await interaction.channel.send(embeds=embeds[i:i+10])
                
                elif self.channel:
                    # Send via bot to configured channel
                    await self._send_to_channel(embeds=embeds)
                
                elif self.webhook_url:
                    # Fallback: Send via webhook
                    await self._send_webhook(embeds=embeds)
                
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


# Create bot instance and commands
_bot_instance: Optional[SoccerResearchBot] = None


def create_bot(settings: Settings) -> SoccerResearchBot:
    """Create and configure the research bot."""
    global _bot_instance
    
    bot = SoccerResearchBot(settings)
    _bot_instance = bot
    
    # Register slash commands
    @bot.tree.command(name="analyze", description="Run soccer betting analysis")
    @app_commands.describe(
        league="Which league to analyze (default: both)",
    )
    @app_commands.choices(league=[
        app_commands.Choice(name="All (La Liga + Premier League)", value="all"),
        app_commands.Choice(name="La Liga only", value="la_liga"),
        app_commands.Choice(name="Premier League only", value="premier_league"),
    ])
    async def analyze_command(
        interaction: discord.Interaction,
        league: str = "all",
    ):
        """Slash command to run analysis on demand."""
        leagues = None if league == "all" else [league]
        await bot.run_analysis_and_post(interaction=interaction, leagues=leagues)
    
    @bot.tree.command(name="status", description="Check research bot status")
    async def status_command(interaction: discord.Interaction):
        """Check bot status and next scheduled run."""
        embed = discord.Embed(
            title="🤖 Soccer Research Bot Status",
            color=0x00ff00,
        )
        
        embed.add_field(
            name="Status",
            value="✅ Online",
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
            value="perplexity/sonar-pro (web search)",
            inline=False,
        )
        
        await interaction.response.send_message(embed=embed)
    
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
    logger.info("Starting Soccer Research Bot...")
    
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

