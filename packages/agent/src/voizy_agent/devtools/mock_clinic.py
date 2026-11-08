"""A tiny in-memory dental-clinic backend for exercising tools locally.

    uv run python -m voizy_agent.devtools.mock_clinic --port 8099 --delay-ms 1500

The delay applies to availability and booking so filler speech is easy to hear. Extra routes
(/redirect, /big, /slow) exist only so the tool executor's safety limits can be tested.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import re
import uuid
from datetime import date as Date
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

# A well-known key for local development and tests. Not a secret.
DEV_API_KEY = "dev-clinic-key-0123456789"  # noqa: S105
SLOTS = ("09:00", "10:30", "14:00", "16:30")
_TIME = re.compile(r"^\d{2}:\d{2}$")


class AppointmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=5, max_length=30)
    date: Date
    time: str = Field(pattern=_TIME.pattern)


def create_mock_app(delay_ms: int = 0, api_key: str | None = None) -> FastAPI:
    """With api_key set, /availability and /appointments require it (bearer, X-Api-Key or basic)."""
    app = FastAPI(title="Mock clinic", docs_url=None, redoc_url=None)
    app.state.hits = []  # every authenticated-endpoint request, so tests can see what arrived
    booked: dict[tuple[Date, str], str] = {}

    def authenticate(request: Request) -> str:
        h = request.headers
        scheme = None
        if api_key is None:
            scheme = "none"
        elif h.get("authorization") == f"Bearer {api_key}":
            scheme = "bearer"
        elif h.get("x-api-key") == api_key:
            scheme = "header"
        elif (
            h.get("authorization")
            == "Basic " + base64.b64encode(f"clinic:{api_key}".encode()).decode()
        ):
            scheme = "basic"
        app.state.hits.append(scheme)
        if scheme is None:
            raise HTTPException(401, "missing or wrong credentials")
        return scheme

    async def pause() -> None:
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)

    @app.get("/availability")
    async def availability(request: Request, date: Annotated[Date, Query()]) -> dict[str, object]:
        authenticate(request)
        await pause()
        if date.weekday() == 6:  # Sunday
            return {"date": date.isoformat(), "open": False, "slots": []}
        free = [s for s in SLOTS if (date, s) not in booked]
        return {"date": date.isoformat(), "open": True, "slots": free}

    @app.post("/appointments", status_code=201)
    async def book(request: Request, req: AppointmentRequest) -> dict[str, str]:
        authenticate(request)
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

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, str]:
        return {"scheme": authenticate(request)}

    @app.get("/_hits")
    async def hits() -> list[str]:
        """Which auth scheme each data request used (None = rejected). For tests and demos."""
        return [str(h) for h in app.state.hits]

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
    parser.add_argument("--api-key", default=None, help="require this key on the data endpoints")
    args = parser.parse_args()
    uvicorn.run(
        create_mock_app(args.delay_ms, args.api_key),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
