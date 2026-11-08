"""Execute a configured HTTP tool safely.

Every request: SSRF-validated destination, connection pinned to the validated IP (so a second DNS
answer cannot redirect it), no redirects, hard timeout, capped response size, and error text that
never reveals URLs, addresses or exception internals to the model.
"""

from __future__ import annotations

import asyncio
import base64
import socket
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from voizy_core.domain.agent_config import HttpAuth, HttpTool
from voizy_core.security.hosts import host_allowed
from voizy_core.security.ssrf import (
    STRICT,
    Resolver,
    SafeTarget,
    SsrfError,
    SsrfPolicy,
    resolve_safe,
)
from voizy_core.services.secrets_store import ResolvedSecret

# Looks up a tool credential by name. Returns None when it is missing or unreadable.
SecretResolver = Callable[[str], Awaitable["ResolvedSecret | None"]]

TRUNCATED = " …[truncated]"
_SCALARS = (str, int, float, bool)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    text: str  # safe to give to the model
    status: int | None
    duration_s: float


def _auth_headers(auth: HttpAuth, value: str) -> dict[str, str]:
    if auth.kind == "bearer":
        return {"Authorization": f"Bearer {value}"}
    if auth.kind == "basic":
        return {"Authorization": "Basic " + base64.b64encode(value.encode()).decode()}
    return {str(auth.header_name): value}


class _PinnedResolver(AbstractResolver):
    """Always answers with the already-validated address; never consults DNS again."""

    def __init__(self, ip: str) -> None:
        self._ip = ip

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        fam = socket.AF_INET6 if ":" in self._ip else socket.AF_INET
        return [
            {
                "hostname": host,
                "host": self._ip,
                "port": port,
                "family": fam,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            }
        ]

    async def close(self) -> None:
        return None


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - len(TRUNCATED))] + TRUNCATED


class HttpToolExecutor:
    def __init__(
        self,
        policy: SsrfPolicy = STRICT,
        *,
        max_response_bytes: int = 262_144,
        resolver: Resolver | None = None,
    ) -> None:
        self._policy = policy
        self._max_bytes = max_response_bytes
        self._resolver = resolver

    def _resolve(self, url: str) -> SafeTarget:
        if self._resolver is None:
            return resolve_safe(url, policy=self._policy)
        return resolve_safe(url, resolver=self._resolver, policy=self._policy)

    async def execute(
        self,
        tool: HttpTool,
        args: Mapping[str, Any],
        secrets: SecretResolver | None = None,
    ) -> ToolResult:
        started = time.perf_counter()

        def done(ok: bool, text: str, status: int | None = None) -> ToolResult:
            return ToolResult(ok, text, status, time.perf_counter() - started)

        url = str(tool.url)
        try:
            kwargs: dict[str, Any] = {}
            if tool.method in ("GET", "DELETE"):
                if any(not isinstance(v, _SCALARS) for v in args.values()):
                    return done(False, "tool arguments must be simple values")
                kwargs["params"] = {k: str(v) for k, v in args.items()}
            else:
                kwargs["json"] = dict(args)

            target = await asyncio.to_thread(self._resolve, url)
            headers: dict[str, str] = {}
            if tool.auth is not None:
                # Resolve the credential only now, and only send it where it is allowed to go.
                secret = await secrets(tool.auth.secret) if secrets else None
                if secret is None:
                    return done(False, "the tool's credential is not configured")
                if not host_allowed(target.host, secret.allowed_hosts):
                    return done(False, "the tool's credential is not allowed for that address")
                headers = _auth_headers(tool.auth, secret.value)
            connector = aiohttp.TCPConnector(
                resolver=_PinnedResolver(target.ip), use_dns_cache=False
            )
            timeout = aiohttp.ClientTimeout(total=tool.timeout_s)
            async with (
                aiohttp.ClientSession(connector=connector, timeout=timeout) as session,
                session.request(
                    tool.method, url, allow_redirects=False, headers=headers, **kwargs
                ) as resp,
            ):
                body = await resp.content.read(self._max_bytes + 1)
                status = resp.status
        except SsrfError:
            return done(False, "that address is not allowed")
        except TimeoutError:
            return done(False, "the request timed out")
        except aiohttp.ClientError:
            return done(False, "could not connect")

        text = body[: self._max_bytes].decode("utf-8", errors="replace")
        if 300 <= status < 400:
            return done(
                False, "the service responded with a redirect, which is not followed", status
            )
        if status >= 500:
            return done(False, f"the service had an error (status {status})", status)
        if status >= 400:
            detail = _truncate(text.strip(), 200)
            return done(
                False, f"the service rejected the request (status {status}): {detail}", status
            )
        return done(True, _truncate(text, tool.max_result_chars), status)
