"""
Lenient reader for Claude Code transcript JSONL.

The format is internal to Claude Code and changes between versions, so this
keeps only plain user/assistant text and skips anything it does not recognise.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple

_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_LABEL = {"user": "USER", "assistant": "CLAUDE"}


class Turn(NamedTuple):
    role: str
    text: str


_ACTION_MAX = 200
_PATH_KEYS = ("file_path", "notebook_path", "path")


def _action(item: dict) -> str:
    """One short line for a tool call, so the summariser can tell who did what."""
    name, args = item.get("name") or "tool", item.get("input") or {}
    if isinstance(args, dict) and isinstance(args.get("command"), str):
        detail = args["command"]
    elif isinstance(args, dict) and name in ("Read", "Edit", "Write", "NotebookEdit") and \
            any(isinstance(args.get(k), str) for k in _PATH_KEYS):
        detail = next(args[k] for k in _PATH_KEYS if isinstance(args.get(k), str))
    else:
        detail = json.dumps(args, ensure_ascii=False)
    line = f"[ran {name}: {' '.join(detail.split())}"
    return (line[:_ACTION_MAX - 2] + "…]") if len(line) > _ACTION_MAX - 1 else line + "]"


def _segments(content) -> list[str]:
    """Text and tool-call lines of one message, in order."""
    if not isinstance(content, list):
        return [_text_of(content)]
    out, text = [], []
    for c in content:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "text":
            text.append(c.get("text", ""))
        elif c.get("type") == "tool_use":
            out.append(_text_of("\n".join(text)) if text else "")
            text = []
            out.append(_action(c))
    out.append(_text_of("\n".join(text)) if text else "")
    return out


def _text_of(content) -> str:
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    else:
        return ""
    return _REMINDER.sub("", "\n".join(parts)).strip()


def read_turns(path: Path, start_line: int = 0) -> tuple[list[Turn], int]:
    turns: list[Turn] = []
    total = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for total, line in enumerate(f, start=1):
            if total <= start_line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            kind = rec.get("type") if isinstance(rec, dict) else None
            msg = rec.get("message") if kind in _LABEL else None
            if not isinstance(msg, dict) or msg.get("role") != kind:
                continue
            if rec.get("isMeta") or rec.get("isSidechain"):
                continue
            for text in _segments(msg.get("content")) if kind == "assistant" else [_text_of(msg.get("content"))]:
                if text:
                    turns.append(Turn(kind, text))
    return turns, total


def _render(t: Turn) -> str:
    return f"{_LABEL[t.role]}: {t.text}"


def condense(turns: list[Turn], budget: int = 60_000) -> str:
    sep = "\n\n"
    blocks = [_render(t) for t in turns]
    if sum(len(b) + len(sep) for b in blocks) <= budget:
        return sep.join(blocks)
    marker_room = 40
    head, used = [], 0
    for b in blocks:
        if used + len(b) + len(sep) > budget // 3:
            break
        head.append(b)
        used += len(b) + len(sep)
    tail, left = [], budget - used - marker_room
    for b in reversed(blocks[len(head):]):
        if len(b) + len(sep) > left:
            break
        tail.insert(0, b)
        left -= len(b) + len(sep)
    omitted = len(blocks) - len(head) - len(tail)
    if not head and not tail:
        # A single turn larger than the budget: keep its start and end.
        b = blocks[-1]
        half = (budget - marker_room) // 2
        return f"{b[:half]}{sep}[… truncated …]{sep}{b[-half:]}"
    return sep.join([*head, f"[… {omitted} turns omitted …]", *tail])


def is_trivial(turns: list[Turn]) -> bool:
    users = sum(1 for t in turns if t.role == "user")
    return users < 3 and sum(len(t.text) for t in turns) < 2000
