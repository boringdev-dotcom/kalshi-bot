"""Kalshi Bot - Live market dashboard, order monitoring, and research tools."""

# Lazy imports to avoid loading all dependencies when only using the API
__all__ = ["main", "run_research_bot", "run_analysis_once"]


def __getattr__(name: str):
    """Lazy import to avoid loading discord/research deps when running API only."""
    if name == "main":
        from .main import main
        return main
    elif name == "run_research_bot":
        from .research_bot import run_research_bot
        return run_research_bot
    elif name == "run_analysis_once":
        from .research_bot import run_analysis_once
        return run_analysis_once
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

