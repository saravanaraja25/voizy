from __future__ import annotations

import httpx
import pytest
from voizy_agent.devtools.mock_shop import create_mock_app


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_mock_app()), base_url="http://shop"
    )


async def test_order_lookup_needs_the_matching_postcode_and_never_reveals_existence(
    client: httpx.AsyncClient,
) -> None:
    ok = await client.get("/orders/status", params={"order_id": "#1001", "zip": "94107"})
    assert (
        ok.status_code == 200
        and ok.json()["status"] == "shipped"
        and "tracking_number" in ok.json()
    )
    wrong_zip = await client.get("/orders/status", params={"order_id": "1001", "zip": "00000"})
    missing = await client.get("/orders/status", params={"order_id": "9999", "zip": "00000"})
    assert wrong_zip.status_code == missing.status_code == 404
    assert wrong_zip.json() == missing.json()


async def test_returns_follow_the_policy(client: httpx.AsyncClient) -> None:
    body = {"order_id": "1002", "zip": "10001", "sku": "RUN-SHOE-42", "reason": "too small"}
    assert (await client.post("/returns", json=body)).status_code == 201
    assert (await client.post("/returns", json={**body, "sku": "TENT-2P"})).status_code == 422
    old = {"order_id": "1004", "zip": "73301", "sku": "TENT-2P"}
    r = await client.post("/returns", json=old)
    assert r.status_code == 409 and "window" in r.json()["detail"]
    shipped = {"order_id": "1001", "zip": "94107", "sku": "TRAIL-JKT-M"}
    assert (await client.post("/returns", json=shipped)).status_code == 409


async def test_products_and_checkout_links(client: httpx.AsyncClient) -> None:
    found = (await client.get("/products", params={"query": "jacket"})).json()
    assert {p["sku"] for p in found["products"]} == {"TRAIL-JKT-M", "FLEECE-L"}
    sent = await client.post(
        "/checkout-links", json={"sku": "FLEECE-L", "size": "L", "phone": "+14155550134"}
    )
    assert sent.status_code == 201 and sent.json()["sent"] is True
    out_of_stock = await client.post(
        "/checkout-links", json={"sku": "TENT-2P", "phone": "+14155550134"}
    )
    assert out_of_stock.status_code == 409
    state = (await client.get("/_state")).json()
    assert len(state["links"]) == 1 and state["returns"] == []
