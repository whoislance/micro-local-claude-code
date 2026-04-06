"""Run via `python -m micro_local_claude`."""

from __future__ import annotations

import asyncio

from .cli import main


if __name__ == "__main__":
    asyncio.run(main())

