"""CLI: worker, API, or both."""

from __future__ import annotations

import asyncio
import logging
import sys

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
