import json
from pathlib import Path

import pytest

import mcp_server as m
from claude_memory.notes import Note, parse_note, write_note


def remember(**kw):
    args = dict(kind="lesson", summary="Hollow O-ring is intentional", surface_when="kestrel, O-ring, hul ring",
                body="I got this wrong first.", session_id="s1", cwd="/tmp")
    args.update(kw)
    return m.remember(**args)


def test_remember_then_search_then_read(root):
    nid = remember()
    assert nid == "lesson-hollow-o-ring-is-intentional"
    hits = m.search_memory("kestrel O-ring")
    assert hits[0]["id"] == nid and hits[0]["kind"] == "lesson" and hits[0]["cwd"] == "/tmp"
    text = m.read_memory(nid, session_id="s1")
    assert "I got this wrong first." in text and "source: claude" in text


@pytest.mark.parametrize("kind", ["handoff", "fact"])
def test_remember_rejects_handoff_and_fact(root, kind):
    with pytest.raises(ValueError):
        remember(kind=kind)


def test_remember_scrubs(root):
    nid = remember(body="token ghp_0123456789abcdefABCDEF0123456789abcd here")
    assert "ghp_0123" not in m.read_memory(nid)


def test_remember_resaves_worker_note_as_claude(root):
    write_note(root, Note(id="lesson-x", kind="lesson", summary="Hollow O-ring is intentional",
                          surface_when="a", body="old", created="2026-01-01T00:00:00+01:00",
                          origin={"session_id": "old"}, source="worker"))
    nid = remember()
    assert nid == "lesson-x"
    n = parse_note((root / "notes" / "lesson-x.md").read_text())
    assert n.source == "claude" and n.body == "I got this wrong first."
    assert len(list((root / "notes").glob("*.md"))) == 1


def test_remember_origin(root):
    nid = remember(cwd=str(Path(__file__).resolve().parent.parent))
    n = parse_note((root / "notes" / f"{nid}.md").read_text())
    assert n.origin["session_id"] == "s1" and n.origin["git_branch"] is not None


def test_read_logs_session(root):
    nid = remember()
    m.read_memory(nid, session_id="s9")
    rec = json.loads((root / "log" / "reads.jsonl").read_text().splitlines()[-1])
    assert rec["id"] == nid and rec["session_id"] == "s9"


def test_read_unknown_id(root):
    assert m.read_memory("nope").startswith("No note with id")


def test_forget_removes_from_search(root):
    nid = remember()
    m.forget(nid)
    assert m.search_memory("kestrel") == []
    assert not (root / "notes" / f"{nid}.md").exists()


def test_search_has_no_body(root):
    remember()
    assert "body" not in m.search_memory("kestrel")[0]
