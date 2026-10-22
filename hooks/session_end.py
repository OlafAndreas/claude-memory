#!/usr/bin/env python3
"""
SessionEnd hook: enqueue the session for the worker.

Runs inside Claude Code's 1.5 s SessionEnd budget, so it only writes a small
queue file; the handoff itself is written later by the worker.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_memory.paths import git_branch, memory_root, now_iso  # noqa: E402


def main() -> None:
    if os.environ.get("CLAUDE_MEMORY_CHILD") == "1":
        return
    data = json.load(sys.stdin)
    # CLI subcommands such as `claude mcp list` end a session that never wrote a transcript.
    if not data.get("transcript_path") or not Path(data["transcript_path"]).is_file():
        return
    sid = data["session_id"]
    cwd = data.get("cwd") or ""
    item = {
        "session_id": sid,
        "transcript_path": data.get("transcript_path"),
        "cwd": cwd,
        "git_branch": git_branch(cwd) if cwd else None,
        "ended": now_iso(),
        "reason": data.get("reason"),
        "attempts": 0,
    }
    queue = memory_root() / "queue"
    tmp = queue / f".{sid}.json.tmp"
    tmp.write_text(json.dumps(item), encoding="utf-8")
    os.replace(tmp, queue / f"{sid}.json")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — a hook must never break the session
        pass
    sys.exit(0)
