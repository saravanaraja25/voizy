import pytest
from voizy_core.security.ssrf import Resolver, SsrfError, resolve_safe


def fixed(*addrs: str) -> Resolver:
    return lambda host, port: list(addrs)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.9",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
    ],
)
def test_blocks_internal_addresses_from_dns(ip: str) -> None:
    with pytest.raises(SsrfError, match="not allowed"):
        resolve_safe("https://tool.example/x", resolver=fixed(ip))


@pytest.mark.parametrize("host", ["127.0.0.1", "[::1]", "169.254.169.254", "[::ffff:10.0.0.1]"])
def test_blocks_literal_internal_ips(host: str) -> None:
    with pytest.raises(SsrfError):
        resolve_safe(f"https://{host}/x")


def test_mixed_dns_answer_is_rejected() -> None:
    with pytest.raises(SsrfError):
        resolve_safe("https://t.example/", resolver=fixed("93.184.216.34", "10.0.0.1"))


def test_public_address_allowed_and_ip_is_pinned() -> None:
    t = resolve_safe("https://t.example/path?q=1", resolver=fixed("93.184.216.34"))
    assert (t.host, t.ip, t.port) == ("t.example", "93.184.216.34", 443)


@pytest.mark.parametrize(
    "url",
    [
        "http://t.example/",
        "ftp://t.example/",
        "https://user:pw@t.example/",
        "https://t.example:8443/",
        "https:///nohost",
        "file:///etc/passwd",
    ],
)
def test_rejects_bad_scheme_credentials_port_or_host(url: str) -> None:
    with pytest.raises(SsrfError):
        resolve_safe(url, resolver=fixed("93.184.216.34"))


def test_unresolvable_host_rejected() -> None:
    def boom(host: str, port: int) -> list[str]:
        raise OSError("nxdomain")

    with pytest.raises(SsrfError, match="could not resolve"):
        resolve_safe("https://nope.invalid/", resolver=boom)
