from pathlib import Path

import pytest

from claude_memory.notes import Note, load_all, note_path, parse_note, render_note, slugify, write_note
from claude_memory.paths import config_dir, git_branch, memory_root

ORIGIN = {"session_id": "7c1e", "cwd": "/x", "git_branch": None, "started": "a", "ended": "b"}


def make(kind="lesson", id="lesson-oring", **kw):
    return Note(id=id, kind=kind, summary="Hollow O-ring is intentional",
                surface_when="kestrel, O-ring, hul ring", body="Jeg tok feil først.\nLine 2",
                created="2026-10-22T14:03:00+02:00", origin=dict(ORIGIN), **kw)


def test_round_trip_preserves_all_fields():
    n = make(source="claude", links=["handoff-7c1e-1"])
    assert parse_note(render_note(n)) == n


def test_round_trip_handoff_fields():
    n = make(kind="handoff", id="7c1e0000-1", seq=1, expires="2026-11-21")
    assert parse_note(render_note(n)) == n


def test_handoff_path_and_other_path(root):
    assert note_path(root, make(kind="handoff", id="h-1", seq=1)).parent.name == "handoffs"
    assert note_path(root, make()).parent.name == "notes"


def test_load_all_skips_garbage(root):
    (root / "notes" / "bad.md").write_text("no frontmatter")
    write_note(root, make())
    assert [n.id for n in load_all(root)] == ["lesson-oring"]


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        make(kind="fact")


def test_memory_root_follows_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "p"))
    assert memory_root() == tmp_path / "p" / "claude-memory"
    for sub in ("handoffs", "notes", "queue/failed", "state", "log/hinted"):
        assert (tmp_path / "p" / "claude-memory" / sub).is_dir()


def test_memory_root_default(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert config_dir() == Path.home() / ".claude"


def test_git_branch_none_outside_repo(tmp_path):
    assert git_branch(str(tmp_path)) is None


def test_git_branch_in_repo():
    assert git_branch(str(Path(__file__).parent)) is not None


def test_slugify_cuts_at_word_boundary():
    assert slugify("Measure before trusting assumed dimensions") == "measure-before-trusting-assumed"
    assert slugify("Bøtte på Åsen") == "botte-pa-asen"
    assert slugify("!!!") == "note"
