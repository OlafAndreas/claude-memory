#!/usr/bin/env python3
"""
UserPromptSubmit hook: inject up to three one-line hints when memory matches.

Stdlib + claude_memory.index only (no yaml, no Markdown reads): runs on every
prompt. Prints nothing on a weak match or any error, and never blocks.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_memory.index import HINT_MIN_TERMS, search  # noqa: E402
from claude_memory.paths import memory_root, now_iso  # noqa: E402

MAX_HINTS = 3
QUERY_MAX_CHARS = 500


def main() -> None:
    if os.environ.get("CLAUDE_MEMORY_CHILD") == "1":
        return
    data = json.load(sys.stdin)
    sid = data.get("session_id") or "unknown"
    cwd = data.get("cwd")
    root = memory_root()
    hinted_file = root / "log" / "hinted" / sid
    already = set(hinted_file.read_text().split()) if hinted_file.exists() else set()

    hits = [h for h in search(root, (data.get("prompt") or "")[:QUERY_MAX_CHARS], cwd=cwd, limit=10)
            if h.strength >= HINT_MIN_TERMS and h.id not in already][:MAX_HINTS]
    if not hits:
        return

    lines = ["Claude-memory hints (open with read_memory(id, session_id)):"]
    lines += [f"• {h.summary} ({h.id}, {h.date})" for h in hits]
    print("\n".join(lines))
    sys.stdout.flush()

    with open(hinted_file, "a", encoding="utf-8") as f:
        f.write("".join(f"{h.id}\n" for h in hits))
    with open(root / "log" / "hints.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now_iso(), "session_id": sid, "cwd": cwd,
                            "ids": [h.id for h in hits]}) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — a hook must never block a prompt
        pass
    sys.exit(0)
