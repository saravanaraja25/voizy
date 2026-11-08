"""Authenticated encryption for stored secrets (provider keys, tool auth).

AES-256-GCM with a random nonce. The workspace and secret name are bound as associated data so a
ciphertext copied to another tenant or field fails to decrypt. Keys are versioned for rotation.
"""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_ID = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
_VERSION = b"v1"


class SecretError(Exception):
    """Encryption or decryption failed. Messages never include key or plaintext material."""


@dataclass(frozen=True)
class SecretBox:
    keys: dict[str, bytes]  # key_id -> 32-byte key
    active_key_id: str

    def __post_init__(self) -> None:
        if self.active_key_id not in self.keys:
            raise SecretError("active key id is not in the keyring")
        for key_id, key in self.keys.items():
            if not _KEY_ID.match(key_id) or len(key) != 32:
                raise SecretError("keyring entries must be 32-byte keys with a simple id")

    @classmethod
    def from_env_value(cls, value: str) -> SecretBox:
        """Parse 'id:base64key[,id2:base64key2]'; the first entry is the active key."""
        keys: dict[str, bytes] = {}
        first: str | None = None
        for entry in value.split(","):
            key_id, _, b64 = entry.strip().partition(":")
            try:
                keys[key_id] = base64.b64decode(b64, validate=True)
            except ValueError as exc:
                raise SecretError("keyring is not valid base64") from exc
            first = first or key_id
        if first is None:
            raise SecretError("keyring is empty")
        return cls(keys, first)

    @staticmethod
    def generate_key() -> str:
        return base64.b64encode(os.urandom(32)).decode()

    @staticmethod
    def _aad(workspace_id: str, name: str) -> bytes:
        return f"{workspace_id}\x00{name}".encode()

    def encrypt(self, plaintext: str, *, workspace_id: str, name: str) -> str:
        nonce = os.urandom(12)
        ct = AESGCM(self.keys[self.active_key_id]).encrypt(
            nonce, plaintext.encode(), self._aad(workspace_id, name)
        )
        blob = base64.urlsafe_b64encode(nonce + ct).decode()
        return f"{_VERSION.decode()}:{self.active_key_id}:{blob}"

    def decrypt(self, token: str, *, workspace_id: str, name: str) -> str:
        try:
            version, key_id, blob = token.split(":", 2)
            raw = base64.urlsafe_b64decode(blob.encode())
            key = self.keys[key_id]
            if version != _VERSION.decode() or len(raw) < 28:
                raise SecretError("malformed secret")
            plain = AESGCM(key).decrypt(raw[:12], raw[12:], self._aad(workspace_id, name))
        except (ValueError, KeyError, InvalidTag) as exc:
            raise SecretError("secret could not be decrypted") from exc
        return plain.decode()

    def needs_rotation(self, token: str) -> bool:
        return token.split(":", 2)[1] != self.active_key_id

    def __repr__(self) -> str:  # never leak key material in logs or tracebacks
        return f"SecretBox(active_key_id={self.active_key_id!r}, keys=<redacted>)"
