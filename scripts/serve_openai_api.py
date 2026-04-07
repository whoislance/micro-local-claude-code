#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer, TextStreamer

app = FastAPI()
model: AutoModelForCausalLM | None = None
tokenizer = None
runtime_device = "cpu"


class ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    temperature: float = 0.7
    top_p: float = 0.92
    max_tokens: int = 512
    stream: bool = True
    tools: list[dict[str, Any]] = Field(default_factory=list)
    open_thinking: bool = False
    chat_template_kwargs: dict[str, Any] | None = None

    def get_open_thinking(self) -> bool:
        if self.open_thinking:
            return True
        if not self.chat_template_kwargs:
            return False
        return bool(
            self.chat_template_kwargs.get("open_thinking")
            or self.chat_template_kwargs.get("enable_thinking")
        )


class QueueStreamer(TextStreamer):
    def __init__(self, tokenizer_instance, queue: Queue[str | None]) -> None:
        super().__init__(tokenizer_instance, skip_prompt=True, skip_special_tokens=True)
        self.queue = queue

    def on_finalized_text(self, text: str, stream_end: bool = False) -> None:
        self.queue.put(text)
        if stream_end:
            self.queue.put(None)


def load_runtime(load_from: Path, device: str) -> tuple[AutoModelForCausalLM, Any]:
    tokenizer_instance = AutoTokenizer.from_pretrained(load_from, trust_remote_code=True)
    kwargs: dict[str, Any] = {"trust_remote_code": True}
    if device in {"cuda", "mps"}:
        kwargs["torch_dtype"] = torch.float16
    model_instance = AutoModelForCausalLM.from_pretrained(load_from, **kwargs).eval()
    model_instance = model_instance.to(device)
    return model_instance, tokenizer_instance


def build_inputs(messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int, open_thinking: bool):
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        tools=tools or None,
        open_thinking=open_thinking,
    )[-max_tokens:]
    return tokenizer(prompt, return_tensors="pt", truncation=True).to(runtime_device)


def build_generate_kwargs(inputs: Any, temperature: float, top_p: float, max_tokens: int) -> dict[str, Any]:
    pad_token_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    generate_kwargs: dict[str, Any] = {
        "input_ids": inputs["input_ids"],
        "attention_mask": inputs["attention_mask"],
        "max_new_tokens": max_tokens,
        "pad_token_id": pad_token_id,
        "eos_token_id": tokenizer.eos_token_id,
    }
    if temperature > 0:
        generate_kwargs["do_sample"] = True
        generate_kwargs["temperature"] = temperature
        generate_kwargs["top_p"] = top_p
    else:
        generate_kwargs["do_sample"] = False
    return generate_kwargs


def parse_response(text: str) -> tuple[str, str | None, list[dict[str, Any]] | None]:
    reasoning_content = None
    if "<think>" in text and "</think>" in text:
        start = text.find("<think>") + len("<think>")
        end = text.find("</think>")
        reasoning_content = text[start:end].strip()
        text = (text[: text.find("<think>")] + text[end + len("</think>") :]).strip()
    elif "</think>" in text:
        parts = text.split("</think>", 1)
        reasoning_content = parts[0].strip()
        text = parts[1].strip() if len(parts) > 1 else ""

    tool_calls: list[dict[str, Any]] = []
    start = 0
    while True:
        tag_start = text.find("<tool_call>", start)
        if tag_start < 0:
            break
        tag_end = text.find("</tool_call>", tag_start)
        if tag_end < 0:
            break
        payload = text[tag_start + len("<tool_call>") : tag_end].strip()
        try:
            call = json.loads(payload)
            tool_calls.append(
                {
                    "id": f"call_{int(time.time() * 1000)}_{len(tool_calls)}",
                    "type": "function",
                    "function": {
                        "name": call.get("name", ""),
                        "arguments": json.dumps(call.get("arguments", {}), ensure_ascii=False),
                    },
                }
            )
        except Exception:
            pass
        start = tag_end + len("</tool_call>")

    if tool_calls:
        cleaned = text
        while True:
            tag_start = cleaned.find("<tool_call>")
            if tag_start < 0:
                break
            tag_end = cleaned.find("</tool_call>", tag_start)
            if tag_end < 0:
                break
            cleaned = (cleaned[:tag_start] + cleaned[tag_end + len("</tool_call>") :]).strip()
        text = cleaned

    return text.strip(), reasoning_content, tool_calls or None


def generate_stream_chunks(request: ChatRequest):
    inputs = build_inputs(
        request.messages,
        request.tools,
        request.max_tokens,
        request.get_open_thinking(),
    )
    queue: Queue[str | None] = Queue()
    streamer = QueueStreamer(tokenizer, queue)
    generate_kwargs = build_generate_kwargs(inputs, request.temperature, request.top_p, request.max_tokens)
    generate_kwargs["streamer"] = streamer

    def run_generation() -> None:
        with torch.no_grad():
            model.generate(**generate_kwargs)

    Thread(target=run_generation, daemon=True).start()

    full_text = ""
    emitted = 0
    thinking_done = not request.get_open_thinking()

    while True:
        piece = queue.get()
        if piece is None:
            break
        full_text += piece
        if not thinking_done:
            marker = full_text.find("</think>")
            if marker >= 0:
                thinking_done = True
                reasoning_piece = full_text[emitted:marker]
                if reasoning_piece:
                    yield json.dumps({"choices": [{"delta": {"reasoning_content": reasoning_piece}}]}, ensure_ascii=False)
                emitted = marker + len("</think>")
                content_piece = full_text[emitted:].lstrip("\n")
                emitted = len(full_text) - len(content_piece)
                if content_piece:
                    yield json.dumps({"choices": [{"delta": {"content": content_piece}}]}, ensure_ascii=False)
                    emitted = len(full_text)
            else:
                reasoning_piece = full_text[emitted:]
                if reasoning_piece:
                    yield json.dumps({"choices": [{"delta": {"reasoning_content": reasoning_piece}}]}, ensure_ascii=False)
                    emitted = len(full_text)
        else:
            content_piece = full_text[emitted:]
            if content_piece:
                yield json.dumps({"choices": [{"delta": {"content": content_piece}}]}, ensure_ascii=False)
                emitted = len(full_text)

    _, _, tool_calls = parse_response(full_text)
    if tool_calls:
        stream_tool_calls = []
        for index, item in enumerate(tool_calls):
            stream_tool_calls.append(
                {
                    "index": index,
                    "id": item["id"],
                    "type": item["type"],
                    "function": item["function"],
                }
            )
        yield json.dumps({"choices": [{"delta": {"tool_calls": stream_tool_calls}}]}, ensure_ascii=False)
    yield json.dumps(
        {"choices": [{"delta": {}, "finish_reason": "tool_calls" if tool_calls else "stop"}]},
        ensure_ascii=False,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    return {"data": [{"id": "minimind-local", "object": "model"}], "object": "list"}


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    try:
        if request.stream:
            async def event_stream():
                for chunk in generate_stream_chunks(request):
                    yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        inputs = build_inputs(
            request.messages,
            request.tools,
            request.max_tokens,
            request.get_open_thinking(),
        )
        generate_kwargs = build_generate_kwargs(inputs, request.temperature, request.top_p, request.max_tokens)
        with torch.no_grad():
            generated_ids = model.generate(**generate_kwargs)
        answer = tokenizer.decode(
            generated_ids[0][inputs["input_ids"].shape[1] :],
            skip_special_tokens=True,
        )
        content, reasoning_content, tool_calls = parse_response(answer)
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
            ],
        }
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Local OpenAI-compatible server for minimind-3")
    parser.add_argument("--load-from", default="models/minimind-3", help="Local model directory")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu", choices=["cpu", "cuda", "mps"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8998, type=int)
    args = parser.parse_args()

    load_from = Path(args.load_from).expanduser().resolve()
    if not load_from.exists():
        raise SystemExit(f"Model directory not found: {load_from}")

    global model, tokenizer, runtime_device
    runtime_device = args.device
    model, tokenizer = load_runtime(load_from, runtime_device)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
