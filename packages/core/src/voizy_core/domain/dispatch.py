"""What a voice job is told to run: set server-side when a call is dispatched, parsed strictly."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass

# Name the voice worker registers under; explicit dispatch targets it.
AGENT_WORKER_NAME = "voizy"

_KEYS = {"workspace_id", "agent_id"}
_OPTIONAL = {"version", "source", "remote", "contact"}
_E164 = re.compile(r"^\+[1-9][0-9]{6,14}$")
SOURCES = ("test", "inbound", "outbound")


@dataclass(frozen=True)
class DispatchTarget:
    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    version: int | None = None  # None = the published version; set for test calls on drafts
    source: str = "test"  # where the call came from: test | inbound | outbound
    remote: str | None = None  # outbound only: the number being dialed (E.164), set by the server
    contact: uuid.UUID | None = None  # campaign calls: which contact this call is for


def encode_dispatch(target: DispatchTarget) -> str:
    data: dict[str, object] = {
        "workspace_id": str(target.workspace_id),
        "agent_id": str(target.agent_id),
    }
    if target.version is not None:
        data["version"] = target.version
    if target.source != "test":
        data["source"] = target.source
    if target.remote is not None:
        data["remote"] = target.remote
    if target.contact is not None:
        data["contact"] = str(target.contact)
    return json.dumps(data, separators=(",", ":"))


def parse_dispatch(raw: str | None) -> DispatchTarget | None:
    """Return the target, or None if the metadata is absent or anything but the expected shape."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) - _KEYS - _OPTIONAL or _KEYS - set(data):
            return None
        version = data.get("version")
        if "version" in data and (
            not isinstance(version, int) or isinstance(version, bool) or version < 1
        ):
            return None
        source = data.get("source", "test")
        if source not in SOURCES:
            return None
        remote = data.get("remote")
        if "remote" in data and (not isinstance(remote, str) or not _E164.match(remote)):
            return None
        contact = None
        if "contact" in data:
            contact = uuid.UUID(str(data["contact"]))
        return DispatchTarget(
            uuid.UUID(str(data["workspace_id"])),
            uuid.UUID(str(data["agent_id"])),
            version,
            source,
            remote,
            contact,
        )
    except (ValueError, TypeError):
        return None
