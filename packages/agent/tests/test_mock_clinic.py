from __future__ import annotations

import httpx
import pytest
from voizy_agent.devtools.mock_clinic import SLOTS, create_mock_app

pytestmark = pytest.mark.asyncio
BOOKING = {"name": "Sam", "phone": "5551234567", "date": "2026-11-10", "time": "10:30"}  # Tuesday


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_mock_app()), base_url="http://t"
    )


async def test_availability_open_closed_and_invalid() -> None:
    async with client() as c:
        tue = (await c.get("/availability", params={"date": "2026-11-10"})).json()
        assert tue == {"date": "2026-11-10", "open": True, "slots": list(SLOTS)}
        sun = (await c.get("/availability", params={"date": "2026-11-08"})).json()
        assert sun["open"] is False and sun["slots"] == []
        assert (await c.get("/availability", params={"date": "tomorrow"})).status_code == 422


async def test_booking_removes_slot_and_rejects_double_booking() -> None:
    async with client() as c:
        r = await c.post("/appointments", json=BOOKING)
        assert r.status_code == 201 and r.json()["confirmation_id"].startswith("BS-")
        slots = (await c.get("/availability", params={"date": "2026-11-10"})).json()["slots"]
        assert "10:30" not in slots
        assert (await c.post("/appointments", json=BOOKING)).status_code == 409


async def test_booking_validation() -> None:
    async with client() as c:
        for bad in (
            {**BOOKING, "time": "07:00"},  # outside hours
            {**BOOKING, "date": "2026-11-08"},  # Sunday
        ):
            assert (await c.post("/appointments", json=bad)).status_code == 422
        assert (await c.post("/appointments", json={**BOOKING, "extra": 1})).status_code == 422
