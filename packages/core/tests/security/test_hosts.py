import pytest
from voizy_core.security.hosts import host_allowed, valid_host_pattern


@pytest.mark.parametrize(
    "pattern",
    [
        "api.example.com",
        "*.example.com",
        "a.b.example.co.uk",
        "localhost",
        "127.0.0.1",
        "API.Example.COM",
    ],
)
def test_valid_patterns(pattern: str) -> None:
    assert valid_host_pattern(pattern)


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        "example",
        "*",
        "*.",
        "http://example.com",
        "example.com/path",
        "a b.com",
        "exa_mple.com",
        "-bad.example.com",
        "*.*.example.com",
        "example.com:443",
        "10.0.0.1",
        "203.0.113.5",
        "*.0.0.1",
        "169.254.169.254",
    ],
)
def test_invalid_patterns_including_ip_literals(pattern: str) -> None:
    assert not valid_host_pattern(pattern)


def test_exact_match_is_case_insensitive_and_tolerates_a_trailing_dot() -> None:
    assert host_allowed("API.example.com.", ["api.example.com"])
    assert not host_allowed("evil-api.example.com", ["api.example.com"])
    assert not host_allowed("api.example.com.evil.com", ["api.example.com"])


def test_wildcards_match_subdomains_only() -> None:
    patterns = ["*.example.com"]
    assert host_allowed("api.example.com", patterns)
    assert host_allowed("a.b.example.com", patterns)
    assert not host_allowed("example.com", patterns)  # the bare apex is not a subdomain
    assert not host_allowed("notexample.com", patterns)
    assert not host_allowed("example.com.evil.com", patterns)


def test_no_patterns_allows_nothing() -> None:
    assert not host_allowed("api.example.com", [])
