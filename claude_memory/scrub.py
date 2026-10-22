"""Redact secrets and national ID numbers before anything is written to memory."""
from __future__ import annotations

import re

R = "[redacted]"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:sk|ctx7sk|rk|pk)-[A-Za-z0-9_\-]{12,}"), R),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), R),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*"), R),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-~+/=]{6,}"), r"\1 " + R),
    (re.compile(r"(?i)\b(password|passord|passwd|pwd)(\s*[:=]\s*)\S+"), r"\1\2" + R),
    (re.compile(r"(?<![\d\-])\b\d{11}\b(?![\d\-])"), R),
]


def scrub(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text
