"""OpenAI-compatible local agent loop for MiniMind."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
        quick_answer = self._try_quick_math(user_text)
        if quick_answer is not None:
            print(f"\n{quick_answer}\n")
            self.messages.append({"role": "user", "content": user_text})
            self.messages.append({"role": "assistant", "content": quick_answer})
            return

        self.messages.append({"role": "user", "content": user_text})
        use_tools = self._should_enable_tools(user_text)
        if not use_tools:
            try:
                response = await self._call_openai_non_stream_with_retry(user_text=user_text, use_tools=False)
            except RuntimeError as error:
                print(f"\n[error] {error}")
                print("\n")
                return
            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            self.messages.append(message)
            print("\n")
            return

        while True:
            try:
                response = await self._call_openai_stream_with_fallback(user_text=user_text, use_tools=True)
            except RuntimeError as error:
                print(f"\n[error] {error}")
                print("\n")
                break
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

    async def _call_openai_stream_with_fallback(self, user_text: str, use_tools: bool) -> Dict[str, Any]:
        """Prefer streaming for UX, fallback to non-stream on compatibility issues."""
        try:
            response = await self._call_openai_stream(use_tools=use_tools)
            if not self._has_payload(response):
                print("\n[info] Empty streamed response, retrying with non-stream mode...")
                return await self._call_openai_non_stream_with_retry(user_text=user_text, use_tools=use_tools)
            return response
        except Exception as error:
            print(f"\n[warn] Stream mode failed ({type(error).__name__}), fallback to non-stream.")
            return await self._call_openai_non_stream_with_retry(user_text=user_text, use_tools=use_tools)

    async def _call_openai_stream(self, use_tools: bool) -> Dict[str, Any]:
        def _sync_call() -> Dict[str, Any]:
            max_tokens = 256 if use_tools else 96
            create_kwargs: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": self._build_messages_for_model(use_tools=use_tools),
                "stream": True,
                "temperature": 0.2,
            }
            if use_tools:
                create_kwargs["tools"] = to_openai_tools()

            stream = self.client.chat.completions.create(
                **create_kwargs,
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

    async def _call_openai_non_stream(self, use_tools: bool) -> Dict[str, Any]:
        def _sync_call() -> Dict[str, Any]:
            max_tokens = 256 if use_tools else 96
            create_kwargs: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": self._build_messages_for_model(use_tools=use_tools),
                "stream": False,
                "temperature": 0.2,
            }
            if use_tools:
                create_kwargs["tools"] = to_openai_tools()

            response = self.client.chat.completions.create(**create_kwargs)
            response_dict = self._model_to_dict(response)
            message = response_dict.get("choices", [{}])[0].get("message", {})
            content = self._clean_response_text(message.get("content"))
            message["content"] = content
            if content:
                print(f"\n{content}", end="", flush=True)
            return response_dict

        return await asyncio.to_thread(_sync_call)

    async def _call_openai_non_stream_with_retry(
        self, user_text: str, use_tools: bool, max_attempts: int = 2
    ) -> Dict[str, Any]:
        last_response: Dict[str, Any] = {}
        for attempt in range(1, max_attempts + 1):
            response = await self._call_openai_non_stream(use_tools=use_tools)
            last_response = response
            if self._has_payload(response) and not self._looks_like_echo(user_text, response):
                return response
            if attempt < max_attempts:
                print(
                    f"\n[warn] Non-stream response is empty or echoed input, retrying ({attempt}/{max_attempts})..."
                )
                await asyncio.sleep(0.3)
        raise RuntimeError("Model returned empty/echo response in both stream and non-stream modes.")

    def _has_payload(self, response: Dict[str, Any]) -> bool:
        message = response.get("choices", [{}])[0].get("message", {})
        text = (message.get("content") or "").strip()
        tool_calls = message.get("tool_calls")
        return bool(text or tool_calls)

    def _build_messages_for_model(self, use_tools: bool) -> List[Dict[str, Any]]:
        # For tiny models, plain chat works better as stateless single-turn.
        if not use_tools:
            last_user = ""
            for item in reversed(self.messages):
                if item.get("role") == "user":
                    last_user = str(item.get("content", ""))
                    break
            return [{"role": "user", "content": last_user}]

        # Tool mode keeps short history + system prompt.
        if len(self.messages) <= 12:
            return self.messages
        return [self.messages[0], *self.messages[-10:]]

    def _clean_response_text(self, content: Any) -> str:
        text = str(content or "").strip()
        return " ".join(text.split())

    def _looks_like_echo(self, user_text: str, response: Dict[str, Any]) -> bool:
        message = response.get("choices", [{}])[0].get("message", {})
        text = self._clean_response_text(message.get("content"))
        if not text:
            return True
        user = self._clean_response_text(user_text)
        user_norm = self._normalize_for_compare(user)
        text_norm = self._normalize_for_compare(text)
        if not user:
            return False
        if text == user or text_norm == user_norm:
            return True
        if user_norm and text_norm.startswith(user_norm) and len(text_norm) <= len(user_norm) + 3:
            return True
        return text_norm.count(user_norm) >= 2 and len(text_norm) <= len(user_norm) * 4

    def _should_enable_tools(self, user_text: str) -> bool:
        lowered = user_text.lower()
        tool_hints = [
            "文件",
            "read",
            "write",
            "edit",
            "代码",
            "shell",
            "命令",
            "目录",
            "grep",
            "运行",
            "测试",
            "script",
            "git",
        ]
        return any(token in lowered for token in tool_hints)

    def _normalize_for_compare(self, text: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", text.lower())

    def _try_quick_math(self, user_text: str) -> Optional[str]:
        candidate = user_text.strip().replace(" ", "")
        if not candidate:
            return None
        if not re.fullmatch(r"[0-9\.\+\-\*\/\(\)]+", candidate):
            return None
        try:
            value = eval(candidate, {"__builtins__": {}}, {})
        except Exception:
            return None
        return str(value)

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

