"""Password hashing (argon2id) and policy.

Hashing is deliberately slow and memory-hard, so call it off the event loop. Policy follows NIST
SP 800-63B: length over composition rules, and no known-bad passwords.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 10
MAX_LENGTH = 128  # bounds hashing work and request size

# time_cost=3, 64 MiB, 4 lanes: above the OWASP minimum for argon2id.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

# A real hash of a throwaway password, so logins for unknown accounts cost the same as real ones.
_DUMMY_HASH = _hasher.hash("voizy-timing-equaliser-not-a-real-password")

_COMMON = frozenset(
    """password password1 password12 password123 passw0rd 1234567890 12345678910 qwertyuiop
    qwerty123 qwertyuiop123 letmein123 welcome123 admin12345 administrator iloveyou123
    changeme123 123456789012 abcdefghij abc1234567 1q2w3e4r5t 0123456789 9876543210 trustno1234
    monkey12345 dragon12345 football123 baseball123 superman123 sunshine123 princess123
    000000000000 111111111111 aaaaaaaaaaaa voizy12345""".split()
)


class PasswordPolicyError(ValueError):
    """The password is unacceptable; the message is safe to show to the user."""


def check_policy(password: str, *, email: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"Use at most {MAX_LENGTH} characters.")
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) < 4:
        raise PasswordPolicyError("That password is too common or too repetitive.")
    local = email.split("@", 1)[0].lower()
    if email and (lowered == email.lower() or (len(local) >= 4 and local in lowered)):
        raise PasswordPolicyError("The password must not contain your email address.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Constant-effort check: a missing account is verified against a dummy hash."""
    try:
        _hasher.verify(stored_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return stored_hash is not None


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)
