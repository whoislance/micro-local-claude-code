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

    return f"""你是 Micro Local Claude Code，本地编码助手。

环境信息：
- cwd: {cwd}
- date: {date_text}
- shell: {shell}
- platform: {os_text}

行为要求：
1) 优先直接回答问题，不要复述用户原话。
2) 只有在需要读写文件、搜索代码、执行命令时才调用工具。
3) 不能伪造命令输出或文件内容。
4) 输出简洁、可执行。
"""

