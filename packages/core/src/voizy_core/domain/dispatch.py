"""What a voice job is told to run: set server-side when a call is dispatched, parsed strictly."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

# Name the voice worker registers under; explicit dispatch targets it.
AGENT_WORKER_NAME = "voizy"

_KEYS = {"workspace_id", "agent_id"}


@dataclass(frozen=True)
class DispatchTarget:
    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    version: int | None = None  # None = the published version; set for test calls on drafts


def encode_dispatch(target: DispatchTarget) -> str:
    data: dict[str, object] = {
        "workspace_id": str(target.workspace_id),
        "agent_id": str(target.agent_id),
    }
    if target.version is not None:
        data["version"] = target.version
    return json.dumps(data, separators=(",", ":"))


def parse_dispatch(raw: str | None) -> DispatchTarget | None:
    """Return the target, or None if the metadata is absent or anything but the expected shape."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) - _KEYS - {"version"} or _KEYS - set(data):
            return None
        version = data.get("version")
        if "version" in data and (
            not isinstance(version, int) or isinstance(version, bool) or version < 1
        ):
            return None
        return DispatchTarget(
            uuid.UUID(str(data["workspace_id"])), uuid.UUID(str(data["agent_id"])), version
        )
    except (ValueError, TypeError):
        return None
