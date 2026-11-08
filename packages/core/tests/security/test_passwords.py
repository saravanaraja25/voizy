import pytest
from voizy_core.security.passwords import (
    MAX_LENGTH,
    PasswordPolicyError,
    check_policy,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_hash_verify_roundtrip_and_uses_argon2id() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple")
    assert not verify_password(h, "correct horse battery stapl")
    assert not needs_rehash(h)


def test_hashes_are_salted() -> None:
    assert hash_password("same password here") != hash_password("same password here")


def test_unknown_account_never_verifies_but_still_does_the_work() -> None:
    assert verify_password(None, "anything at all") is False
    assert verify_password("not-a-hash", "anything at all") is False


@pytest.mark.parametrize(
    ("password", "email", "message"),
    [
        ("short", "", "at least"),
        ("x" * (MAX_LENGTH + 1), "", "at most"),
        ("password123", "", "common"),
        ("PASSWORD123", "", "common"),
        ("aaaaaaaaaaaa", "", "common"),
        ("sam.taylor@example.com", "sam.taylor@example.com", "email"),
        ("my-samtaylor-secret", "samtaylor@example.com", "email"),
    ],
)
def test_policy_rejections(password: str, email: str, message: str) -> None:
    with pytest.raises(PasswordPolicyError, match=message):
        check_policy(password, email=email)


def test_policy_accepts_a_long_passphrase_without_composition_rules() -> None:
    check_policy("correct horse battery staple", email="sam@example.com")
