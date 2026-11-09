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


def _mentions_quota(error: object) -> bool:
    """Whether the provider said its credits or quota are used up (classified, never echoed)."""
    inner = getattr(error, "error", error)
    text = f"{inner} {error}".lower()
    return "quota" in text or "credit" in text


def describe_failure(error: object) -> Failure:
    code = _status_code(error)
    if code == 429 and _mentions_quota(error):
        return Failure(
            "provider error (429, credits used up)",
            "LiveKit reports that the credits included in your plan for a speech, language or "
            "voice service are used up (quota exceeded). Use your own provider keys (Settings, "
            "then Connect via in the agent's Voice & models tab), upgrade the plan, or wait for "
            "the credits to reset.",
        )
    if code == 429:
        return Failure(
            "provider error (429)",
            "A speech, language or voice service refused the request as too many (429): a rate or "
            "concurrency limit. Wait a moment and try again; on LiveKit's free plan check "
            "Settings, then Usage and limits in the LiveKit dashboard.",
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
