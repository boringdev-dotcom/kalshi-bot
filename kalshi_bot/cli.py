"""CLI: worker, API, or both."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

import typer
import uvicorn

from kalshi_bot.api.app import create_app
from kalshi_bot.config import Settings
from kalshi_bot.watcher.runner import run_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)
cli = typer.Typer(help="Kalshi soccer under-No bot")


def _settings() -> Settings:
    return Settings()


async def _serve_api(settings: Settings) -> None:
    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host=settings.api_host,
        port=settings.get_port(),
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


@cli.command("run-worker")
def run_worker_cmd() -> None:
    """Background watcher + event-triggered agents."""
    settings = _settings()
    asyncio.run(run_worker(settings))


@cli.command("run-api")
def run_api_cmd() -> None:
    """FastAPI read API + dashboard WebSocket."""
    settings = _settings()
    asyncio.run(_serve_api(settings))


@cli.command("seed-demo")
def seed_demo_cmd() -> None:
    """Load sample games into SQLite for local dashboard testing."""
    from kalshi_bot.demo import seed_demo
    from kalshi_bot.store import Store

    settings = _settings()
    store = Store(settings.sqlite_path)
    seed_demo(store)
    store.close()
    logger.info("Seeded demo data into %s", settings.sqlite_path)


@cli.command("replay")
def replay_cmd(
    fixture: Optional[str] = typer.Option(None, help="Recorded fixture id (default: milan-lecce-2026-09-20)"),
    ticker: Optional[str] = typer.Option(None, help="Kalshi soccer-total ticker or Phase 0 fill ticker"),
    date: Optional[str] = typer.Option(None, help="YYYY-MM-DD to pick a Phase 0 match"),
    path: Optional[str] = typer.Option(None, help="Path to a replay JSON fixture"),
) -> None:
    """Replay a past scoreline paper-only: detector + Pundit/Kalshi would-decisions."""
    from kalshi_bot.replay import resolve_fixture, replay_fixture
    from kalshi_bot.store import Store

    settings = _settings()
    store = Store(settings.sqlite_path)
    store.set_paper(True)
    try:
        spec = resolve_fixture(fixture_id=fixture, ticker=ticker, date=date, path=path)
    except ValueError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=1) from exc
    result = replay_fixture(store, spec, settings)
    game = result["game"]
    pnl = result["pnl"]
    logger.info(
        "Replay %s vs %s events=%s decisions=%s paper pnl=%s¢",
        game.get("home_team"),
        game.get("away_team"),
        result["fired"],
        len(result["decisions"]),
        pnl.get("total_cents"),
    )
    for row in result["decisions"]:
        logger.info(
            "  %s %s %s size=%s px=%s rem=%s — %s",
            row.get("agent"),
            row.get("action"),
            row.get("market_ticker"),
            row.get("size"),
            row.get("price"),
            row.get("rem"),
            row.get("reason"),
        )
    store.close()


@cli.command("learn-nightly")
def learn_nightly_cmd() -> None:
    """Mine journal + Phase 0, validate lessons, update calibration, draft proposals."""
    from kalshi_bot.learning.mine import run_nightly
    from kalshi_bot.store import Store

    settings = _settings()
    store = Store(settings.sqlite_path)
    result = run_nightly(store)
    logger.info(
        "Nightly mine lessons=%s proposals=%s calibration=%s",
        len(result.get("lessons") or []),
        len(result.get("proposals") or []),
        len(result.get("calibration") or []),
    )
    store.close()


@cli.command("learn-reflect")
def learn_reflect_cmd(
    game_id: str = typer.Option(..., help="Finished game id to grade and reflect"),
) -> None:
    """Post-game grading + reflection. Off the event path."""
    from kalshi_bot.learning.reflect import reflect_game
    from kalshi_bot.store import Store

    settings = _settings()
    store = Store(settings.sqlite_path)
    result = reflect_game(store, game_id, settings)
    logger.info("Reflection %s: %s", game_id, (result or {}).get("notes"))
    store.close()


@cli.command("run-all")
def run_all_cmd() -> None:
    """API and watcher in one process (local / single-box)."""
    settings = _settings()

    async def main() -> None:
        await asyncio.gather(_serve_api(settings), run_worker(settings))

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("shutdown")
        sys.exit(0)


if __name__ == "__main__":
    cli()
