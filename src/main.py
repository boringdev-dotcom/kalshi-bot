"""Compatibility entry point.

The hosted API service starts with `python -m src.main` (its start command
predates the rebuild). This keeps that command working; the app itself lives
in the `courtside` package.
"""

from courtside.main import run

if __name__ == "__main__":
    run()
