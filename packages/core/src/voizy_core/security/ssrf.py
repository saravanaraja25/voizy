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


def _check_ip(raw: str) -> str:
    addr = ipaddress.ip_address(raw.split("%", 1)[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if not addr.is_global or addr.is_multicast or any(addr in net for net in _EXTRA_BLOCKED):
        raise SsrfError(f"destination address {addr} is not allowed")
    return str(addr)


def resolve_safe(
    url: str,
    *,
    resolver: Resolver = _system_resolver,
    allowed_ports: frozenset[int] = _ALLOWED_PORTS,
) -> SafeTarget:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise SsrfError("only https URLs are allowed")
    if parts.username or parts.password:
        raise SsrfError("credentials in URLs are not allowed")
    host = parts.hostname
    if not host:
        raise SsrfError("URL has no host")
    port = parts.port or 443
    if port not in allowed_ports:
        raise SsrfError(f"port {port} is not allowed")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return SafeTarget(url, host, _check_ip(str(literal)), port)

    try:
        addresses = resolver(host, port)
    except OSError as exc:
        raise SsrfError(f"could not resolve {host}") from exc
    if not addresses:
        raise SsrfError(f"could not resolve {host}")
    # Every resolved address must be safe, otherwise a mixed answer could slip through.
    validated = [_check_ip(a) for a in addresses]
    return SafeTarget(url, host, validated[0], port)
