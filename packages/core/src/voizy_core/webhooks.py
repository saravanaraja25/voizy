"""Outbound webhook signatures: HMAC-SHA256 over '<timestamp>.<body>' (Stripe-style).

Header: ``Voizy-Signature: t=<unix>,v1=<hex>[,v1=<hex>]``. Several v1 values allow secret rotation.
The timestamp is signed so a captured request cannot be replayed outside the tolerance window.
"""

from __future__ import annotations

import hashlib
import hmac
import time

DEFAULT_TOLERANCE_S = 300


class SignatureError(Exception):
    pass


def _mac(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def sign(secrets: str | list[str], body: bytes, *, now: float | None = None) -> str:
    ts = int(time.time() if now is None else now)
    items = [secrets] if isinstance(secrets, str) else secrets
    return f"t={ts}," + ",".join(f"v1={_mac(s, ts, body)}" for s in items)


def verify(
    secret: str,
    header: str,
    body: bytes,
    *,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
    now: float | None = None,
) -> None:
    timestamp: int | None = None
    candidates: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                raise SignatureError("malformed signature header") from None
        elif key == "v1":
            candidates.append(value)
    if timestamp is None or not candidates:
        raise SignatureError("malformed signature header")
    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance_s:
        raise SignatureError("timestamp outside tolerance")
    expected = _mac(secret, timestamp, body)
    if not any(hmac.compare_digest(expected, c) for c in candidates):
        raise SignatureError("signature mismatch")
