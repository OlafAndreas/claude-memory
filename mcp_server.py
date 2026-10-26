#!/usr/bin/env python3
"""
Local MCP server for claude-memory: search, read, remember and forget notes.

The store is per Claude Code profile (CLAUDE_CONFIG_DIR, else ~/.claude), so the
personal and work profiles never see each other's notes.

Run:  ./.venv/bin/python mcp_server.py     (stdio transport)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make sure we can import the package regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_memory.index import search  # noqa: E402
from claude_memory.indexer import rebuild_index  # noqa: E402
from claude_memory.notes import Note, load_all, note_path, render_note, slugify, write_note  # noqa: E402
from claude_memory.paths import git_branch, memory_root, now_iso  # noqa: E402
from claude_memory.scrub import scrub  # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    sys.stderr.write("Missing dependency 'mcp'. Run: pip install -r requirements.txt\n")
    raise

mcp = FastMCP("claude-memory")

REMEMBER_KINDS = ("lesson", "outcome", "question")


# --- helpers ------------------------------------------------------------------
def _find(root: Path, id: str) -> Note | None:
    return next((n for n in load_all(root) if n.id == id), None)


# --- tools ----------------------------------------------------------------------
@mcp.tool()
def search_memory(query: str, kind: str | None = None, cwd: str | None = None, limit: int = 5) -> list[dict]:
    """Search your own earlier handoffs, lessons, outcomes and questions.

    Returns id, kind, summary, date and origin cwd for each match (no body);
    open one with read_memory. kind filters to handoff|lesson|outcome|question;
    cwd ranks notes from that project higher.
    """
    return [{"id": h.id, "kind": h.kind, "summary": h.summary, "date": h.date, "cwd": h.cwd}
            for h in search(memory_root(), query, cwd=cwd, kind=kind, limit=limit)]


@mcp.tool()
def read_memory(id: str, session_id: str | None = None) -> str:
    """Read one note in full. Pass this session's id (from the Claude-memory startup line)."""
    root = memory_root()
    note = _find(root, id)
    if note is None:
        return f"No note with id {id!r}. Use search_memory to find ids."
    with open(root / "log" / "reads.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now_iso(), "session_id": session_id, "id": id}) + "\n")
    return render_note(note)


@mcp.tool()
def remember(kind: str, summary: str, surface_when: str, body: str, session_id: str, cwd: str) -> str:
    """Save a long-term note of your own: lesson (a mistake and why), outcome (what happened
    after something) or question (an open curiosity).

    Only Claude's own side goes here; facts about the user, their projects and preferences go in
    MEMORY.md. Write body in first person to a future session. surface_when lists the words
    and situations, in Norwegian and English, a future prompt would contain when this matters.
    session_id and cwd come from the Claude-memory startup line. Returns the note id.
    """
    if kind not in REMEMBER_KINDS:
        raise ValueError(f"kind must be one of {REMEMBER_KINDS}")
    root = memory_root()
    summary, surface_when, body = scrub(summary.strip()), scrub(surface_when.strip()), scrub(body.strip())
    origin = {"session_id": session_id, "cwd": cwd, "git_branch": git_branch(cwd),
              "started": None, "ended": None}
    existing = next((n for n in load_all(root) if n.source == "worker" and n.summary == summary), None)
    if existing is not None:
        note = Note(id=existing.id, kind=kind, summary=summary, surface_when=surface_when, body=body,
                    created=now_iso(), origin=origin, source="claude", links=existing.links)
    else:
        note = Note(id=f"{kind}-{slugify(summary)}", kind=kind, summary=summary, surface_when=surface_when,
                    body=body, created=now_iso(), origin=origin, source="claude")
        base, i = note.id, 1
        while note_path(root, note).exists():
            i += 1
            note.id = f"{base}-{i}"
    write_note(root, note)
    rebuild_index(root)
    return note.id


@mcp.tool()
def forget(id: str) -> str:
    """Delete a note you no longer want to keep."""
    root = memory_root()
    note = _find(root, id)
    if note is None:
        return f"No note with id {id!r}."
    note_path(root, note).unlink()
    rebuild_index(root)
    return f"Forgot {id}."


if __name__ == "__main__":
    mcp.run()
