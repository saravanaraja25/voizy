import pytest
from voizy_core.webhooks import SignatureError, sign, verify

BODY = b'{"event":"call.ended"}'


def test_roundtrip() -> None:
    verify("s3cret", sign("s3cret", BODY, now=1000), BODY, now=1001)


@pytest.mark.parametrize("mutate", ["body", "secret", "timestamp"])
def test_tampering_is_rejected(mutate: str) -> None:
    header = sign("s3cret", BODY, now=1000)
    body, key = BODY, "s3cret"
    if mutate == "body":
        body = BODY + b" "
    elif mutate == "secret":
        key = "other"
    else:
        header = header.replace("t=1000", "t=1001")
    with pytest.raises(SignatureError, match="mismatch"):
        verify(key, header, body, now=1001)


def test_replay_outside_tolerance_rejected() -> None:
    header = sign("s3cret", BODY, now=1000)
    with pytest.raises(SignatureError, match="tolerance"):
        verify("s3cret", header, BODY, now=1000 + 301)
    with pytest.raises(SignatureError, match="tolerance"):
        verify("s3cret", header, BODY, now=1000 - 301)


def test_secret_rotation_accepts_either_signature() -> None:
    header = sign(["new", "old"], BODY, now=1000)
    verify("old", header, BODY, now=1000)
    verify("new", header, BODY, now=1000)


@pytest.mark.parametrize("header", ["", "garbage", "t=abc,v1=00", "t=1000", "v1=00", "t=1000,v1="])
def test_malformed_headers_rejected(header: str) -> None:
    with pytest.raises(SignatureError):
        verify("s3cret", header, BODY, now=1000)
