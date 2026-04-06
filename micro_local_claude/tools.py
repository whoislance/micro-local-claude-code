"""Tool definitions and local tool runtime."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

ToolDef = Dict[str, Any]

tool_definitions: List[ToolDef] = [
    {
        "name": "read_file",
        "description": "Read file content and return numbered lines.",
        "input_schema": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write full content into a file (overwrite).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace one exact old_string with new_string in a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_files",
        "description": "List files matching a glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_search",
        "description": "Search matching lines in files with a regex pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "include": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_shell",
        "description": "Run a shell command and return output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["command"],
        },
    },
]

MAX_RESULT_CHARS = 50_000

DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s"),
    re.compile(r"\bgit\s+(push|reset|clean|checkout\s+\.)"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s"),
    re.compile(r">\s*/dev/"),
    re.compile(r"\bkill\b"),
    re.compile(r"\bpkill\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bshutdown\b"),
]


def read_file(input_data: Dict[str, Any]) -> str:
    try:
        file_path = Path(str(input_data["file_path"]))
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        return "\n".join(f"{i + 1:4} | {line}" for i, line in enumerate(lines))
    except Exception as error:
        return f"Error reading file: {error}"


def write_file(input_data: Dict[str, Any]) -> str:
    try:
        file_path = Path(str(input_data["file_path"]))
        content = str(input_data["content"])
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {file_path}"
    except Exception as error:
        return f"Error writing file: {error}"


def edit_file(input_data: Dict[str, Any]) -> str:
    try:
        file_path = Path(str(input_data["file_path"]))
        old_string = str(input_data["old_string"])
        new_string = str(input_data["new_string"])
        content = file_path.read_text(encoding="utf-8")
        matches = content.count(old_string)
        if matches == 0:
            return f"Error: old_string not found in {file_path}"
        if matches > 1:
            return f"Error: old_string found {matches} times. Must be unique."
        file_path.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return f"Successfully edited {file_path}"
    except Exception as error:
        return f"Error editing file: {error}"


def list_files(input_data: Dict[str, Any]) -> str:
    try:
        pattern = str(input_data["pattern"])
        base = Path(str(input_data.get("path", os.getcwd())))
        files: List[str] = []
        for path in base.glob(pattern):
            if not path.is_file():
                continue
            normalized = path.as_posix()
            if "/.git/" in normalized or "/node_modules/" in normalized:
                continue
            files.append(str(path.relative_to(base)).replace("\\", "/"))
        if not files:
            return "No files found matching the pattern."
        files.sort()
        return "\n".join(files[:200])
    except Exception as error:
        return f"Error listing files: {error}"


def grep_search(input_data: Dict[str, Any]) -> str:
    try:
        pattern = str(input_data["pattern"])
        target = Path(str(input_data.get("path", ".")))
        include = str(input_data.get("include", "*"))
        regex = re.compile(pattern)
        matches: List[str] = []
        files = [target] if target.is_file() else [p for p in target.rglob("*") if p.is_file()]
        for file_path in files:
            normalized = file_path.as_posix()
            if "/.git/" in normalized or "/node_modules/" in normalized:
                continue
            if include and not fnmatch.fnmatch(file_path.name, include):
                continue
            try:
                text = file_path.read_text(encoding="utf-8")
            except Exception:
                continue
            for idx, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{normalized}:{idx}:{line}")
        if not matches:
            return "No matches found."
        return "\n".join(matches[:200])
    except re.error as error:
        return f"Error: invalid regex pattern ({error})"
    except Exception as error:
        return f"Error: {error}"


def run_shell(input_data: Dict[str, Any]) -> str:
    command = str(input_data.get("command", ""))
    timeout_ms = int(input_data.get("timeout", 30_000))
    try:
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(timeout_ms / 1000.0, 0.001),
        )
        if completed.returncode == 0:
            return completed.stdout or "(no output)"
        out = f"\nStdout: {completed.stdout}" if completed.stdout else ""
        err = f"\nStderr: {completed.stderr}" if completed.stderr else ""
        return f"Command failed (exit code {completed.returncode}){out}{err}"
    except subprocess.TimeoutExpired:
        return f"Command failed (timeout after {timeout_ms} ms)"
    except Exception as error:
        return f"Command failed: {error}"


def needs_confirmation(tool_name: str, input_data: Dict[str, Any]) -> Optional[str]:
    if tool_name == "run_shell":
        command = str(input_data.get("command", ""))
        if any(pattern.search(command) for pattern in DANGEROUS_PATTERNS):
            return command
    if tool_name == "write_file":
        file_path = Path(str(input_data.get("file_path", "")))
        if not file_path.exists():
            return f"write new file: {file_path}"
    if tool_name == "edit_file":
        file_path = Path(str(input_data.get("file_path", "")))
        if not file_path.exists():
            return f"edit non-existent file: {file_path}"
    return None


def to_openai_tools() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item["description"],
                "parameters": item["input_schema"],
            },
        }
        for item in tool_definitions
    ]


def truncate_result(result: str) -> str:
    if len(result) <= MAX_RESULT_CHARS:
        return result
    keep_each = (MAX_RESULT_CHARS - 60) // 2
    omitted = len(result) - keep_each * 2
    return result[:keep_each] + f"\n\n[... truncated {omitted} chars ...]\n\n" + result[-keep_each:]


async def execute_tool(name: str, input_data: Dict[str, Any]) -> str:
    handlers = {
        "read_file": read_file,
        "write_file": write_file,
        "edit_file": edit_file,
        "list_files": list_files,
        "grep_search": grep_search,
        "run_shell": run_shell,
    }
    handler = handlers.get(name)
    if handler is None:
        return f"Unknown tool: {name}"
    return truncate_result(await asyncio.to_thread(handler, input_data))

