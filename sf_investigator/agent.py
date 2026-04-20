from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Iterable

from openai import OpenAI

from .prompt import SYSTEM_PROMPT
from .tool_defs import TOOL_DEFS, TOOL_IMPL


def _client() -> OpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


def _run_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = TOOL_IMPL.get(name)
    if not fn:
        return {"error": f"unknown tool: {name}"}
    try:
        return fn(**args)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _default_max_turns() -> int:
    try:
        return int(os.environ.get("LLM_MAX_TURNS", "12"))
    except ValueError:
        return 12


def run_investigation(
    user_prompt: str,
    *,
    model: str | None = None,
    max_turns: int | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if max_turns is None:
        max_turns = _default_max_turns()
    """
    Run a tool-calling investigation. Returns {report, turns, tool_calls, messages}.

    `on_event` is called with dicts like:
      {"type": "assistant_text", "text": ...}
      {"type": "tool_call", "name": ..., "arguments": ..., "call_id": ...}
      {"type": "tool_result", "call_id": ..., "name": ..., "result": ...}
      {"type": "final", "report": ...}
    """
    model = model or os.environ.get("MODEL", "anthropic/claude-sonnet-4.5")
    client = _client()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    tool_calls_log: list[dict[str, Any]] = []

    def emit(e: dict[str, Any]) -> None:
        if on_event:
            on_event(e)

    for turn in range(max_turns):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            tools=TOOL_DEFS,  # type: ignore[arg-type]
            tool_choice="auto",
            temperature=0.2,
        )
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []

        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ]
                if tool_calls
                else None,
            }
        )
        if msg.content:
            emit({"type": "assistant_text", "text": msg.content})

        if not tool_calls:
            emit({"type": "final", "report": msg.content or ""})
            return {
                "report": msg.content or "",
                "turns": turn + 1,
                "tool_calls": tool_calls_log,
                "messages": messages,
            }

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            emit({"type": "tool_call", "name": name, "arguments": args, "call_id": tc.id})
            t0 = time.time()
            result = _run_tool(name, args)
            elapsed_ms = int((time.time() - t0) * 1000)
            tool_calls_log.append(
                {"name": name, "arguments": args, "result": result, "elapsed_ms": elapsed_ms}
            )
            emit({"type": "tool_result", "call_id": tc.id, "name": name, "result": result, "elapsed_ms": elapsed_ms})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str)[:48000],
                }
            )

    return {
        "report": "(max turns reached without a final report)",
        "turns": max_turns,
        "tool_calls": tool_calls_log,
        "messages": messages,
    }
