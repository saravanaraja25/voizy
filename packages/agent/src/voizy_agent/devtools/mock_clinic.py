"""A tiny in-memory dental-clinic backend for exercising tools locally.

    uv run python -m voizy_agent.devtools.mock_clinic --port 8099 --delay-ms 1500

The delay applies to availability and booking so filler speech is easy to hear. Extra routes
(/redirect, /big, /slow) exist only so the tool executor's safety limits can be tested.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from datetime import date as Date
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

SLOTS = ("09:00", "10:30", "14:00", "16:30")
_TIME = re.compile(r"^\d{2}:\d{2}$")


class AppointmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=5, max_length=30)
    date: Date
    time: str = Field(pattern=_TIME.pattern)


def create_mock_app(delay_ms: int = 0) -> FastAPI:
    app = FastAPI(title="Mock clinic", docs_url=None, redoc_url=None)
    booked: dict[tuple[Date, str], str] = {}

    async def pause() -> None:
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)

    @app.get("/availability")
    async def availability(date: Annotated[Date, Query()]) -> dict[str, object]:
        await pause()
        if date.weekday() == 6:  # Sunday
            return {"date": date.isoformat(), "open": False, "slots": []}
        free = [s for s in SLOTS if (date, s) not in booked]
        return {"date": date.isoformat(), "open": True, "slots": free}

    @app.post("/appointments", status_code=201)
    async def book(req: AppointmentRequest) -> dict[str, str]:
        await pause()
        if req.time not in SLOTS or req.date.weekday() == 6:
            raise HTTPException(422, f"no appointments at {req.time} on {req.date.isoformat()}")
        if (req.date, req.time) in booked:
            raise HTTPException(409, "that time is already booked")
        confirmation = "BS-" + uuid.uuid4().hex[:6].upper()
        booked[(req.date, req.time)] = confirmation
        return {
            "confirmation_id": confirmation,
            "name": req.name,
            "date": req.date.isoformat(),
            "time": req.time,
        }

    @app.get("/redirect")
    async def redirect() -> RedirectResponse:
        return RedirectResponse("http://169.254.169.254/latest/meta-data/", status_code=302)

    @app.get("/big", response_class=PlainTextResponse)
    async def big() -> str:
        return "x" * 100_000

    @app.get("/slow")
    async def slow(ms: int = 1000) -> dict[str, bool]:
        await asyncio.sleep(min(ms, 10_000) / 1000)
        return {"ok": True}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the mock clinic API (loopback only).")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--delay-ms", type=int, default=1500)
    args = parser.parse_args()
    uvicorn.run(
        create_mock_app(args.delay_ms), host="127.0.0.1", port=args.port, log_level="warning"
    )


if __name__ == "__main__":
    main()
