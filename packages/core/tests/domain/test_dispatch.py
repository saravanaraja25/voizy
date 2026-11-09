import json
import uuid

import pytest
from voizy_core.domain.dispatch import DispatchTarget, encode_dispatch, parse_dispatch

WS, AG = uuid.uuid4(), uuid.uuid4()


@pytest.mark.parametrize("version", [None, 1, 7])
def test_roundtrip(version: int | None) -> None:
    target = DispatchTarget(WS, AG, version)
    assert parse_dispatch(encode_dispatch(target)) == target


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not json",
        "[]",
        "null",
        "{}",
        '"x"',
        json.dumps({"workspace_id": str(WS)}),
        json.dumps({"workspace_id": str(WS), "agent_id": "nope"}),
        json.dumps({"workspace_id": str(WS), "agent_id": str(AG), "extra": 1}),
        json.dumps({"workspace_id": 5, "agent_id": [1]}),
        json.dumps({"workspace_id": str(WS), "agent_id": str(AG), "version": 0}),
        json.dumps({"workspace_id": str(WS), "agent_id": str(AG), "version": -2}),
        json.dumps({"workspace_id": str(WS), "agent_id": str(AG), "version": "3"}),
        json.dumps({"workspace_id": str(WS), "agent_id": str(AG), "version": True}),
        json.dumps({"workspace_id": str(WS), "agent_id": str(AG), "version": 1.5}),
    ],
)
def test_anything_else_is_rejected(raw: str | None) -> None:
    assert parse_dispatch(raw) is None


def test_source_round_trips_and_defaults_to_test() -> None:
    import uuid

    from voizy_core.domain.dispatch import DispatchTarget, encode_dispatch, parse_dispatch

    ws, ag = uuid.uuid4(), uuid.uuid4()
    for source in ("inbound", "outbound"):
        parsed = parse_dispatch(encode_dispatch(DispatchTarget(ws, ag, None, source)))
        assert parsed is not None and parsed.source == source
    plain = encode_dispatch(DispatchTarget(ws, ag))
    default = parse_dispatch(plain)
    assert "source" not in plain and default is not None and default.source == "test"
    assert parse_dispatch(plain[:-1] + ',"source":"bogus"}') is None


def test_remote_number_must_be_e164() -> None:
    import uuid

    from voizy_core.domain.dispatch import DispatchTarget, encode_dispatch, parse_dispatch

    ws, ag = uuid.uuid4(), uuid.uuid4()
    good = parse_dispatch(encode_dispatch(DispatchTarget(ws, ag, None, "outbound", "+14155550199")))
    assert good is not None and good.remote == "+14155550199"
    base = encode_dispatch(DispatchTarget(ws, ag, None, "outbound"))
    for bad in ('"4155550199"', '"+0123"', '"+1 415 555 0199"', "5", '"+1415555019900000"'):
        assert parse_dispatch(base[:-1] + f',"remote":{bad}}}') is None
