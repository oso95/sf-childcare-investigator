from __future__ import annotations

import json
import os
import queue
import threading
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# .env.local (gitignored, for secrets) wins over .env if both exist.
load_dotenv(".env.local", override=False)
load_dotenv(".env", override=False)

from sf_investigator.agent import _default_max_turns, run_investigation  # noqa: E402

app = FastAPI(title="sf-childcare-investigator")
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse("frontend/index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "sf-childcare-investigator"}


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {
        "default_max_turns": _default_max_turns(),
        "default_model": os.environ.get("MODEL", "anthropic/claude-sonnet-4.5"),
    }


class InvestigateRequest(BaseModel):
    prompt: str
    max_turns: int | None = None
    model: str | None = None


@app.post("/api/investigate")
def investigate(req: InvestigateRequest) -> dict[str, Any]:
    result = run_investigation(req.prompt, model=req.model, max_turns=req.max_turns)
    return {
        "report": result["report"],
        "turns": result["turns"],
        "tool_calls": result["tool_calls"],
    }


@app.post("/api/investigate/stream")
def investigate_stream(req: InvestigateRequest) -> StreamingResponse:
    q: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def run() -> None:
        try:
            run_investigation(
                req.prompt,
                model=req.model,
                max_turns=req.max_turns,
                on_event=q.put,
            )
        except Exception as e:
            q.put({"type": "error", "error": str(e)})
        finally:
            q.put(None)

    threading.Thread(target=run, daemon=True).start()

    def gen():
        while True:
            event = q.get()
            if event is None:
                yield "event: done\ndata: {}\n\n"
                return
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
