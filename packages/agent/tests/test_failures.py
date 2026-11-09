from __future__ import annotations

from types import SimpleNamespace

import pytest
from voizy_agent.failures import describe_failure


@pytest.mark.parametrize(
    ("error", "reason", "needle"),
    [
        (
            SimpleNamespace(error=SimpleNamespace(status_code=429)),
            "provider error (429)",
            "allowance",
        ),
        (
            SimpleNamespace(error=SimpleNamespace(status_code=401)),
            "provider error (401)",
            "credentials",
        ),
        (SimpleNamespace(status_code=403), "provider error (403)", "credentials"),
        (SimpleNamespace(error=RuntimeError("boom")), "provider error", "worker log"),
        (object(), "provider error", "worker log"),
    ],
)
def test_failures_say_what_to_do(error: object, reason: str, needle: str) -> None:
    f = describe_failure(error)
    assert f.reason == reason and needle in f.message


def test_the_message_never_echoes_provider_error_text() -> None:
    secret = "sk-this-should-never-appear"  # noqa: S105 - a marker string, not a credential
    f = describe_failure(SimpleNamespace(error=RuntimeError(f"bad key {secret}")))
    assert secret not in f.message and secret not in f.reason
