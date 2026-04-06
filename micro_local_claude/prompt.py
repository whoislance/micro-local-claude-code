"""System prompt builder."""

from __future__ import annotations

import os
import platform
from datetime import datetime
from pathlib import Path


def build_system_prompt() -> str:
    """Build a concise system prompt for local coding assistant."""
    cwd = Path.cwd().as_posix()
    date_text = datetime.now().strftime("%Y-%m-%d")
    shell = os.environ.get("SHELL", "unknown")
    os_text = f"{platform.system().lower()} {platform.machine().lower()}"

    return f"""You are Micro Local Claude Code, a local coding assistant.

Environment:
- cwd: {cwd}
- date: {date_text}
- shell: {shell}
- platform: {os_text}

Rules:
1) Prefer short, actionable answers.
2) Use tools when file read/write/search/shell is needed.
3) Never fabricate command output.
4) Keep edits minimal and safe.
"""

