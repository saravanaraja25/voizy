# Telephony

Voizy answers and places phone calls through **Twilio Elastic SIP Trunking** into **LiveKit SIP**,
using your own Twilio account and your own LiveKit project. Nothing is routed through a Voizy
service.

```
Caller -> Twilio number -> Twilio SIP trunk --origination--> LiveKit SIP -> room -> voice agent
Agent  -> LiveKit SIP outbound trunk --termination (credentials)--> Twilio -> callee
```

## Connect a number

1. **Settings**: connect LiveKit and Twilio (account SID and auth token). Use *Test connection*.
2. **Phone** -> *Connect a number*: enter a number that already exists in your Twilio account and
   (optionally) a published agent to answer it.

Voizy then, through the Twilio and LiveKit APIs:

- finds the number in your account (a number you do not own is refused);
- creates one Twilio trunk per workspace (first time only) with an origination URI of
  `sip:<project>.sip.livekit.cloud;transport=tcp`, a termination domain and a credential list;
- attaches the number to the trunk. **This replaces any voice webhook configured on that number.**
- creates a LiveKit inbound trunk for the number and a dispatch rule that gives every caller a fresh
  room and dispatches the agent with server-signed metadata (workspace, agent, source);
- creates a LiveKit outbound trunk pointing at the Twilio termination domain, authenticated with a
  random per-number credential that is stored only inside Twilio and LiveKit.

If any step fails, everything created before it is removed. Disconnecting a number removes the same
resources; the number itself stays in your Twilio account.

Inbound calls reach **published** versions only. Changing *Who answers* swaps the dispatch rule;
choosing "No one" removes it so callers are rejected.

## Outbound calls

*Phone* -> *Call* places one call from a connected number. The agent starts speaking when the
callee picks up and gives up after 60 seconds of ringing (the call is recorded as "not answered").
`POST /v1/calls/outbound` needs `calls:place_outbound`, an explicit `consent_confirmed: true`, a
published agent, and is capped per workspace (30 calls per hour) because dialing is a toll-fraud
target. Audit entries keep only the last four digits of the dialed number.

Campaign-level consent, do-not-call lists and quiet hours are not built yet.

## Security

- The LiveKit inbound trunk accepts SIP only from Twilio's published signaling gateways
  ([list](https://www.twilio.com/docs/sip-trunking/ip-addresses)) and only for the connected
  number. Override with `VOIZY_SIP_ALLOWED_ADDRESSES`.
- Twilio's auth token never leaves the server: it is stored encrypted, decrypted only to call
  Twilio, and never logged or returned.
- Caller numbers are not stored with call history.

## What is verified, and what is not

| Part | How it was checked |
|---|---|
| Twilio REST calls (trunk, origination URL, credential list, credentials, number attach/detach) | Against a mock Twilio server asserting every endpoint, form field and basic-auth header, and against Twilio's published API reference |
| LiveKit SIP requests (inbound/outbound trunk, dispatch rule, participant) | Request objects built with the pinned `livekit-api` and asserted field by field; see `packages/api/tests/test_telephony_providers.py` |
| Connect/rollback/disconnect/outbound flows, permissions, caps | Route tests with fake providers |
| Agent handling an inbound-style and outbound-style dispatch | Live LiveKit Cloud room with a browser/SDK participant standing in for the phone leg |
| **A real PSTN call through Twilio** | **Not done.** Needs a Twilio number and balance; run it before relying on this |

## Troubleshooting

- *"Cannot work out your LiveKit SIP address"*: self-hosted LiveKit; set `VOIZY_LIVEKIT_SIP_HOST`.
- *Twilio refused the request*: the message includes Twilio's reason (for example a taken domain).
- *Calls ring and drop*: confirm the number is attached to the trunk in the Twilio console and the
  trunk's origination URI matches your LiveKit SIP address.
