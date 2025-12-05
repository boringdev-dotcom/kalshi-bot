"""LLM Council engine for soccer betting research using OpenRouter + Gemini."""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json

import httpx

from .config import Settings
from .prompts import (
    RESEARCH_PROMPT,
    ANALYSIS_PROMPT,
    REVIEW_PROMPT,
    SYNTHESIS_PROMPT,
    RESEARCH_SYSTEM_PROMPT,
    ANALYST_SYSTEM_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
    CHAIRMAN_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Gemini API endpoint (for research with Google Search grounding)
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Model configuration
# Research uses Gemini with Google Search grounding (called directly)
# Supported: gemini-2.5-pro, gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-pro/flash
RESEARCH_MODEL = "gemini-2.5-flash"  # Fast model with grounding support

# Council models (via OpenRouter)
COUNCIL_MODELS = [
    "openai/gpt-5.1",
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
    LLM Council for soccer betting research.
    
    Implements a 4-stage pipeline:
    1. Research: Web search for match data (Gemini with Google Search grounding)
    2. Analysis: Multiple LLMs analyze independently
    3. Review: LLMs review each other's work
    4. Synthesis: Chairman compiles final recommendation
    """
    
    def __init__(self, openrouter_api_key: str, google_api_key: Optional[str] = None):
        """
        Initialize the LLM Council.
        
        Args:
            openrouter_api_key: OpenRouter API key for council models
            google_api_key: Google API key for Gemini with grounding (research)
        """
        self.openrouter_api_key = openrouter_api_key
        self.google_api_key = google_api_key
        self.client = httpx.AsyncClient(timeout=120.0)
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def _call_gemini_with_grounding(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> str:
        """
        Call Gemini API directly with Google Search grounding enabled.
        
        Based on: https://ai.google.dev/gemini-api/docs/google-search
        
        Args:
            prompt: User prompt
            system_prompt: System instruction
            
        Returns:
            Model response text with grounded information
        """
        if not self.google_api_key:
            raise ValueError("GOOGLE_API_KEY required for Gemini grounding")
        
        # URL format: https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
        url = f"{GEMINI_API_URL}/{RESEARCH_MODEL}:generateContent"
        
        # Use x-goog-api-key header as per docs
        headers = {
            "x-goog-api-key": self.google_api_key,
            "Content-Type": "application/json",
        }
        
        # Build contents with optional system instruction
        contents = [
            {
                "parts": [{"text": prompt}]
            }
        ]
        
        payload = {
            "contents": contents,
            "tools": [
                {
                    "google_search": {}  # Enable Google Search grounding
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 8192,
            }
        }
        
        # Add system instruction if provided
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }
        
        try:
            response = await self.client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract text from response
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text_parts = [p.get("text", "") for p in parts if "text" in p]
                
                # Log grounding metadata if available
                grounding_meta = candidates[0].get("groundingMetadata", {})
                if grounding_meta:
                    queries = grounding_meta.get("webSearchQueries", [])
                    logger.info(f"Gemini search queries: {queries}")
                
                return "\n".join(text_parts)
            
            return "No response from Gemini"
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Gemini API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error calling Gemini: {e}")
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
            "max_tokens": 4096,
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
            return data["choices"][0]["message"]["content"]
            
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API error for {model}: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error calling {model}: {e}")
            raise
    
    async def stage_0_research(self, matches: str) -> str:
        """
        Stage 0: Research using Gemini with Google Search grounding.
        
        Args:
            matches: Description of matches to research
            
        Returns:
            Research findings from Google Search
        """
        logger.info("Stage 0: Starting research with Gemini + Google Search grounding...")
        
        prompt = RESEARCH_PROMPT.format(matches=matches)
        
        research = await self._call_gemini_with_grounding(
            prompt=prompt,
            system_prompt=RESEARCH_SYSTEM_PROMPT,
        )
        
        logger.info("Stage 0: Research complete")
        return research
    
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
        logger.info(f"Stage 1: Starting analysis with {len(COUNCIL_MODELS)} models...")
        
        prompt = ANALYSIS_PROMPT.format(
            research=research,
            market_odds=market_odds,
        )
        
        async def get_analysis(model: str) -> tuple[str, str]:
            """Get analysis from a single model."""
            try:
                analysis = await self._call_llm(
                    model=model,
                    system_prompt=ANALYST_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    temperature=0.7,
                )
                logger.info(f"Stage 1: {model} analysis complete")
                return model, analysis
            except Exception as e:
                logger.error(f"Stage 1: {model} failed: {e}")
                return model, f"[Analysis failed: {e}]"
        
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
        logger.info(f"Stage 2: Starting reviews with {len(COUNCIL_MODELS)} models...")
        
        # Anonymize analyses for unbiased review
        anonymized_analyses = []
        model_labels = {}
        for i, (model, analysis) in enumerate(analyses.items()):
            label = chr(65 + i)  # A, B, C, D...
            model_labels[model] = label
            anonymized_analyses.append(f"=== Analyst {label} ===\n{analysis}")
        
        analyses_text = "\n\n".join(anonymized_analyses)
        
        prompt = REVIEW_PROMPT.format(
            research=research,
            market_odds=market_odds,
            analyses=analyses_text,
        )
        
        async def get_review(model: str) -> tuple[str, str]:
            """Get review from a single model."""
            # Don't let a model review its own work
            # We still include all analyses but the model doesn't know which is theirs
            try:
                review = await self._call_llm(
                    model=model,
                    system_prompt=REVIEWER_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    temperature=0.5,
                )
                logger.info(f"Stage 2: {model} review complete")
                return model, review
            except Exception as e:
                logger.error(f"Stage 2: {model} failed: {e}")
                return model, f"[Review failed: {e}]"
        
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
        logger.info("Stage 3: Chairman synthesizing final recommendation...")
        
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
        
        prompt = SYNTHESIS_PROMPT.format(
            research=research,
            market_odds=market_odds,
            analyses=analyses_text,
            reviews=reviews_text,
        )
        
        final_recommendation = await self._call_llm(
            model=CHAIRMAN_MODEL,
            system_prompt=CHAIRMAN_SYSTEM_PROMPT,
            user_prompt=prompt,
            temperature=0.4,
        )
        
        logger.info("Stage 3: Synthesis complete")
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
        logger.info("Starting LLM Council analysis pipeline...")
        
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
        
        logger.info("LLM Council analysis pipeline complete")
        
        return CouncilResult(
            research=research,
            analyses=analyses,
            reviews=reviews,
            final_recommendation=final_recommendation,
            metadata={
                "research_model": RESEARCH_MODEL,
                "council_models": COUNCIL_MODELS,
                "chairman_model": CHAIRMAN_MODEL,
            },
        )


async def run_soccer_analysis(
    settings: Settings,
    markets_text: str,
) -> CouncilResult:
    """
    Convenience function to run soccer analysis.
    
    Args:
        settings: Application settings with API keys
        markets_text: Formatted market data for analysis
        
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
    )
    
    try:
        # Extract match info for research
        # The markets_text should contain match titles that we can research
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

