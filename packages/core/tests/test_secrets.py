import pytest
from voizy_core.secrets import SecretBox, SecretError


def box(key_id: str = "k1") -> SecretBox:
    return SecretBox.from_env_value(f"{key_id}:{SecretBox.generate_key()}")


def test_roundtrip_and_ciphertext_hides_plaintext() -> None:
    b = box()
    token = b.encrypt("sk-live-123", workspace_id="w1", name="twilio")
    assert "sk-live-123" not in token
    assert b.decrypt(token, workspace_id="w1", name="twilio") == "sk-live-123"


def test_nonce_is_random() -> None:
    b = box()
    a = b.encrypt("x", workspace_id="w1", name="n")
    c = b.encrypt("x", workspace_id="w1", name="n")
    assert a != c


def test_ciphertext_bound_to_workspace_and_name() -> None:
    b = box()
    token = b.encrypt("secret", workspace_id="w1", name="twilio")
    with pytest.raises(SecretError):
        b.decrypt(token, workspace_id="w2", name="twilio")
    with pytest.raises(SecretError):
        b.decrypt(token, workspace_id="w1", name="openai")


def test_tampering_detected() -> None:
    b = box()
    token = b.encrypt("secret", workspace_id="w1", name="n")
    head, _, blob = token.rpartition(":")
    flipped = blob[:-2] + ("AA" if blob[-2:] != "AA" else "BB")
    with pytest.raises(SecretError):
        b.decrypt(f"{head}:{flipped}", workspace_id="w1", name="n")


def test_rotation_old_key_still_decrypts_and_is_flagged() -> None:
    k_old, k_new = SecretBox.generate_key(), SecretBox.generate_key()
    old = SecretBox.from_env_value(f"k1:{k_old}")
    token = old.encrypt("v", workspace_id="w", name="n")
    rotated = SecretBox.from_env_value(f"k2:{k_new},k1:{k_old}")
    assert rotated.decrypt(token, workspace_id="w", name="n") == "v"
    assert rotated.needs_rotation(token)
    assert not rotated.needs_rotation(rotated.encrypt("v", workspace_id="w", name="n"))


def test_wrong_key_and_garbage_fail_without_leaking() -> None:
    token = box().encrypt("PLAINTEXT-9f3a", workspace_id="w", name="n")
    with pytest.raises(SecretError) as e:
        box().decrypt(token, workspace_id="w", name="n")
    assert "PLAINTEXT-9f3a" not in str(e.value)
    with pytest.raises(SecretError):
        box().decrypt("garbage", workspace_id="w", name="n")


def test_short_key_rejected_and_repr_redacts() -> None:
    with pytest.raises(SecretError):
        SecretBox({"k1": b"short"}, "k1")
    b = box()
    assert "redacted" in repr(b) and b.active_key_id in repr(b)
