"""
Turn a condensed transcript into a handoff (and up to three notes) with Haiku.

Runs `claude -p` with hooks, tools, MCP and session persistence disabled, and
CLAUDE_MEMORY_CHILD=1 so our own hooks ignore the call.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .paths import profile_env

NOTE_KINDS = ("lesson", "outcome", "question")
MAX_NOTES = 3


class SummariseError(Exception):
    pass


def build_prompt(condensed: str, memory_index: str, previous_summary: str | None,
                 existing_note_summaries: list[str]) -> str:
    parts = [
        "You are writing memory for the next Claude Code session. You are Claude; the next session "
        "is also Claude and will read this as a note from a previous instance of itself.",
        "",
        "Rules:",
        "- Write the handoff body in first person, addressed to the next session: what we did, what is "
        "unresolved, what I got wrong and why, what changed between me and Olaf.",
        "- Keep only Claude's own side. Facts about Olaf, his projects, preferences and rules belong in "
        "MEMORY.md (its index is below); do not repeat them.",
        "- surface_when: comma-separated words and situations a future prompt would contain when this "
        "matters, in both Norwegian and English.",
        "- Never copy secrets, tokens, API keys, passwords, national ID numbers or personal details "
        "about people other than Olaf.",
        f"- notes: at most {MAX_NOTES}, kind one of lesson (a mistake and why), outcome (what happened "
        "after something), question (an open curiosity). Only when they would matter beyond this session.",
        "- If nothing in this session is worth handing on, set worth_keeping to false.",
        "",
        "Reply with exactly one JSON object and nothing else:",
        '{"worth_keeping": bool, "handoff": {"summary": "one line", "surface_when": "...", "body": "..."}, '
        '"notes": [{"kind": "lesson|outcome|question", "summary": "one line", "surface_when": "...", "body": "..."}]}',
        "",
        "MEMORY.md index:",
        memory_index or "(empty)",
    ]
    if previous_summary is not None:
        parts += ["", "This session was resumed. The earlier part was already handed off as:", previous_summary,
                  "Write the handoff for the new part only."]
    if existing_note_summaries:
        parts += ["", "Notes already extracted from this session (do not extract these again):",
                  *(f"- {s}" for s in existing_note_summaries)]
    parts += ["", "Transcript:", condensed]
    return "\n".join(parts)


def claude_bin() -> str:
    found = os.environ.get("CLAUDE_MEMORY_CLAUDE_BIN") or shutil.which("claude")
    if not found:
        raise SummariseError("claude binary not found")
    return found


def call_claude(prompt: str, config_dir: Path, timeout: int = 180) -> dict:
    cmd = [claude_bin(), "-p", "--model", "haiku", "--tools", "", "--strict-mcp-config",
           "--no-session-persistence", "--settings", '{"disableAllHooks":true}',
           "--output-format", "json"]
    env = {**profile_env(config_dir), "CLAUDE_MEMORY_CHILD": "1"}
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise SummariseError(f"timed out after {timeout}s")
    if r.returncode != 0:
        raise SummariseError(f"exit {r.returncode}: {r.stderr.strip()[:200]}")
    try:
        inner = json.loads(r.stdout)["result"]
    except (ValueError, KeyError, TypeError):
        raise SummariseError(f"unexpected envelope: {r.stdout[:200]}")
    return parse_result(inner)


def parse_result(inner: str) -> dict:
    m = re.search(r"```(?:json)?\s*(.*?)```", inner, re.S)
    text = m.group(1) if m else inner
    try:
        data = json.loads(text.strip())
    except ValueError:
        raise SummariseError(f"not JSON: {inner[:200]}")
    if not isinstance(data, dict) or not isinstance(data.get("worth_keeping"), bool):
        raise SummariseError("missing worth_keeping")
    if not data["worth_keeping"]:
        return {"worth_keeping": False, "handoff": None, "notes": []}
    h = data.get("handoff")
    if not isinstance(h, dict) or not all(isinstance(h.get(k), str) for k in ("summary", "surface_when", "body")):
        raise SummariseError("bad handoff")
    notes = []
    for n in (data.get("notes") or [])[:MAX_NOTES]:
        if isinstance(n, dict) and n.get("kind") in NOTE_KINDS and \
                all(isinstance(n.get(k), str) for k in ("summary", "surface_when", "body")):
            notes.append(n)
    return {"worth_keeping": True, "handoff": h, "notes": notes}
