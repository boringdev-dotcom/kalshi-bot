"""Entry point: `uv run courtside`."""

from __future__ import annotations

import logging
import os

import uvicorn

from .api.app import create_app
from .config import get_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

app = create_app()


def run() -> None:
    uvicorn.run(
        "courtside.main:app",
        # A hosted container must listen on all interfaces; a laptop should not.
        host=os.environ.get("HOST", "0.0.0.0" if get_config().hosted else "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    run()
