"""Connecting phone numbers: Twilio Elastic SIP trunk <-> LiveKit SIP trunks and dispatch rules.

Inbound:  PSTN -> Twilio number -> Twilio trunk origination URI -> LiveKit SIP inbound trunk ->
          dispatch rule -> a new room with the voice agent dispatched (signed metadata).
Outbound: LiveKit outbound trunk -> Twilio termination domain (credential-authenticated) -> PSTN.

Everything here is called only from authenticated, permission-checked routes. Provider calls are
behind two small protocols so tests can substitute fakes and a mock Twilio.
"""

from __future__ import annotations

import secrets
import urllib.parse
import uuid
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from google.protobuf.duration_pb2 import Duration
from livekit import api
from voizy_core.domain.dispatch import AGENT_WORKER_NAME, DispatchTarget, encode_dispatch

from voizy_api.livekit import LiveKitSettings

# Twilio's published signaling gateways (https://www.twilio.com/docs/sip-trunking/ip-addresses).
# Only these may open calls on the inbound trunk. Override with VOIZY_SIP_ALLOWED_ADDRESSES.
TWILIO_SIGNALING_CIDRS = (
    "54.172.60.0/30",
    "54.244.51.0/30",
    "54.171.127.192/30",
    "35.156.191.128/30",
    "54.65.63.192/30",
    "54.169.127.128/30",
    "54.252.254.64/30",
    "177.71.206.192/30",
)
TWILIO_API = "https://api.twilio.com/2010-04-01"
TWILIO_TRUNKING = "https://trunking.twilio.com/v1"
LIVEKIT_SIP_AGENT_ROOM_PREFIX = "call-"
RING_TIMEOUT_S = 45
MAX_CALL_S = 7200  # provider-side backstop; the agent enforces its own, shorter limit


class TelephonyError(Exception):
    """Something the operator can act on; the message is shown to them."""


@dataclass(frozen=True)
class TwilioCreds:
    account_sid: str
    auth_token: str = field(repr=False)


def sip_host(livekit_url: str, override: str | None = None) -> str:
    """LiveKit Cloud serves SIP at <project>.sip.livekit.cloud, next to <project>.livekit.cloud."""
    if override:
        return override
    host = urllib.parse.urlparse(livekit_url).hostname or ""
    if host.endswith(".livekit.cloud"):
        return host.removesuffix(".livekit.cloud") + ".sip.livekit.cloud"
    raise TelephonyError(
        "Cannot work out your LiveKit SIP address from the project URL. "
        "Set VOIZY_LIVEKIT_SIP_HOST on the server."
    )


class Twilio(Protocol):
    async def find_number(self, e164: str) -> str: ...
    async def create_trunk(self, friendly_name: str, domain_name: str) -> str: ...
    async def add_origination(self, trunk_sid: str, sip_url: str) -> None: ...
    async def create_credential_list(self, friendly_name: str) -> str: ...
    async def attach_credential_list(self, trunk_sid: str, list_sid: str) -> None: ...
    async def add_credential(self, list_sid: str, username: str, password: str) -> str: ...
    async def delete_credential(self, list_sid: str, credential_sid: str) -> None: ...
    async def attach_number(self, trunk_sid: str, number_sid: str) -> None: ...
    async def detach_number(self, trunk_sid: str, number_sid: str) -> None: ...


class TwilioApi:
    """Twilio REST calls. Docs: twilio.com/docs/sip-trunking/api and /docs/usage/api."""

    def __init__(
        self, creds: TwilioCreds, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._sid = creds.account_sid
        self._client = httpx.AsyncClient(
            auth=(creds.account_sid, creds.auth_token),
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            transport=transport,
        )

    async def _call(
        self, method: str, url: str, data: dict[str, str] | None = None
    ) -> dict[str, object]:
        try:
            r = await self._client.request(method, url, data=data)
        except httpx.HTTPError as exc:
            raise TelephonyError("Could not reach Twilio. Try again in a moment.") from exc
        if r.status_code == 401:
            raise TelephonyError("Twilio rejected the account SID or auth token.")
        if r.status_code >= 400:
            try:
                detail = str(r.json().get("message", ""))[:200]
            except ValueError:
                detail = ""
            raise TelephonyError(f"Twilio refused the request ({r.status_code}). {detail}".strip())
        if r.status_code == 204 or not r.content:
            return {}
        body = r.json()
        return body if isinstance(body, dict) else {}

    async def find_number(self, e164: str) -> str:
        url = f"{TWILIO_API}/Accounts/{self._sid}/IncomingPhoneNumbers.json?" + (
            urllib.parse.urlencode({"PhoneNumber": e164})
        )
        found = (await self._call("GET", url)).get("incoming_phone_numbers")
        if not isinstance(found, list) or not found:
            raise TelephonyError(f"{e164} is not a number in this Twilio account.")
        return str(found[0]["sid"])

    async def create_trunk(self, friendly_name: str, domain_name: str) -> str:
        body = await self._call(
            "POST",
            f"{TWILIO_TRUNKING}/Trunks",
            {"FriendlyName": friendly_name, "DomainName": domain_name},
        )
        return str(body["sid"])

    async def add_origination(self, trunk_sid: str, sip_url: str) -> None:
        await self._call(
            "POST",
            f"{TWILIO_TRUNKING}/Trunks/{trunk_sid}/OriginationUrls",
            {
                "FriendlyName": "LiveKit SIP",
                "SipUrl": sip_url,
                "Weight": "1",
                "Priority": "1",
                "Enabled": "true",
            },
        )

    async def create_credential_list(self, friendly_name: str) -> str:
        body = await self._call(
            "POST",
            f"{TWILIO_API}/Accounts/{self._sid}/SIP/CredentialLists.json",
            {"FriendlyName": friendly_name},
        )
        return str(body["sid"])

    async def attach_credential_list(self, trunk_sid: str, list_sid: str) -> None:
        await self._call(
            "POST",
            f"{TWILIO_TRUNKING}/Trunks/{trunk_sid}/CredentialLists",
            {"CredentialListSid": list_sid},
        )

    async def add_credential(self, list_sid: str, username: str, password: str) -> str:
        body = await self._call(
            "POST",
            f"{TWILIO_API}/Accounts/{self._sid}/SIP/CredentialLists/{list_sid}/Credentials.json",
            {"Username": username, "Password": password},
        )
        return str(body["sid"])

    async def delete_credential(self, list_sid: str, credential_sid: str) -> None:
        await self._call(
            "DELETE",
            f"{TWILIO_API}/Accounts/{self._sid}/SIP/CredentialLists/{list_sid}"
            f"/Credentials/{credential_sid}.json",
        )

    async def attach_number(self, trunk_sid: str, number_sid: str) -> None:
        await self._call(
            "POST",
            f"{TWILIO_TRUNKING}/Trunks/{trunk_sid}/PhoneNumbers",
            {"PhoneNumberSid": number_sid},
        )

    async def detach_number(self, trunk_sid: str, number_sid: str) -> None:
        await self._call(
            "DELETE", f"{TWILIO_TRUNKING}/Trunks/{trunk_sid}/PhoneNumbers/{number_sid}"
        )

    async def aclose(self) -> None:
        await self._client.aclose()


# --- LiveKit SIP ---------------------------------------------------------------------------------


def inbound_trunk_request(e164: str, allowed: tuple[str, ...]) -> api.CreateSIPInboundTrunkRequest:
    return api.CreateSIPInboundTrunkRequest(
        trunk=api.SIPInboundTrunkInfo(
            name=f"voizy {e164}", numbers=[e164], allowed_addresses=list(allowed)
        )
    )


def dispatch_rule_request(
    trunk_id: str, target: DispatchTarget
) -> api.CreateSIPDispatchRuleRequest:
    """Each caller gets a fresh room; the agent is dispatched with server-signed metadata."""
    return api.CreateSIPDispatchRuleRequest(
        rule=api.SIPDispatchRule(
            dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                room_prefix=LIVEKIT_SIP_AGENT_ROOM_PREFIX
            )
        ),
        trunk_ids=[trunk_id],
        name=f"voizy {target.agent_id}",
        room_config=api.RoomConfiguration(
            agents=[
                api.RoomAgentDispatch(
                    agent_name=AGENT_WORKER_NAME,
                    metadata=encode_dispatch(
                        DispatchTarget(target.workspace_id, target.agent_id, None, "inbound")
                    ),
                )
            ],
            empty_timeout=30,
            max_participants=2,
        ),
    )


def outbound_trunk_request(
    e164: str, address: str, username: str, password: str
) -> api.CreateSIPOutboundTrunkRequest:
    return api.CreateSIPOutboundTrunkRequest(
        trunk=api.SIPOutboundTrunkInfo(
            name=f"voizy {e164}",
            address=address,
            transport=api.SIPTransport.SIP_TRANSPORT_TCP,
            numbers=[e164],
            auth_username=username,
            auth_password=password,
        )
    )


class Sip(Protocol):
    async def create_inbound(
        self, e164: str, target: DispatchTarget | None, allowed: tuple[str, ...]
    ) -> tuple[str, str]:
        """Returns (trunk id, dispatch rule id)."""
        ...

    async def create_outbound(self, e164: str, address: str, user: str, password: str) -> str: ...
    async def replace_rule(
        self, trunk_id: str, old_rule_id: str, target: DispatchTarget
    ) -> str: ...
    async def remove_rule(self, rule_id: str) -> None: ...
    async def delete_inbound(self, trunk_id: str, rule_id: str) -> None: ...
    async def delete_outbound(self, trunk_id: str) -> None: ...
    async def dial(self, trunk_id: str, to: str, target: DispatchTarget) -> str:
        """Start an outbound call that the agent will handle. Returns the room name."""
        ...


class LiveKitSip:
    """LiveKit SIP API. Docs: docs.livekit.io/reference/telephony/sip-api/."""

    def __init__(self, settings: LiveKitSettings) -> None:
        self._s = settings

    def _lk(self) -> api.LiveKitAPI:
        return api.LiveKitAPI(self._s.url, self._s.api_key, self._s.api_secret)

    async def create_inbound(
        self, e164: str, target: DispatchTarget | None, allowed: tuple[str, ...]
    ) -> tuple[str, str]:
        async with self._lk() as lk:
            trunk = await lk.sip.create_sip_inbound_trunk(inbound_trunk_request(e164, allowed))
            if target is None:
                return trunk.sip_trunk_id, ""
            rule = await lk.sip.create_sip_dispatch_rule(
                dispatch_rule_request(trunk.sip_trunk_id, target)
            )
            return trunk.sip_trunk_id, rule.sip_dispatch_rule_id

    async def create_outbound(self, e164: str, address: str, user: str, password: str) -> str:
        async with self._lk() as lk:
            t = await lk.sip.create_sip_outbound_trunk(
                outbound_trunk_request(e164, address, user, password)
            )
            return t.sip_trunk_id

    async def replace_rule(self, trunk_id: str, old_rule_id: str, target: DispatchTarget) -> str:
        async with self._lk() as lk:
            if old_rule_id:
                await lk.sip.delete_sip_dispatch_rule(
                    api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=old_rule_id)
                )
            rule = await lk.sip.create_sip_dispatch_rule(dispatch_rule_request(trunk_id, target))
            return rule.sip_dispatch_rule_id

    async def remove_rule(self, rule_id: str) -> None:
        async with self._lk() as lk:
            await lk.sip.delete_sip_dispatch_rule(
                api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=rule_id)
            )

    async def delete_inbound(self, trunk_id: str, rule_id: str) -> None:
        async with self._lk() as lk:
            if rule_id:
                await lk.sip.delete_sip_dispatch_rule(
                    api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=rule_id)
                )
            await lk.sip.delete_sip_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=trunk_id))

    async def delete_outbound(self, trunk_id: str) -> None:
        async with self._lk() as lk:
            await lk.sip.delete_sip_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=trunk_id))

    async def dial(self, trunk_id: str, to: str, target: DispatchTarget) -> str:
        room = f"out-{uuid.uuid4().hex[:12]}"
        async with self._lk() as lk:
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=AGENT_WORKER_NAME,
                    room=room,
                    metadata=encode_dispatch(
                        DispatchTarget(target.workspace_id, target.agent_id, None, "outbound")
                    ),
                )
            )
            await lk.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    sip_trunk_id=trunk_id,
                    sip_call_to=to,
                    room_name=room,
                    participant_identity=f"phone-{uuid.uuid4().hex[:8]}",
                    wait_until_answered=False,
                    ringing_timeout=Duration(seconds=RING_TIMEOUT_S),
                    max_call_duration=Duration(seconds=MAX_CALL_S),
                )
            )
        return room


@dataclass
class Telephony:
    twilio: Twilio
    sip: Sip
    sip_host: str
    allowed_addresses: tuple[str, ...] = TWILIO_SIGNALING_CIDRS


def new_sip_credentials() -> tuple[str, str]:
    return f"voizy-{secrets.token_hex(4)}", secrets.token_urlsafe(24)
