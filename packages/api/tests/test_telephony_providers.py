"""The provider calls match the Twilio and LiveKit documentation, checked against a mock Twilio."""

from __future__ import annotations

import base64
import urllib.parse
import uuid

import httpx
import pytest
from livekit import api
from voizy_api.telephony import (
    TWILIO_SIGNALING_CIDRS,
    TelephonyError,
    TwilioApi,
    TwilioCreds,
    dispatch_rule_request,
    inbound_trunk_request,
    outbound_trunk_request,
    sip_host,
)
from voizy_core.domain.dispatch import DispatchTarget, parse_dispatch

SID, TOKEN = "AC" + "1" * 32, "2" * 32


class MockTwilio:
    """Records requests; answers like Twilio's REST API."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = dict(urllib.parse.parse_qsl(request.content.decode()))
        self.requests.append((request.method, str(request.url), form))
        auth = base64.b64decode(request.headers["authorization"].split()[1]).decode()
        assert auth == f"{SID}:{TOKEN}"  # HTTP basic with account sid + auth token
        path = request.url.path
        if path.endswith("IncomingPhoneNumbers.json"):
            hit = request.url.params["PhoneNumber"] == "+14155550134"
            return httpx.Response(
                200, json={"incoming_phone_numbers": [{"sid": "PN1"}] if hit else []}
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        if path == "/v1/Trunks":
            return httpx.Response(201, json={"sid": "TK1"})
        if path.endswith("CredentialLists.json"):
            return httpx.Response(201, json={"sid": "CL1"})
        if path.endswith("Credentials.json"):
            return httpx.Response(201, json={"sid": "CR1"})
        return httpx.Response(201, json={"sid": "XX1"})


def twilio() -> tuple[TwilioApi, MockTwilio]:
    mock = MockTwilio()
    client = TwilioApi(TwilioCreds(SID, TOKEN), transport=httpx.MockTransport(mock.handler))
    return client, mock


async def test_trunk_provisioning_uses_the_documented_endpoints() -> None:
    t, mock = twilio()
    assert await t.find_number("+14155550134") == "PN1"
    assert await t.create_trunk("Voizy", "voizy-abc.pstn.twilio.com") == "TK1"
    await t.add_origination("TK1", "sip:proj.sip.livekit.cloud;transport=tcp")
    assert await t.create_credential_list("Voizy") == "CL1"
    await t.attach_credential_list("TK1", "CL1")
    assert await t.add_credential("CL1", "voizy-1", "pw") == "CR1"
    await t.attach_number("TK1", "PN1")
    await t.detach_number("TK1", "PN1")
    await t.delete_credential("CL1", "CR1")

    seen = [(m, u.split("twilio.com")[1].split("?")[0], f) for m, u, f in mock.requests]
    base = f"/2010-04-01/Accounts/{SID}"
    assert seen == [
        ("GET", f"{base}/IncomingPhoneNumbers.json", {}),
        (
            "POST",
            "/v1/Trunks",
            {"FriendlyName": "Voizy", "DomainName": "voizy-abc.pstn.twilio.com"},
        ),
        (
            "POST",
            "/v1/Trunks/TK1/OriginationUrls",
            {
                "FriendlyName": "LiveKit SIP",
                "SipUrl": "sip:proj.sip.livekit.cloud;transport=tcp",
                "Weight": "1",
                "Priority": "1",
                "Enabled": "true",
            },
        ),
        ("POST", f"{base}/SIP/CredentialLists.json", {"FriendlyName": "Voizy"}),
        ("POST", "/v1/Trunks/TK1/CredentialLists", {"CredentialListSid": "CL1"}),
        (
            "POST",
            f"{base}/SIP/CredentialLists/CL1/Credentials.json",
            {"Username": "voizy-1", "Password": "pw"},
        ),
        ("POST", "/v1/Trunks/TK1/PhoneNumbers", {"PhoneNumberSid": "PN1"}),
        ("DELETE", "/v1/Trunks/TK1/PhoneNumbers/PN1", {}),
        ("DELETE", f"{base}/SIP/CredentialLists/CL1/Credentials/CR1.json", {}),
    ]


async def test_unknown_number_and_bad_credentials_give_clear_errors() -> None:
    t, _ = twilio()
    with pytest.raises(TelephonyError, match="not a number in this Twilio account"):
        await t.find_number("+14155559999")
    bad = TwilioApi(
        TwilioCreds(SID, "x"),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(401, json={"message": "Authenticate"})
        ),
    )
    with pytest.raises(TelephonyError, match="auth token"):
        await bad.find_number("+14155550134")
    boom = TwilioApi(
        TwilioCreds(SID, TOKEN),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"message": "Domain taken"})
        ),
    )
    with pytest.raises(TelephonyError, match="Domain taken"):
        await boom.create_trunk("v", "d")


def test_the_auth_token_is_never_in_a_repr() -> None:
    assert TOKEN not in repr(TwilioCreds(SID, TOKEN))


def test_sip_host_follows_livekit_cloud_naming() -> None:
    assert sip_host("wss://my-proj-abc.livekit.cloud") == "my-proj-abc.sip.livekit.cloud"
    assert sip_host("wss://lk.internal", "sip.internal:5060") == "sip.internal:5060"
    with pytest.raises(TelephonyError, match="VOIZY_LIVEKIT_SIP_HOST"):
        sip_host("wss://lk.internal")


def test_inbound_trunk_only_accepts_twilio_signaling_for_that_number() -> None:
    req = inbound_trunk_request("+14155550134", TWILIO_SIGNALING_CIDRS)
    assert list(req.trunk.numbers) == ["+14155550134"]
    assert list(req.trunk.allowed_addresses) == list(TWILIO_SIGNALING_CIDRS)
    assert len(TWILIO_SIGNALING_CIDRS) == 8


def test_dispatch_rule_gives_each_caller_a_room_and_signed_agent_metadata() -> None:
    target = DispatchTarget(uuid.uuid4(), uuid.uuid4())
    req = dispatch_rule_request("ST_1", target)
    assert list(req.trunk_ids) == ["ST_1"]
    assert req.rule.dispatch_rule_individual.room_prefix == "call-"
    (dispatch,) = req.room_config.agents
    assert dispatch.agent_name == "voizy"
    parsed = parse_dispatch(dispatch.metadata)
    assert parsed == DispatchTarget(target.workspace_id, target.agent_id, None, "inbound")


def test_outbound_trunk_dials_twilio_termination_over_tcp_with_credentials() -> None:
    req = outbound_trunk_request("+14155550134", "voizy-a.pstn.twilio.com", "u", "p")
    t = req.trunk
    assert (t.address, t.auth_username, t.auth_password) == ("voizy-a.pstn.twilio.com", "u", "p")
    assert t.transport == api.SIPTransport.SIP_TRANSPORT_TCP
    assert list(t.numbers) == ["+14155550134"]


def test_outbound_dispatch_names_the_number_in_signed_metadata() -> None:
    from voizy_api.telephony import outbound_dispatch_request

    target = DispatchTarget(uuid.uuid4(), uuid.uuid4())
    req = outbound_dispatch_request("out-1", target, "+14155550199")
    assert req.room == "out-1" and req.agent_name == "voizy"
    parsed = parse_dispatch(req.metadata)
    assert parsed == DispatchTarget(
        target.workspace_id, target.agent_id, None, "outbound", "+14155550199"
    )


async def test_listing_and_deleting_origination_urls_use_the_documented_endpoints() -> None:
    mock = MockTwilio()

    def handler(request: httpx.Request) -> httpx.Response:
        mock.requests.append((request.method, str(request.url), {}))
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "origination_urls": [{"sid": "OU1", "sip_url": "sip:a.example;transport=tcp"}]
                },
            )
        return httpx.Response(204)

    t = TwilioApi(TwilioCreds(SID, TOKEN), transport=httpx.MockTransport(handler))
    assert await t.list_origination_urls("TK1") == [("OU1", "sip:a.example;transport=tcp")]
    await t.delete_origination("TK1", "OU1")
    assert [(m, u.split("twilio.com")[1]) for m, u, _ in mock.requests] == [
        ("GET", "/v1/Trunks/TK1/OriginationUrls"),
        ("DELETE", "/v1/Trunks/TK1/OriginationUrls/OU1"),
    ]


def test_livekit_errors_become_messages_an_operator_can_act_on() -> None:
    from livekit.api.twirp_client import ServerError
    from voizy_api.telephony import livekit_error

    gone = livekit_error(ServerError("not_found", "requested sip trunk does not exist", status=404))
    assert "different LiveKit project" in str(gone) and "connect it again" in str(gone)
    assert "credentials" in str(livekit_error(ServerError("unauthenticated", "x", status=401)))
    assert "limit" in str(livekit_error(ServerError("resource_exhausted", "x", status=429)))
    other = livekit_error(ServerError("internal", "secret detail", status=500))
    assert "internal" in str(other) and "secret detail" not in str(other)
