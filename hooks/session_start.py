#!/usr/bin/env python3
"""
SessionStart hook: tell the session the memory exists and what its id is.

Prints one short line (the session does not otherwise know its own id), then
kicks the worker in the background if anything is queued.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from claude_memory.paths import memory_root  # noqa: E402

LINE = ("Claude-memory (session {session_id}, cwd {cwd}): your earlier handoffs, lessons, outcomes "
        "and questions are searchable via search_memory/read_memory; save your own lessons with "
        "remember (facts about the user go in MEMORY.md). Pass this session_id to remember/read_memory. "
        "Hints appear automatically when relevant.")


def main() -> None:
    if os.environ.get("CLAUDE_MEMORY_CHILD") == "1":
        return
    data = json.load(sys.stdin)
    print(LINE.format(session_id=data.get("session_id", "?"), cwd=data.get("cwd", "?")))
    sys.stdout.flush()
    cli = REPO / "cli.py"
    if cli.exists() and any((memory_root() / "queue").glob("*.json")):
        subprocess.Popen([sys.executable, str(cli), "run-worker"], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — a hook must never break the session
        pass
    sys.exit(0)
