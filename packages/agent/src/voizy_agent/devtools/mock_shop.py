"""A tiny in-memory online-store backend for trying an e-commerce agent locally.

    uv run python -m voizy_agent.devtools.mock_shop --port 8098 --delay-ms 400

Orders are looked up by order number AND postcode, and a mismatch looks the same as a missing order,
so the endpoint never confirms that an order number exists. Local development only.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import date, timedelta
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

RETURN_WINDOW_DAYS = 30
TODAY = date.today


def _orders() -> dict[str, dict[str, object]]:
    t = TODAY()
    return {
        "1001": {
            "zip": "94107",
            "status": "shipped",
            "items": [("TRAIL-JKT-M", "Trail Jacket, medium")],
            "ordered": t - timedelta(days=3),
            "eta": t + timedelta(days=2),
            "tracking": "1Z999AA10123456784",
        },
        "1002": {
            "zip": "10001",
            "status": "delivered",
            "items": [("RUN-SHOE-42", "Runner shoes, size 42")],
            "ordered": t - timedelta(days=9),
            "delivered": t - timedelta(days=5),
        },
        "1003": {
            "zip": "60601",
            "status": "processing",
            "items": [("PACK-30L", "30 litre daypack")],
            "ordered": t - timedelta(days=1),
            "eta": t + timedelta(days=6),
        },
        "1004": {
            "zip": "73301",
            "status": "delivered",
            "items": [("TENT-2P", "Two-person tent")],
            "ordered": t - timedelta(days=50),
            "delivered": t - timedelta(days=45),
        },
    }


PRODUCTS = [
    {
        "sku": "TRAIL-JKT-M",
        "name": "Trail Jacket",
        "category": "jackets",
        "price": 129.0,
        "sizes": ["S", "M", "L"],
        "in_stock": True,
    },
    {
        "sku": "RUN-SHOE-42",
        "name": "Runner Shoes",
        "category": "shoes",
        "price": 89.0,
        "sizes": ["40", "41", "42", "43"],
        "in_stock": True,
    },
    {
        "sku": "PACK-30L",
        "name": "30 Litre Daypack",
        "category": "bags",
        "price": 59.0,
        "sizes": ["one size"],
        "in_stock": True,
    },
    {
        "sku": "TENT-2P",
        "name": "Two-Person Tent",
        "category": "camping",
        "price": 249.0,
        "sizes": ["one size"],
        "in_stock": False,
    },
    {
        "sku": "FLEECE-L",
        "name": "Fleece Pullover",
        "category": "jackets",
        "price": 69.0,
        "sizes": ["M", "L", "XL"],
        "in_stock": True,
    },
]


class ReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=20)
    zip: str = Field(min_length=3, max_length=10)
    sku: str = Field(min_length=1, max_length=40)
    reason: str = Field(default="", max_length=200)


class CheckoutLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=40)
    size: str = Field(default="", max_length=20)
    phone: str = Field(min_length=5, max_length=30)


def create_mock_app(delay_ms: int = 0) -> FastAPI:
    app = FastAPI(title="Mock shop", docs_url=None, redoc_url=None)
    orders = _orders()
    app.state.returns = []
    app.state.links = []

    async def pause() -> None:
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)

    def find_order(order_id: str, zip_code: str) -> dict[str, object]:
        order = orders.get(order_id.strip().lstrip("#"))
        if order is None or order["zip"] != zip_code.strip():
            raise HTTPException(404, "no order matches that order number and postcode")
        return order

    @app.get("/products")
    async def products(query: Annotated[str, Query(max_length=60)] = "") -> dict[str, object]:
        await pause()
        q = query.strip().lower()
        hits = [p for p in PRODUCTS if not q or q in f"{p['name']} {p['category']}".lower()]
        return {"count": len(hits), "products": hits[:5]}

    @app.get("/orders/status")
    async def order_status(order_id: str, zip: str) -> dict[str, object]:  # noqa: A002
        await pause()
        o = find_order(order_id, zip)
        out: dict[str, object] = {
            "order_id": order_id.strip().lstrip("#"),
            "status": o["status"],
            "items": [{"sku": sku, "name": name} for sku, name in o["items"]],  # type: ignore[attr-defined]
            "ordered_on": str(o["ordered"]),
        }
        for key in ("eta", "delivered", "tracking"):
            if key in o:
                out[
                    "estimated_delivery"
                    if key == "eta"
                    else ("delivered_on" if key == "delivered" else "tracking_number")
                ] = str(o[key])
        return out

    @app.post("/returns", status_code=201)
    async def start_return(req: ReturnRequest) -> dict[str, object]:
        await pause()
        o = find_order(req.order_id, req.zip)
        if o["status"] != "delivered":
            raise HTTPException(409, "only delivered orders can be returned")
        if (TODAY() - o["delivered"]).days > RETURN_WINDOW_DAYS:  # type: ignore[operator]
            raise HTTPException(409, f"the {RETURN_WINDOW_DAYS}-day return window has passed")
        if req.sku not in {sku for sku, _ in o["items"]}:  # type: ignore[attr-defined]
            raise HTTPException(422, "that item is not on this order")
        rma = "RMA-" + uuid.uuid4().hex[:6].upper()
        app.state.returns.append({"rma": rma, "order_id": req.order_id, "sku": req.sku})
        return {
            "return_id": rma,
            "label_emailed": True,
            "refund": "within 5 business days of receiving the item",
        }

    @app.post("/checkout-links", status_code=201)
    async def checkout_link(req: CheckoutLinkRequest) -> dict[str, object]:
        await pause()
        product = next((p for p in PRODUCTS if p["sku"] == req.sku), None)
        if product is None:
            raise HTTPException(404, "unknown product")
        if not product["in_stock"]:
            raise HTTPException(409, "that product is out of stock")
        app.state.links.append({"sku": req.sku, "size": req.size})
        return {
            "sent": True,
            "via": "text message",
            "item": product["name"],
            "price": product["price"],
        }

    @app.get("/_state")
    async def state() -> dict[str, object]:
        """What the agent actually did, for tests and demos."""
        return {"returns": app.state.returns, "links": app.state.links}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the mock shop API (loopback only).")
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--delay-ms", type=int, default=400)
    args = parser.parse_args()
    uvicorn.run(
        create_mock_app(args.delay_ms), host="127.0.0.1", port=args.port, log_level="warning"
    )


if __name__ == "__main__":
    main()
