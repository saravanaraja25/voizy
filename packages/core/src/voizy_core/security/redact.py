"""Best-effort removal of obvious personal data from text before it is stored.

This is a safety net, not a guarantee: it catches the patterns below and will miss names,
addresses and anything phrased unusually. Agents that must not keep transcripts at all should turn
transcript storage off.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_DIGIT_RUN = re.compile(r"(?<!\w)\+?\d(?:[\s().-]{0,2}\d){6,}(?!\w)")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_WORDS = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)"
# Speech recognition often writes numbers as words: "five five five one two three four".
_SPOKEN = re.compile(rf"\b{_WORDS}(?:[\s,.-]+{_WORDS}){{6,}}\b", re.IGNORECASE)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _digits_replacement(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if 13 <= len(digits) <= 19 and _luhn(digits):
        return "[card]"
    return "[phone]" if len(digits) <= 15 else "[number]"


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _SSN.sub("[id]", text)
    text = _DIGIT_RUN.sub(_digits_replacement, text)
    return _SPOKEN.sub("[number]", text)
