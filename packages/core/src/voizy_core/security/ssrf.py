"""SSRF guard for user-configured outbound URLs (HTTP tools, webhooks).

Resolve once, validate every address, then connect to the validated IP so a second DNS lookup
(DNS rebinding) cannot swap in an internal address. Callers must also disable redirects.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

Resolver = Callable[[str, int], list[str]]

_ALLOWED_PORTS = frozenset({443})
# Not flagged by is_private/is_global on every Python version, so listed explicitly.
_EXTRA_BLOCKED = tuple(
    ipaddress.ip_network(n) for n in ("100.64.0.0/10", "192.0.0.0/24", "198.18.0.0/15")
)


@dataclass(frozen=True)
class SsrfPolicy:
    """Strict by default. allow_loopback is for local development only: it additionally permits
    http and any port, but only for destinations that resolve entirely to loopback. Private
    ranges, link-local and cloud metadata addresses stay blocked in every mode."""

    allow_loopback: bool = False


STRICT = SsrfPolicy()


class SsrfError(Exception):
    """The URL targets a destination we refuse to contact."""


@dataclass(frozen=True)
class SafeTarget:
    url: str
    host: str  # original hostname: use for the Host header and TLS SNI
    ip: str  # validated address to connect to
    port: int


def _system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _check_ip(raw: str, policy: SsrfPolicy = STRICT) -> str:
    addr = ipaddress.ip_address(raw.split("%", 1)[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if policy.allow_loopback and addr.is_loopback:
        return str(addr)
    if not addr.is_global or addr.is_multicast or any(addr in net for net in _EXTRA_BLOCKED):
        raise SsrfError(f"destination address {addr} is not allowed")
    return str(addr)


def resolve_safe(
    url: str,
    *,
    resolver: Resolver = _system_resolver,
    allowed_ports: frozenset[int] = _ALLOWED_PORTS,
    policy: SsrfPolicy = STRICT,
) -> SafeTarget:
    parts = urlsplit(url)
    if parts.username or parts.password:
        raise SsrfError("credentials in URLs are not allowed")
    host = parts.hostname
    if not host:
        raise SsrfError("URL has no host")
    if parts.scheme == "https":
        default_port = 443
    elif parts.scheme == "http" and policy.allow_loopback:
        default_port = 80
    else:
        raise SsrfError("only https URLs are allowed")
    try:
        port = parts.port or default_port
    except ValueError:
        raise SsrfError("invalid port") from None
    if not policy.allow_loopback and port not in allowed_ports:
        raise SsrfError(f"port {port} is not allowed")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        ip = _check_ip(str(literal), policy)
        _require_loopback_for_plain_http(parts.scheme, ip, policy)
        return SafeTarget(url, host, ip, port)

    try:
        addresses = resolver(host, port)
    except OSError as exc:
        raise SsrfError(f"could not resolve {host}") from exc
    if not addresses:
        raise SsrfError(f"could not resolve {host}")
    # Every resolved address must be safe, otherwise a mixed answer could slip through.
    validated = [_check_ip(a, policy) for a in addresses]
    for ip in validated:
        _require_loopback_for_plain_http(parts.scheme, ip, policy)
    return SafeTarget(url, host, validated[0], port)


def _require_loopback_for_plain_http(scheme: str, ip: str, policy: SsrfPolicy) -> None:
    if scheme == "http" and not ipaddress.ip_address(ip).is_loopback:
        raise SsrfError("plain http is only allowed to loopback in development")
