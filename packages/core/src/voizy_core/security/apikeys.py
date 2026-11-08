"""API keys: 256-bit random tokens, stored only as SHA-256, shown once at creation."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass

TOKEN_RE = re.compile(r"^vz_[A-Za-z0-9_-]{43}$")  # 32 random bytes, urlsafe base64, no padding


@dataclass(frozen=True)
class NewApiKey:
    token: str  # show to the user once; never persisted
    prefix: str  # safe to display, helps users identify a key
    key_hash: bytes


def generate_api_key() -> NewApiKey:
    token = "vz_" + secrets.token_urlsafe(32)
    return NewApiKey(token=token, prefix=token[:11], key_hash=hash_token(token))


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
