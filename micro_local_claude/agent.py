"""OpenAI-compatible local agent loop for MiniMind."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from .prompt import build_system_prompt
from .tools import execute_tool, needs_confirmation, to_openai_tools


@dataclass
class AgentOptions:
    model: str = "minimind-local"
    api_base: str = "http://127.0.0.1:8998/v1"
    api_key: str = "sk-local"
    yolo: bool = False


class Agent:
    def __init__(self, options: AgentOptions) -> None:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError("openai package is required. Run: pip install -r requirements.txt") from error

        self.model = options.model
        self.yolo = options.yolo
        self.client = OpenAI(api_key=options.api_key, base_url=options.api_base)
        self.messages: List[Dict[str, Any]] = [{"role": "system", "content": build_system_prompt()}]
        self.confirmed_actions: set[str] = set()

    async def chat(self, user_text: str) -> None:
        self.messages.append({"role": "user", "content": user_text})
        while True:
            response = await self._call_openai_stream_with_fallback()
            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls")
            self.messages.append(message)
            if not tool_calls:
                print("\n")
                break
            for tool_call in tool_calls:
                if tool_call.get("type") != "function":
                    continue
                name = tool_call.get("function", {}).get("name", "")
                arguments_text = tool_call.get("function", {}).get("arguments", "{}")
                try:
                    input_data = json.loads(arguments_text)
                except Exception:
                    input_data = {}
                print(f"\n[tool] {name} {input_data}")
                if not self.yolo:
                    confirm_msg = needs_confirmation(name, input_data)
                    if confirm_msg and confirm_msg not in self.confirmed_actions:
                        if not self._confirm(confirm_msg):
                            self.messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.get("id", ""),
                                    "content": "User denied this action.",
                                }
                            )
                            continue
                        self.confirmed_actions.add(confirm_msg)
                result = await execute_tool(name, input_data)
                print(result[:500] + ("..." if len(result) > 500 else ""))
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": result,
                    }
                )

    def _confirm(self, text: str) -> bool:
        answer = input(f"\n[confirm] {text}\nAllow? (y/n): ").strip().lower()
        return answer.startswith("y")

    async def _call_openai_stream_with_fallback(self) -> Dict[str, Any]:
        """Prefer streaming for UX, fallback to non-stream on compatibility issues."""
        try:
            response = await self._call_openai_stream()
            message = response.get("choices", [{}])[0].get("message", {})
            text = (message.get("content") or "").strip()
            tool_calls = message.get("tool_calls")
            # Some local OpenAI-compatible services occasionally return empty streamed text.
            if not text and not tool_calls:
                print("\n[info] Empty streamed response, retrying with non-stream mode...")
                return await self._call_openai_non_stream()
            return response
        except Exception as error:
            print(f"\n[warn] Stream mode failed ({type(error).__name__}), fallback to non-stream.")
            return await self._call_openai_non_stream()

    async def _call_openai_stream(self) -> Dict[str, Any]:
        def _sync_call() -> Dict[str, Any]:
            stream = self.client.chat.completions.create(
                model=self.model,
                max_tokens=1536,
                tools=to_openai_tools(),
                messages=self.messages,
                stream=True,
            )
            content = ""
            first_text = True
            tool_calls: Dict[int, Dict[str, str]] = {}
            finish_reason = ""
            for chunk in stream:
                chunk_dict = self._model_to_dict(chunk)
                choices = chunk_dict.get("choices", [])
                if not choices:
                    continue
                choice0 = choices[0]
                delta = choice0.get("delta", {})
                delta_content = delta.get("content")
                if delta_content:
                    if first_text:
                        print("", flush=True)
                        first_text = False
                    print(delta_content, end="", flush=True)
                    content += delta_content
                for tc in delta.get("tool_calls", []) or []:
                    index = int(tc.get("index") or 0)
                    existing = tool_calls.get(index)
                    if existing is None:
                        tool_calls[index] = {
                            "id": tc.get("id", ""),
                            "name": tc.get("function", {}).get("name", ""),
                            "arguments": tc.get("function", {}).get("arguments", ""),
                        }
                    else:
                        new_args = tc.get("function", {}).get("arguments", "")
                        if new_args:
                            existing["arguments"] += new_args
                if choice0.get("finish_reason"):
                    finish_reason = str(choice0["finish_reason"])
            assembled_tool_calls = []
            for index in sorted(tool_calls):
                item = tool_calls[index]
                assembled_tool_calls.append(
                    {
                        "id": item["id"] or f"tool_{index}_{int(time.time())}",
                        "type": "function",
                        "function": {"name": item["name"], "arguments": item["arguments"]},
                    }
                )
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": content or None,
                            "tool_calls": assembled_tool_calls or None,
                        },
                        "finish_reason": finish_reason or "stop",
                    }
                ]
            }

        return await asyncio.to_thread(_sync_call)

    async def _call_openai_non_stream(self) -> Dict[str, Any]:
        def _sync_call() -> Dict[str, Any]:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=1536,
                tools=to_openai_tools(),
                messages=self.messages,
                stream=False,
            )
            response_dict = self._model_to_dict(response)
            message = response_dict.get("choices", [{}])[0].get("message", {})
            content = message.get("content")
            if content:
                print(f"\n{content}", end="", flush=True)
            return response_dict

        return await asyncio.to_thread(_sync_call)

    def _model_to_dict(self, obj: Any) -> Dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            try:
                return obj.model_dump()
            except Exception:
                return {}
        if hasattr(obj, "to_dict"):
            try:
                return obj.to_dict()
            except Exception:
                return {}
        if hasattr(obj, "__dict__"):
            try:
                return dict(obj.__dict__)
            except Exception:
                return {}
        return {}

