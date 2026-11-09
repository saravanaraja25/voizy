"""Turning a provider failure into something a person can act on.

When a speech, language or voice service refuses a request the session cannot continue, and the
caller just hears silence. The worker tells the dashboard what happened and records the call as
failed with a real reason, instead of "ended".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Failure:
    reason: str  # short, stored as the call's end reason
    message: str  # shown to the person testing the agent


def _status_code(error: object) -> int | None:
    inner = getattr(error, "error", error)  # the SDK wraps the original exception
    for candidate in (inner, error):
        code = getattr(candidate, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def describe_failure(error: object) -> Failure:
    code = _status_code(error)
    if code == 429:
        return Failure(
            "provider error (429)",
            "A speech, language or voice service refused the request as too many (429). On "
            "LiveKit's free plan this usually means the included Inference allowance is used up. "
            "Use your own provider keys (Settings, then Connect via in the agent's Voice & models "
            "tab) or upgrade the plan.",
        )
    if code in (401, 403):
        return Failure(
            f"provider error ({code})",
            "A speech, language or voice service rejected the credentials. Check the keys saved in "
            "Settings.",
        )
    suffix = f" ({code})" if code else ""
    return Failure(
        f"provider error{suffix}",
        "A speech, language or voice service failed, so the call was stopped. The worker log has "
        "the details.",
    )
