"""Host patterns for pinning a credential to the destinations it may be sent to."""

from __future__ import annotations

import re

# 'api.example.com' or '*.example.com' (subdomains only, never the bare apex).
_PATTERN = re.compile(
    r"^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)
_LOOPBACK = frozenset({"localhost", "127.0.0.1"})


def valid_host_pattern(pattern: str) -> bool:
    p = pattern.strip().lower()
    if p in _LOOPBACK:
        return True
    # IP literals are not hostnames: a credential binds to a name; the SSRF guard owns addresses.
    if set(p.replace("*.", "")) <= set("0123456789."):
        return False
    return bool(_PATTERN.match(p))


def host_allowed(host: str, patterns: list[str] | tuple[str, ...]) -> bool:
    host = host.strip().lower().rstrip(".")
    for raw in patterns:
        pattern = raw.strip().lower()
        if pattern.startswith("*."):
            suffix = pattern[1:]  # '.example.com'
            if host.endswith(suffix) and len(host) > len(suffix):
                return True
        elif host == pattern:
            return True
    return False
