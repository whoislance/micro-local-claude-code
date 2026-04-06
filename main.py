"""Compatibility launcher from repository root."""

from __future__ import annotations

import asyncio

from micro_local_claude.cli import main


if __name__ == "__main__":
    asyncio.run(main())

