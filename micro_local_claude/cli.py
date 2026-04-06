"""CLI for micro local claude code."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .agent import Agent, AgentOptions


@dataclass
class CliArgs:
    model: str
    api_base: str
    api_key: str
    yolo: bool
    auto_start_server: bool
    server_script: str
    model_path: str
    device: str
    server_log_file: Optional[str]
    prompt: Optional[str]


def parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(description="Micro local claude code (MiniMind backend).")
    parser.add_argument("--model", default="minimind-local", help="Model name sent to local API server.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8998/v1", help="OpenAI-compatible API base URL.")
    parser.add_argument("--api-key", default="sk-local", help="API key for local API server.")
    parser.add_argument("--yolo", action="store_true", help="Skip dangerous action confirmation.")
    parser.add_argument(
        "--no-auto-start-server",
        action="store_true",
        help="Do not auto-start minimind/scripts/serve_openai_api.py when port is unavailable.",
    )
    parser.add_argument(
        "--server-script",
        default="../minimind/scripts/serve_openai_api.py",
        help="Path to MiniMind serve_openai_api.py script.",
    )
    parser.add_argument(
        "--model-path",
        default="../minimind/model",
        help="Model directory passed to --load_from when auto-starting MiniMind server.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["cpu", "cuda", "mps"],
        help="Device passed to MiniMind API server.",
    )
    parser.add_argument(
        "--server-log-file",
        default=None,
        help="Optional server log file path. If omitted, logs go to .micro-local-claude/logs/",
    )
    parser.add_argument("prompt", nargs="*", help="One-shot prompt. If omitted, start REPL.")
    parsed = parser.parse_args()
    return CliArgs(
        model=parsed.model,
        api_base=parsed.api_base,
        api_key=parsed.api_key,
        yolo=parsed.yolo,
        auto_start_server=not parsed.no_auto_start_server,
        server_script=parsed.server_script,
        model_path=parsed.model_path,
        device=parsed.device,
        server_log_file=parsed.server_log_file,
        prompt=" ".join(parsed.prompt) if parsed.prompt else None,
    )


def parse_host_port(api_base: str) -> tuple[str, int]:
    parsed = urlparse(api_base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def apply_local_proxy_bypass(api_base: str) -> None:
    """Avoid proxying localhost requests, which commonly causes local 502 errors."""
    host, _ = parse_host_port(api_base)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(key, None)

    existing = os.environ.get("NO_PROXY", "")
    values = [item.strip() for item in existing.split(",") if item.strip()]
    for target in ("127.0.0.1", "localhost", "::1"):
        if target not in values:
            values.append(target)
    os.environ["NO_PROXY"] = ",".join(values)


def is_port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def maybe_start_local_server(args: CliArgs) -> Optional[subprocess.Popen]:
    host, port = parse_host_port(args.api_base)
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if host not in local_hosts:
        return None
    if is_port_open(host, port):
        return None
    if not args.auto_start_server:
        raise RuntimeError(
            f"API server {args.api_base} is not reachable. Remove --no-auto-start-server or start MiniMind server manually."
        )

    script_path = Path(args.server_script).resolve()
    # Keep symlink path as-is (absolute path only), because resolving symlink may
    # break MiniMind's load_from branch detection in serve_openai_api.py.
    model_path = Path(args.model_path).expanduser()
    if not model_path.is_absolute():
        model_path = (Path.cwd() / model_path).absolute()
    if not script_path.exists():
        raise RuntimeError(f"Server script not found: {script_path}")
    if not model_path.exists():
        raise RuntimeError(
            f"Model path not found: {model_path}\n"
            "Download a MiniMind transformers model first, then pass --model-path /path/to/model."
        )
    load_from_path = prepare_minimind_load_from_path(model_path)

    log_file = resolve_server_log_file(args.server_log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_fp = log_file.open("a", encoding="utf-8")
    log_fp.write(
        f"\n[{datetime.now().isoformat()}] starting server "
        f"load_from={load_from_path} device={args.device}\n"
    )
    log_fp.flush()

    process = subprocess.Popen(
        [
            sys.executable,
            str(script_path),
            "--load_from",
            str(load_from_path),
            "--device",
            args.device,
        ],
        cwd=str(script_path.parent),
        stdout=log_fp,
        stderr=log_fp,
    )
    log_fp.close()

    deadline = time.time() + 30.0
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "MiniMind API server exited during startup. "
                f"Check log: {log_file}"
            )
        if is_port_open(host, port):
            print(f"[info] Local MiniMind API server started at {args.api_base}")
            print(f"[info] Server log: {log_file}")
            return process
        time.sleep(0.5)

    process.terminate()
    raise RuntimeError(f"MiniMind API server startup timeout (30s). Check log: {log_file}")


def prepare_minimind_load_from_path(model_path: Path) -> Path:
    """Prepare a robust load_from path for MiniMind server."""
    text = model_path.as_posix().lower()
    if "model" not in text:
        return model_path

    # MiniMind's serve_openai_api.py uses string matching on "model" to branch loading logic.
    # Create a symlink path without "model" in its name to force transformers loading.
    runtime_link = (Path.cwd() / ".micro-local-claude" / "runtime" / "minimind3").absolute()
    runtime_link.parent.mkdir(parents=True, exist_ok=True)
    if runtime_link.exists() or runtime_link.is_symlink():
        runtime_link.unlink()
    runtime_link.symlink_to(model_path, target_is_directory=True)
    return runtime_link


def resolve_server_log_file(log_path: Optional[str]) -> Path:
    if log_path:
        return Path(log_path).resolve()
    base = Path.cwd() / ".micro-local-claude" / "logs"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return (base / f"minimind-server-{ts}.log").resolve()


def stop_server(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


async def run_repl(agent: Agent) -> None:
    print("Micro Local Claude Code")
    print("Type your request and press Enter.")
    print("Commands: /help  /clear  /status  /exit")

    while True:
        try:
            line = input("\n> ")
        except EOFError:
            print("\nBye!")
            return
        user_input = line.strip()
        if not user_input:
            continue
        if user_input in {"exit", "quit"}:
            print("\nBye!")
            return
        if user_input == "/help":
            print("\nCommands:")
            print("  /help    Show this help")
            print("  /clear   Clear current conversation history")
            print("  /status  Show current model and message count")
            print("  /exit    Quit")
            continue
        if user_input == "/clear":
            agent.messages = [agent.messages[0]]
            print("[info] Cleared conversation history.")
            continue
        if user_input == "/status":
            print(f"[info] model={agent.model}")
            print(f"[info] messages={len(agent.messages)}")
            continue
        if user_input == "/exit":
            print("\nBye!")
            return
        await agent.chat(user_input)


async def main() -> None:
    args = parse_args()
    apply_local_proxy_bypass(args.api_base)
    try:
        server_process = maybe_start_local_server(args)
    except RuntimeError as error:
        print(f"[error] {error}")
        raise SystemExit(1)

    def _signal_handler(signum, frame) -> None:  # noqa: ANN001
        del signum, frame
        stop_server(server_process)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        try:
            agent = Agent(
                AgentOptions(model=args.model, api_base=args.api_base, api_key=args.api_key, yolo=args.yolo)
            )
        except RuntimeError as error:
            print(f"[error] {error}")
            raise SystemExit(1)
        if args.prompt:
            await agent.chat(args.prompt)
        else:
            await run_repl(agent)
    finally:
        stop_server(server_process)

