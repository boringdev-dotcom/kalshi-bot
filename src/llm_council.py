"""LLM Council engine for sports betting research using OpenRouter + Gemini."""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json
from functools import partial

import httpx
from google import genai
from google.genai import types

from .config import Settings
from .prompts import (
    # Soccer prompts V1 (original)
    RESEARCH_PROMPT,
    ANALYSIS_PROMPT,
    REVIEW_PROMPT,
    SYNTHESIS_PROMPT,
    RESEARCH_SYSTEM_PROMPT,
    ANALYST_SYSTEM_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
    CHAIRMAN_SYSTEM_PROMPT,
    # Soccer prompts V2 (rewritten)
    RESEARCH_PROMPT_V2,
    ANALYSIS_PROMPT_V2,
    REVIEW_PROMPT_V2,
    SYNTHESIS_PROMPT_V2,
    RESEARCH_SYSTEM_PROMPT_V2,
    ANALYST_SYSTEM_PROMPT_V2,
    REVIEWER_SYSTEM_PROMPT_V2,
    CHAIRMAN_SYSTEM_PROMPT_V2,
    # Basketball prompts V1 (original)
    BASKETBALL_RESEARCH_PROMPT,
    BASKETBALL_ANALYSIS_PROMPT,
    BASKETBALL_REVIEW_PROMPT,
    BASKETBALL_SYNTHESIS_PROMPT,
    BASKETBALL_RESEARCH_SYSTEM_PROMPT,
    BASKETBALL_ANALYST_SYSTEM_PROMPT,
    BASKETBALL_REVIEWER_SYSTEM_PROMPT,
    BASKETBALL_CHAIRMAN_SYSTEM_PROMPT,
    # Basketball prompts V2 (multi-stage research)
    BASKETBALL_RESEARCH_PROMPT_V2,
    BASKETBALL_ANALYSIS_PROMPT_V2,
    BASKETBALL_REVIEW_PROMPT_V2,
    BASKETBALL_SYNTHESIS_PROMPT_V2,
    BASKETBALL_RESEARCH_SYSTEM_PROMPT_V2,
    BASKETBALL_ANALYST_SYSTEM_PROMPT_V2,
    BASKETBALL_REVIEWER_SYSTEM_PROMPT_V2,
    BASKETBALL_CHAIRMAN_SYSTEM_PROMPT_V2,
    # Basketball V2 stage prompts (multi-stage research)
    BASKETBALL_STAGE_1_EFFICIENCY,
    BASKETBALL_STAGE_2_BETTING_LINES,
    BASKETBALL_STAGE_3_INJURIES,
    BASKETBALL_STAGE_4_SITUATIONAL,
    BASKETBALL_STAGE_5_H2H,
    BASKETBALL_STAGE_6_PROPS,
    BASKETBALL_RESEARCH_SYNTHESIS_V2,
    # Soccer prompts V3 (UCL specific)
    RESEARCH_PROMPT_V3,
    ANALYSIS_PROMPT_V3,
    REVIEW_PROMPT_V3,
    SYNTHESIS_PROMPT_V3,
    RESEARCH_SYSTEM_PROMPT_V3,
    ANALYST_SYSTEM_PROMPT_V3,
    REVIEWER_SYSTEM_PROMPT_V3,
    CHAIRMAN_SYSTEM_PROMPT_V3,
    # Soccer V2 stage prompts (multi-stage research)
    SOCCER_STAGE_1_FORM_METRICS,
    SOCCER_STAGE_2_BETTING_LINES,
    SOCCER_STAGE_3_TEAM_NEWS,
    SOCCER_STAGE_4_SITUATIONAL,
    SOCCER_STAGE_5_TACTICAL,
    SOCCER_RESEARCH_SYNTHESIS_V2,
)

logger = logging.getLogger(__name__)

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Gemini API endpoint (for research with Google Search grounding)
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Model configuration
# Research uses Gemini with Google Search grounding (called directly)
# Supported: gemini-2.5-pro, gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-pro/flash
RESEARCH_MODEL = "gemini-3-pro-preview"  # Fast model with grounding support

# Council models (via OpenRouter)
COUNCIL_MODELS = [
    "openai/gpt-5.2-pro",
    "anthropic/claude-opus-4.5",
    "google/gemini-3-pro-preview",
    "x-ai/grok-4.1-fast",
]

CHAIRMAN_MODEL = "google/gemini-3-pro-preview"


@dataclass
class CouncilResult:
    """Result from the LLM Council analysis."""
    research: str
    analyses: Dict[str, str]  # model -> analysis
    reviews: Dict[str, str]   # model -> review
    final_recommendation: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class LLMCouncil:
    """
    LLM Council for sports betting research (soccer and basketball).
    
    Implements a 4-stage pipeline:
    1. Research: Web search for match data (Gemini with Google Search grounding)
    2. Analysis: Multiple LLMs analyze independently
    3. Review: LLMs review each other's work
    4. Synthesis: Chairman compiles final recommendation
    """
    
    def __init__(
        self,
        openrouter_api_key: str,
        google_api_key: Optional[str] = None,
        sport: str = "soccer",
        prompt_version: str = "v1",
    ):
        """
        Initialize the LLM Council.
        
        Args:
            openrouter_api_key: OpenRouter API key for council models
            google_api_key: Google API key for Gemini with grounding (research)
            sport: Sport type ("soccer" or "basketball")
            prompt_version: Prompt version to use ("v1" or "v2", default "v1")
        """
        self.openrouter_api_key = openrouter_api_key
        self.google_api_key = google_api_key
        self.sport = sport
        self.prompt_version = prompt_version
        self.client = httpx.AsyncClient(timeout=300.0)  # Extended timeout for reasoning models
        
        # Set sport-specific prompts
        if sport == "basketball" and prompt_version == "v2":
            # Basketball V2 prompts (Four Factors, role-based analysis)
            self.research_prompt = BASKETBALL_RESEARCH_PROMPT_V2
            self.analysis_prompt = BASKETBALL_ANALYSIS_PROMPT_V2
            self.review_prompt = BASKETBALL_REVIEW_PROMPT_V2
            self.synthesis_prompt = BASKETBALL_SYNTHESIS_PROMPT_V2
            self.research_system_prompt = BASKETBALL_RESEARCH_SYSTEM_PROMPT_V2
            self.analyst_system_prompt = BASKETBALL_ANALYST_SYSTEM_PROMPT_V2
            self.reviewer_system_prompt = BASKETBALL_REVIEWER_SYSTEM_PROMPT_V2
            self.chairman_system_prompt = BASKETBALL_CHAIRMAN_SYSTEM_PROMPT_V2
        elif sport == "basketball":
            # Basketball V1 prompts (original)
            self.research_prompt = BASKETBALL_RESEARCH_PROMPT
            self.analysis_prompt = BASKETBALL_ANALYSIS_PROMPT
            self.review_prompt = BASKETBALL_REVIEW_PROMPT
            self.synthesis_prompt = BASKETBALL_SYNTHESIS_PROMPT
            self.research_system_prompt = BASKETBALL_RESEARCH_SYSTEM_PROMPT
            self.analyst_system_prompt = BASKETBALL_ANALYST_SYSTEM_PROMPT
            self.reviewer_system_prompt = BASKETBALL_REVIEWER_SYSTEM_PROMPT
            self.chairman_system_prompt = BASKETBALL_CHAIRMAN_SYSTEM_PROMPT
        elif sport == "soccer" and prompt_version == "v3":
            # Soccer V3 prompts (UCL specific)
            self.research_prompt = RESEARCH_PROMPT_V3
            self.analysis_prompt = ANALYSIS_PROMPT_V3
            self.review_prompt = REVIEW_PROMPT_V3
            self.synthesis_prompt = SYNTHESIS_PROMPT_V3
            self.research_system_prompt = RESEARCH_SYSTEM_PROMPT_V3
            self.analyst_system_prompt = ANALYST_SYSTEM_PROMPT_V3
            self.reviewer_system_prompt = REVIEWER_SYSTEM_PROMPT_V3
            self.chairman_system_prompt = CHAIRMAN_SYSTEM_PROMPT_V3
        elif sport == "soccer" and prompt_version == "v2":
            # Soccer V2 prompts (rewritten with sharper personas)
            self.research_prompt = RESEARCH_PROMPT_V2
            self.analysis_prompt = ANALYSIS_PROMPT_V2
            self.review_prompt = REVIEW_PROMPT_V2
            self.synthesis_prompt = SYNTHESIS_PROMPT_V2
            self.research_system_prompt = RESEARCH_SYSTEM_PROMPT_V2
            self.analyst_system_prompt = ANALYST_SYSTEM_PROMPT_V2
            self.reviewer_system_prompt = REVIEWER_SYSTEM_PROMPT_V2
            self.chairman_system_prompt = CHAIRMAN_SYSTEM_PROMPT_V2
        else:
            # Default to soccer V1
            self.research_prompt = RESEARCH_PROMPT
            self.analysis_prompt = ANALYSIS_PROMPT
            self.review_prompt = REVIEW_PROMPT
            self.synthesis_prompt = SYNTHESIS_PROMPT
            self.research_system_prompt = RESEARCH_SYSTEM_PROMPT
            self.analyst_system_prompt = ANALYST_SYSTEM_PROMPT
            self.reviewer_system_prompt = REVIEWER_SYSTEM_PROMPT
            self.chairman_system_prompt = CHAIRMAN_SYSTEM_PROMPT
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    def _call_gemini_sync(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> str:
        """
        Synchronous call to Gemini with Google Search grounding.
        Uses the official google-genai SDK for reliable grounding.
        """
        client = genai.Client(api_key=self.google_api_key)
        
        # Configure Google Search grounding tool
        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        
        # Build config with grounding and optional system instruction
        config_params = {
            "tools": [grounding_tool],
            "temperature": 1,
            "max_output_tokens": 8192,
        }
        
        if system_prompt:
            config_params["system_instruction"] = system_prompt
        
        config = types.GenerateContentConfig(**config_params)
        
        response = client.models.generate_content(
            model=RESEARCH_MODEL,
            contents=prompt,
            config=config,
        )
        
        return response.text
    
    async def _call_gemini_with_grounding(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> str:
        """
        Call Gemini API with Google Search grounding enabled.
        
        Uses the official google-genai SDK for reliable grounding support.
        Runs synchronous SDK call in executor to maintain async compatibility.
        
        Args:
            prompt: User prompt
            system_prompt: System instruction
            
        Returns:
            Model response text with grounded information
        """
        if not self.google_api_key:
            raise ValueError("GOOGLE_API_KEY required for Gemini grounding")
        
        try:
            # Run sync SDK call in executor to not block event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                partial(self._call_gemini_sync, prompt, system_prompt)
            )
            
            logger.info(f"Gemini grounding response received ({len(result)} chars)")
            return result
            
        except Exception as e:
            logger.error(f"Error calling Gemini with grounding: {e}")
            raise
    
    async def _call_llm(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
    ) -> str:
        """
        Make a request to OpenRouter API.
        
        Args:
            model: Model identifier (e.g., "openai/gpt-4o")
            system_prompt: System message
            user_prompt: User message
            temperature: Sampling temperature
            
        Returns:
            Model response text
        """
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/kalshi-bot",
            "X-Title": "Kalshi Soccer Research Bot",
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": 8192,  # Increased for detailed analysis
            "reasoning": {
                "effort": "high",
            }
        }
        
        try:
            response = await self.client.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Validate response structure
            if not data.get("choices"):
                raise ValueError(f"No choices in response from {model}")
            
            content = data["choices"][0].get("message", {}).get("content")
            if not content or not content.strip():
                raise ValueError(f"Empty response from {model}")
            
            logger.info(f"Received response from {model} ({len(content)} chars)")
            return content
            
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API error for {model}: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error calling {model}: {e}")
            raise
    
    async def _call_llm_with_retry(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_retries: int = 3,
    ) -> str:
        """
        Call LLM with retry logic and exponential backoff.
        
        Args:
            model: Model identifier
            system_prompt: System message
            user_prompt: User message
            temperature: Sampling temperature
            max_retries: Maximum number of retry attempts
            
        Returns:
            Model response text
            
        Raises:
            Exception: If all retries fail
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return await self._call_llm(
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                )
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {model} after {wait_time}s: {e}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"All {max_retries} retries failed for {model}: {e}")
        
        raise last_error
    
    async def stage_0_research(self, matches: str) -> str:
        """
        Stage 0: Research using Gemini with Google Search grounding.
        
        Args:
            matches: Description of matches to research
            
        Returns:
            Research findings from Google Search
        """
        logger.info(f"Stage 0: Starting {self.sport} research with Gemini + Google Search grounding...")
        
        prompt = self.research_prompt.format(matches=matches)
        
        research = await self._call_gemini_with_grounding(
            prompt=prompt,
            system_prompt=self.research_system_prompt,
        )
        
        logger.info("Stage 0: Research complete")
        
        # Print preview of research response
        print()
        print("=" * 60)
        print("📊 RESEARCH PREVIEW (first 500 chars):")
        print("=" * 60)
        print(research[:500])
        if len(research) > 500:
            print(f"\n... [{len(research) - 500} more characters]")
        print("=" * 60)
        print()
        
        return research
    
    async def stage_0_research_multistage(
        self,
        home_team: str,
        away_team: str,
        game_date: str,
        include_props: bool = True,
        players: Optional[List[str]] = None,
    ) -> str:
        """
        Stage 0: Multi-stage research for NBA games.
        
        Runs 5-6 focused research stages sequentially, each with Gemini grounding.
        This allows more targeted searches and better data quality.
        
        Args:
            home_team: Home team name
            away_team: Away team name
            game_date: Game date string
            include_props: Whether to include player props stage
            players: List of player names for props research
            
        Returns:
            Combined research from all stages
        """
        logger.info(f"Stage 0: Starting multi-stage NBA research for {home_team} vs {away_team}...")
        
        context = {
            "home_team": home_team,
            "away_team": away_team,
            "game_date": game_date,
        }
        
        # Define research stages
        stages = [
            ("1_efficiency", BASKETBALL_STAGE_1_EFFICIENCY),
            ("2_betting_lines", BASKETBALL_STAGE_2_BETTING_LINES),
            ("3_injuries", BASKETBALL_STAGE_3_INJURIES),
            ("4_situational", BASKETBALL_STAGE_4_SITUATIONAL),
            ("5_h2h", BASKETBALL_STAGE_5_H2H),
        ]
        
        # Optionally add props stage
        if include_props and players:
            context["player_list"] = ", ".join(players)
            context["opponent_team"] = away_team
            stages.append(("6_props", BASKETBALL_STAGE_6_PROPS))
        
        stage_outputs = {}
        
        # Execute each stage sequentially
        for stage_name, stage_prompt in stages:
            logger.info(f"  Executing research stage: {stage_name}")
            print(f"\n{'='*60}")
            print(f"🔍 RESEARCH STAGE: {stage_name}")
            print('='*60)
            
            try:
                prompt = stage_prompt.format(**context)
                result = await self._call_gemini_with_grounding(
                    prompt=prompt,
                    system_prompt=self.research_system_prompt,
                )
                stage_outputs[stage_name] = result
                
                # Print preview
                print(f"✓ Completed ({len(result)} chars)")
                preview = result[:300] if len(result) > 300 else result
                print(preview)
                if len(result) > 300:
                    print(f"... [{len(result) - 300} more chars]")
                    
            except Exception as e:
                logger.error(f"  Stage {stage_name} failed: {e}")
                stage_outputs[stage_name] = f"[Stage failed: {e}]"
        
        # Compile all stage outputs
        compiled_research = self._compile_stage_outputs(
            stage_outputs, home_team, away_team, game_date
        )
        
        logger.info(f"Stage 0: Multi-stage research complete ({len(compiled_research)} chars)")
        
        return compiled_research
    
    def _compile_stage_outputs(
        self,
        stage_outputs: Dict[str, str],
        home_team: str,
        away_team: str,
        game_date: str,
    ) -> str:
        """
        Compile all stage outputs into a single research document.
        
        Args:
            stage_outputs: Dictionary of stage name -> output
            home_team: Home team name
            away_team: Away team name
            game_date: Game date string
            
        Returns:
            Compiled research document
        """
        sections = [
            f"# NBA Research Report: {home_team} vs {away_team}",
            f"**Date:** {game_date}",
            "",
            "---",
            "",
        ]
        
        stage_labels = {
            "1_efficiency": "## Stage 1: Efficiency & Performance Metrics",
            "2_betting_lines": "## Stage 2: Betting Lines & Market Data",
            "3_injuries": "## Stage 3: Injuries & Roster Status",
            "4_situational": "## Stage 4: Situational & Scheduling Factors",
            "5_h2h": "## Stage 5: Head-to-Head & Matchup History",
            "6_props": "## Stage 6: Player Props Research",
        }
        
        for stage_name, output in stage_outputs.items():
            label = stage_labels.get(stage_name, f"## {stage_name}")
            sections.append(label)
            sections.append("")
            sections.append(output)
            sections.append("")
            sections.append("---")
            sections.append("")
        
        return "\n".join(sections)
    
    async def stage_0_research_multistage_soccer(
        self,
        home_team: str,
        away_team: str,
        competition: str,
        match_date: str,
    ) -> str:
        """
        Stage 0: Multi-stage research for soccer matches.
        
        Runs 5 focused research stages sequentially, each with Gemini grounding.
        This allows more targeted searches and better data quality.
        
        Args:
            home_team: Home team name
            away_team: Away team name
            competition: Competition/league name
            match_date: Match date string
            
        Returns:
            Combined research from all stages
        """
        logger.info(f"Stage 0: Starting multi-stage soccer research for {home_team} vs {away_team}...")
        
        # Extract month from match_date for situational stage
        month = match_date.split()[0] if match_date else "December"
        
        context = {
            "home_team": home_team,
            "away_team": away_team,
            "competition": competition,
            "match_date": match_date,
            "month": month,
        }
        
        # Define research stages
        stages = [
            ("1_form_metrics", SOCCER_STAGE_1_FORM_METRICS),
            ("2_betting_lines", SOCCER_STAGE_2_BETTING_LINES),
            ("3_team_news", SOCCER_STAGE_3_TEAM_NEWS),
            ("4_situational", SOCCER_STAGE_4_SITUATIONAL),
            ("5_tactical", SOCCER_STAGE_5_TACTICAL),
        ]
        
        stage_outputs = {}
        
        # Execute each stage sequentially
        for stage_name, stage_prompt in stages:
            logger.info(f"  Executing soccer research stage: {stage_name}")
            print(f"\n{'='*60}")
            print(f"🔍 RESEARCH STAGE: {stage_name}")
            print('='*60)
            
            try:
                prompt = stage_prompt.format(**context)
                result = await self._call_gemini_with_grounding(
                    prompt=prompt,
                    system_prompt=self.research_system_prompt,
                )
                stage_outputs[stage_name] = result
                
                # Print preview
                print(f"✓ Completed ({len(result)} chars)")
                preview = result[:300] if len(result) > 300 else result
                print(preview)
                if len(result) > 300:
                    print(f"... [{len(result) - 300} more chars]")
                    
            except Exception as e:
                logger.error(f"  Stage {stage_name} failed: {e}")
                stage_outputs[stage_name] = f"[Stage failed: {e}]"
        
        # Compile all stage outputs
        compiled_research = self._compile_soccer_stage_outputs(
            stage_outputs, home_team, away_team, competition, match_date
        )
        
        logger.info(f"Stage 0: Multi-stage soccer research complete ({len(compiled_research)} chars)")
        
        return compiled_research
    
    def _compile_soccer_stage_outputs(
        self,
        stage_outputs: Dict[str, str],
        home_team: str,
        away_team: str,
        competition: str,
        match_date: str,
    ) -> str:
        """
        Compile all soccer stage outputs into a single research document.
        
        Args:
            stage_outputs: Dictionary of stage name -> output
            home_team: Home team name
            away_team: Away team name
            competition: Competition/league name
            match_date: Match date string
            
        Returns:
            Compiled research document
        """
        sections = [
            f"# Soccer Research Report: {home_team} vs {away_team}",
            f"**Competition:** {competition}",
            f"**Date:** {match_date}",
            "",
            "---",
            "",
        ]
        
        stage_labels = {
            "1_form_metrics": "## Stage 1: Form & Underlying Metrics (xG)",
            "2_betting_lines": "## Stage 2: Betting Lines & Market Data",
            "3_team_news": "## Stage 3: Injuries, Suspensions & Team News",
            "4_situational": "## Stage 4: Situational & Motivation Factors",
            "5_tactical": "## Stage 5: Tactical & Style Matchup",
        }
        
        for stage_name, output in stage_outputs.items():
            label = stage_labels.get(stage_name, f"## {stage_name}")
            sections.append(label)
            sections.append("")
            sections.append(output)
            sections.append("")
            sections.append("---")
            sections.append("")
        
        return "\n".join(sections)
    
    async def stage_1_analysis(
        self,
        research: str,
        market_odds: str,
    ) -> Dict[str, str]:
        """
        Stage 1: Independent analysis by council members.
        
        Args:
            research: Research findings from Stage 0
            market_odds: Formatted Kalshi market odds
            
        Returns:
            Dictionary mapping model name to analysis
        """
        logger.info(f"Stage 1: Starting {self.sport} analysis with {len(COUNCIL_MODELS)} models...")
        
        prompt = self.analysis_prompt.format(
            research=research,
            market_odds=market_odds,
        )
        
        analyst_system_prompt = self.analyst_system_prompt
        
        async def get_analysis(model: str) -> tuple[str, str]:
            """Get analysis from a single model with retry logic."""
            try:
                analysis = await self._call_llm_with_retry(
                    model=model,
                    system_prompt=analyst_system_prompt,
                    user_prompt=prompt,
                    temperature=0.7,
                    max_retries=3,
                )
                logger.info(f"Stage 1: {model} analysis complete ({len(analysis)} chars)")
                return model, analysis
            except Exception as e:
                logger.error(f"Stage 1: {model} failed after all retries: {e}")
                return model, f"[Analysis failed after 3 retries: {e}]"
        
        # Run all analyses in parallel
        tasks = [get_analysis(model) for model in COUNCIL_MODELS]
        results = await asyncio.gather(*tasks)
        
        analyses = dict(results)
        logger.info("Stage 1: All analyses complete")
        return analyses
    
    async def stage_2_review(
        self,
        research: str,
        market_odds: str,
        analyses: Dict[str, str],
    ) -> Dict[str, str]:
        """
        Stage 2: Each model reviews others' analyses.
        
        Args:
            research: Research findings from Stage 0
            market_odds: Formatted Kalshi market odds
            analyses: Dictionary of analyses from Stage 1
            
        Returns:
            Dictionary mapping model name to review
        """
        logger.info(f"Stage 2: Starting {self.sport} reviews with {len(COUNCIL_MODELS)} models...")
        
        # Anonymize analyses for unbiased review
        anonymized_analyses = []
        model_labels = {}
        for i, (model, analysis) in enumerate(analyses.items()):
            label = chr(65 + i)  # A, B, C, D...
            model_labels[model] = label
            anonymized_analyses.append(f"=== Analyst {label} ===\n{analysis}")
        
        analyses_text = "\n\n".join(anonymized_analyses)
        
        prompt = self.review_prompt.format(
            research=research,
            market_odds=market_odds,
            analyses=analyses_text,
        )
        
        reviewer_system_prompt = self.reviewer_system_prompt
        
        async def get_review(model: str) -> tuple[str, str]:
            """Get review from a single model with retry logic."""
            # Don't let a model review its own work
            # We still include all analyses but the model doesn't know which is theirs
            try:
                review = await self._call_llm_with_retry(
                    model=model,
                    system_prompt=reviewer_system_prompt,
                    user_prompt=prompt,
                    temperature=0.5,
                    max_retries=3,
                )
                logger.info(f"Stage 2: {model} review complete ({len(review)} chars)")
                return model, review
            except Exception as e:
                logger.error(f"Stage 2: {model} failed after all retries: {e}")
                return model, f"[Review failed after 3 retries: {e}]"
        
        # Run all reviews in parallel
        tasks = [get_review(model) for model in COUNCIL_MODELS]
        results = await asyncio.gather(*tasks)
        
        reviews = dict(results)
        logger.info("Stage 2: All reviews complete")
        return reviews
    
    async def stage_3_synthesis(
        self,
        research: str,
        market_odds: str,
        analyses: Dict[str, str],
        reviews: Dict[str, str],
    ) -> str:
        """
        Stage 3: Chairman synthesizes final recommendation.
        
        Args:
            research: Research findings from Stage 0
            market_odds: Formatted Kalshi market odds
            analyses: Dictionary of analyses from Stage 1
            reviews: Dictionary of reviews from Stage 2
            
        Returns:
            Final synthesized recommendation
        """
        logger.info(f"Stage 3: Chairman synthesizing final {self.sport} recommendation...")
        
        # Format analyses with model names
        analyses_text = "\n\n".join(
            f"=== {model} ===\n{analysis}"
            for model, analysis in analyses.items()
        )
        
        # Format reviews with model names
        reviews_text = "\n\n".join(
            f"=== Review by {model} ===\n{review}"
            for model, review in reviews.items()
        )
        
        prompt = self.synthesis_prompt.format(
            research=research,
            market_odds=market_odds,
            analyses=analyses_text,
            reviews=reviews_text,
        )
        
        final_recommendation = await self._call_llm_with_retry(
            model=CHAIRMAN_MODEL,
            system_prompt=self.chairman_system_prompt,
            user_prompt=prompt,
            temperature=0.4,
            max_retries=3,
        )
        
        logger.info(f"Stage 3: Synthesis complete ({len(final_recommendation)} chars)")
        return final_recommendation
    
    async def run_council(
        self,
        matches: str,
        market_odds: str,
    ) -> CouncilResult:
        """
        Run the full LLM Council pipeline.
        
        Args:
            matches: Description of matches to analyze
            market_odds: Formatted Kalshi market odds
            
        Returns:
            CouncilResult with all outputs from each stage
        """
        logger.info(f"Starting LLM Council {self.sport} analysis pipeline...")
        
        # Stage 0: Research
        research = await self.stage_0_research(matches)
        
        # Stage 1: Analysis
        analyses = await self.stage_1_analysis(research, market_odds)
        
        # Stage 2: Review
        reviews = await self.stage_2_review(research, market_odds, analyses)
        
        # Stage 3: Synthesis
        final_recommendation = await self.stage_3_synthesis(
            research, market_odds, analyses, reviews
        )
        
        logger.info(f"LLM Council {self.sport} analysis pipeline complete")
        
        return CouncilResult(
            research=research,
            analyses=analyses,
            reviews=reviews,
            final_recommendation=final_recommendation,
            metadata={
                "sport": self.sport,
                "prompt_version": self.prompt_version,
                "research_model": RESEARCH_MODEL,
                "council_models": COUNCIL_MODELS,
                "chairman_model": CHAIRMAN_MODEL,
            },
        )


async def run_soccer_analysis(
    settings: Settings,
    markets_text: str,
    prompt_version: str = "v1",
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    competition: Optional[str] = None,
    match_date: Optional[str] = None,
) -> CouncilResult:
    """
    Convenience function to run soccer analysis.
    
    Args:
        settings: Application settings with API keys
        markets_text: Formatted market data for analysis
        prompt_version: Prompt version to use ("v1", "v2", or "v3", default "v1")
        home_team: Home team name (required for v2 multi-stage research)
        away_team: Away team name (required for v2 multi-stage research)
        competition: Competition/league name (required for v2 multi-stage research)
        match_date: Match date string (required for v2 multi-stage research)
        
    Returns:
        CouncilResult with analysis
    """
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is required")
    if not settings.google_api_key:
        raise ValueError("GOOGLE_API_KEY is required for research (Gemini grounding)")
    
    council = LLMCouncil(
        openrouter_api_key=settings.openrouter_api_key,
        google_api_key=settings.google_api_key,
        sport="soccer",
        prompt_version=prompt_version,
    )
    
    try:
        # V2 uses multi-stage research if match info is provided
        if prompt_version == "v2" and home_team and away_team and competition and match_date:
            logger.info(f"Using multi-stage research for {home_team} vs {away_team}")
            
            # Stage 0: Multi-stage research
            research = await council.stage_0_research_multistage_soccer(
                home_team=home_team,
                away_team=away_team,
                competition=competition,
                match_date=match_date,
            )
            
            # Stage 1: Analysis
            analyses = await council.stage_1_analysis(research, markets_text)
            
            # Stage 2: Review
            reviews = await council.stage_2_review(research, markets_text, analyses)
            
            # Stage 3: Synthesis
            final_recommendation = await council.stage_3_synthesis(
                research, markets_text, analyses, reviews
            )
            
            logger.info("LLM Council soccer analysis pipeline complete (multi-stage)")
            
            return CouncilResult(
                research=research,
                analyses=analyses,
                reviews=reviews,
                final_recommendation=final_recommendation,
                metadata={
                    "sport": "soccer",
                    "prompt_version": prompt_version,
                    "research_model": RESEARCH_MODEL,
                    "council_models": COUNCIL_MODELS,
                    "chairman_model": CHAIRMAN_MODEL,
                    "research_type": "multi-stage",
                    "home_team": home_team,
                    "away_team": away_team,
                    "competition": competition,
                    "match_date": match_date,
                },
            )
        else:
            # V1, V3, or V2 without match info: use legacy single-call research
            matches_for_research = f"""
Based on these Kalshi soccer markets, research the following matches:

{markets_text}

Focus on:
- La Liga matches
- Premier League matches
"""
            
            result = await council.run_council(
                matches=matches_for_research,
                market_odds=markets_text,
            )
            
            return result
        
    finally:
        await council.close()


async def run_basketball_analysis(
    settings: Settings,
    markets_text: str,
    prompt_version: str = "v1",
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
    game_date: Optional[str] = None,
    include_props: bool = True,
    players: Optional[List[str]] = None,
) -> CouncilResult:
    """
    Convenience function to run NBA basketball analysis.
    
    Args:
        settings: Application settings with API keys
        markets_text: Formatted market data for analysis
        prompt_version: Prompt version to use ("v1" or "v2", default "v1")
        home_team: Home team name (required for v2 multi-stage research)
        away_team: Away team name (required for v2 multi-stage research)
        game_date: Game date string (required for v2 multi-stage research)
        include_props: Whether to include player props research (v2 only)
        players: List of player names for props research (v2 only)
        
    Returns:
        CouncilResult with analysis
    """
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is required")
    if not settings.google_api_key:
        raise ValueError("GOOGLE_API_KEY is required for research (Gemini grounding)")
    
    council = LLMCouncil(
        openrouter_api_key=settings.openrouter_api_key,
        google_api_key=settings.google_api_key,
        sport="basketball",
        prompt_version=prompt_version,
    )
    
    try:
        # V2 uses multi-stage research if team info is provided
        if prompt_version == "v2" and home_team and away_team and game_date:
            logger.info(f"Using multi-stage research for {home_team} vs {away_team}")
            
            # Stage 0: Multi-stage research
            research = await council.stage_0_research_multistage(
                home_team=home_team,
                away_team=away_team,
                game_date=game_date,
                include_props=include_props,
                players=players,
            )
            
            # Stage 1: Analysis
            analyses = await council.stage_1_analysis(research, markets_text)
            
            # Stage 2: Review
            reviews = await council.stage_2_review(research, markets_text, analyses)
            
            # Stage 3: Synthesis
            final_recommendation = await council.stage_3_synthesis(
                research, markets_text, analyses, reviews
            )
            
            logger.info("LLM Council basketball analysis pipeline complete (multi-stage)")
            
            return CouncilResult(
                research=research,
                analyses=analyses,
                reviews=reviews,
                final_recommendation=final_recommendation,
                metadata={
                    "sport": "basketball",
                    "prompt_version": prompt_version,
                    "research_model": RESEARCH_MODEL,
                    "council_models": COUNCIL_MODELS,
                    "chairman_model": CHAIRMAN_MODEL,
                    "research_type": "multi-stage",
                    "home_team": home_team,
                    "away_team": away_team,
                    "game_date": game_date,
                },
            )
        else:
            # V1 or V2 without team info: use legacy single-call research
            matches_for_research = f"""
Based on these Kalshi NBA basketball markets, research the following games:

{markets_text}

Focus on:
- NBA regular season games
- Injury reports (CRITICAL for NBA)
- Back-to-back scheduling
- Recent team performance
"""
            
            result = await council.run_council(
                matches=matches_for_research,
                market_odds=markets_text,
            )
            
            return result
        
    finally:
        await council.close()

