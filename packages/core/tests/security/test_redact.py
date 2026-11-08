from __future__ import annotations

import pytest
from voizy_core.security.redact import redact


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail me at jo.doe+x@example.co.uk please", "mail me at [email] please"),
        ("my number is 415-555-0134", "my number is [phone]"),
        ("call +1 (415) 555 0134 now", "call [phone] now"),
        ("card 4111 1111 1111 1111 ok", "card [card] ok"),
        ("ssn 123-45-6789", "ssn [id]"),
        ("it is five five five one two three four", "it is [number]"),
        ("I am 42 years old, room 12", "I am 42 years old, room 12"),
        ("", ""),
    ],
)
def test_redact(text: str, expected: str) -> None:
    assert redact(text) == expected
