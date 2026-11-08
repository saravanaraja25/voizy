import pytest
from voizy_core.security.ssrf import Resolver, SsrfError, SsrfPolicy, resolve_safe


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


DEV = SsrfPolicy(allow_loopback=True)


def test_strict_policy_blocks_loopback_http_even_for_literal_localhost() -> None:
    for url in ("http://127.0.0.1:8099/x", "https://127.0.0.1/x", "http://localhost:8099/x"):
        with pytest.raises(SsrfError):
            resolve_safe(url, resolver=fixed("127.0.0.1"))


def test_dev_policy_allows_loopback_http_with_any_port() -> None:
    t = resolve_safe("http://localhost:8099/x", resolver=fixed("127.0.0.1"), policy=DEV)
    assert (t.ip, t.port) == ("127.0.0.1", 8099)
    t = resolve_safe("http://[::1]:9000/x", policy=DEV)
    assert (t.ip, t.port) == ("::1", 9000)


@pytest.mark.parametrize(
    "ip", ["10.0.0.5", "192.168.1.1", "169.254.169.254", "100.64.0.1", "::ffff:10.0.0.1"]
)
def test_dev_policy_still_blocks_private_and_metadata_ranges(ip: str) -> None:
    with pytest.raises(SsrfError, match="not allowed"):
        resolve_safe("https://t.example/x", resolver=fixed(ip), policy=DEV)
    with pytest.raises(SsrfError):
        resolve_safe("http://t.example:8099/x", resolver=fixed(ip), policy=DEV)


def test_dev_policy_rejects_mixed_loopback_and_private_answers() -> None:
    with pytest.raises(SsrfError):
        resolve_safe("http://t.example:8099/", resolver=fixed("127.0.0.1", "10.0.0.1"), policy=DEV)


def test_dev_policy_does_not_allow_plain_http_to_public_hosts() -> None:
    with pytest.raises(SsrfError, match="plain http"):
        resolve_safe("http://t.example:80/x", resolver=fixed("93.184.216.34"), policy=DEV)


def test_dev_policy_public_https_still_works_and_bad_port_is_an_error() -> None:
    t = resolve_safe("https://t.example/x", resolver=fixed("93.184.216.34"), policy=DEV)
    assert t.ip == "93.184.216.34"
    with pytest.raises(SsrfError, match="invalid port"):
        resolve_safe("https://t.example:99999/x", resolver=fixed("93.184.216.34"))
