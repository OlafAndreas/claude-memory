import fcntl
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from claude_memory import worker
from claude_memory.notes import Note, load_all, parse_note, write_note

FAKE = Path(__file__).parent / "fixtures" / "fake_claude.py"


@pytest.fixture
def env(root, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_MEMORY_CLAUDE_BIN", str(FAKE))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.delenv("FAKE_CLAUDE_MODE", raising=False)
    return root


def cfg(root):
    return root.parent


def calls(tmp_path):
    p = tmp_path / "calls.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def transcript(path, users=3, start=0):
    with open(path, "a") as f:
        for i in range(start, start + users):
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": f"question {i}"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": f"answer {i}"}}) + "\n")
    return path


def enqueue(root, sid, tpath, cwd="/p/HallbarPoseRamme"):
    item = {"session_id": sid, "transcript_path": str(tpath), "cwd": cwd, "git_branch": "olaf/x",
            "ended": "2026-10-22T15:00:00+02:00", "reason": "prompt_input_exit", "attempts": 0}
    (root / "queue" / f"{sid}.json").write_text(json.dumps(item))
    return item


def test_writes_handoff_and_notes_with_origin(env, tmp_path):
    sid = "abcdef1234567890"
    enqueue(env, sid, transcript(tmp_path / "t.jsonl"))
    res = worker.run(env, cfg(env))
    assert res["written"] == 1
    h = parse_note((env / "handoffs" / "abcdef12-1.md").read_text())
    assert h.kind == "handoff" and h.seq == 1
    assert h.origin["session_id"] == sid and h.origin["cwd"] == "/p/HallbarPoseRamme"
    assert h.origin["git_branch"] == "olaf/x" and h.origin["ended"] == "2026-10-22T15:00:00+02:00"
    assert h.origin["started"]
    assert h.expires == (date.fromisoformat(h.created[:10]) + timedelta(days=30)).isoformat()
    notes = [n for n in load_all(env) if n.kind != "handoff"]
    assert [n.source for n in notes] == ["worker"] and notes[0].links == [h.id]
    assert notes[0].id == "lesson-measure-before-trusting-assumed"
    assert not list((env / "queue").glob("*.json"))
    assert (env / "index.sqlite").exists()


def test_command_has_guards(env, tmp_path):
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    worker.run(env, cfg(env))
    c = calls(tmp_path)[0]
    argv = " ".join(c["argv"])
    for flag in ("-p", "--model haiku", "--no-session-persistence", "--strict-mcp-config",
                 "disableAllHooks", "--output-format json"):
        assert flag in argv
    assert "--bare" not in argv and '--tools ' in argv
    assert c["env"] == {"CLAUDE_MEMORY_CHILD": "1", "CLAUDE_CONFIG_DIR": str(cfg(env))}


def test_prompt_contains_rules_and_memory_index(env, tmp_path):
    mem = cfg(env) / "projects" / "-Users-x" / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("- [Fact](f.md) — Olaf likes FreeCAD")
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    worker.run(env, cfg(env))
    p = calls(tmp_path)[0]["prompt"]
    assert "Olaf likes FreeCAD" in p and "question 0" in p and "worth_keeping" in p


def test_fenced_json_accepted(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fenced")
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    assert worker.run(env, cfg(env))["written"] == 1


def test_garbage_retried_then_failed(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "garbage")
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    for _ in range(3):
        worker.run(env, cfg(env))
    failed = json.loads((env / "queue" / "failed" / "s1.json").read_text())
    assert failed["attempts"] == 3 and failed["error"]
    assert not list((env / "queue").glob("*.json"))
    assert not list((env / "handoffs").glob("*.md")) and not list((env / "notes").glob("*.md"))


def test_failure_after_one_attempt_stays_queued(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    assert worker.run(env, cfg(env))["failed"] == 1
    assert json.loads((env / "queue" / "s1.json").read_text())["attempts"] == 1


def test_timeout_counts_as_failure(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    assert worker.run(env, cfg(env), timeout=1)["failed"] == 1


def test_missing_transcript_fails_immediately(env, tmp_path):
    enqueue(env, "s1", tmp_path / "gone.jsonl")
    worker.run(env, cfg(env))
    assert "error" in json.loads((env / "queue" / "failed" / "s1.json").read_text())


def test_empty_transcript_fails_immediately(env, tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text('{"type":"mystery"}\n')
    enqueue(env, "s1", p)
    worker.run(env, cfg(env))
    assert (env / "queue" / "failed" / "s1.json").exists()


def test_trivial_session_writes_nothing(env, tmp_path):
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl", users=1))
    res = worker.run(env, cfg(env))
    assert res["skipped"] == 1 and calls(tmp_path) == []
    assert not list((env / "handoffs").glob("*.md")) and not list((env / "queue").glob("*.json"))


def test_not_worth_keeping_writes_nothing(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "notworth")
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    assert worker.run(env, cfg(env))["skipped"] == 1
    assert not list((env / "handoffs").glob("*.md"))


def test_resumed_session_second_segment(env, tmp_path, monkeypatch):
    sid = "abcdef1234567890"
    t = transcript(tmp_path / "t.jsonl")
    enqueue(env, sid, t)
    worker.run(env, cfg(env))
    transcript(t, start=10)
    enqueue(env, sid, t)
    monkeypatch.setenv("FAKE_CLAUDE_JSON", json.dumps({
        "worth_keeping": True, "handoff": {"summary": "Second part", "surface_when": "x", "body": "b"},
        "notes": []}))
    worker.run(env, cfg(env))
    h2 = parse_note((env / "handoffs" / "abcdef12-2.md").read_text())
    assert h2.seq == 2 and h2.links == ["abcdef12-1"]
    p = calls(tmp_path)[1]["prompt"]
    assert "question 10" in p and "question 0" not in p
    assert "Measured the bucket: 250 wide, not 247" in p
    assert "Measure before trusting assumed dimensions" in p


def test_note_id_collision_suffix(env, tmp_path):
    write_note(env, Note(id="lesson-measure-before-trusting-assumed", kind="lesson",
                         summary="other", surface_when="", body="", created="2026-10-01T00:00:00+02:00",
                         origin={}, source="claude"))
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    worker.run(env, cfg(env))
    assert (env / "notes" / "lesson-measure-before-trusting-assumed-2.md").exists()


def test_secrets_scrubbed_in_output(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_BODY", "key ctx7sk-0a1b2c3d-0000-4000-8000-123456789abc used")
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    worker.run(env, cfg(env))
    text = next((env / "handoffs").glob("*.md")).read_text()
    assert "0a1b2c3d" not in text and "[redacted]" in text


def test_lock_prevents_second_run(env, tmp_path):
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    with open(env / "worker.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert worker.run(env, cfg(env)) == {"locked": True}
    assert (env / "queue" / "s1.json").exists()


def _note(root, id, kind="lesson", source="worker", created="2026-01-01T00:00:00+01:00", **kw):
    write_note(root, Note(id=id, kind=kind, summary="s", surface_when="", body="", created=created,
                          origin={}, source=source, **kw))


def test_expire_handoff_after_30_days(env):
    _note(env, "old-1", kind="handoff", source=None, seq=1, expires="2026-10-01")
    _note(env, "new-1", kind="handoff", source=None, seq=1, expires="2026-11-30")
    assert worker.expire(env, date(2026, 10, 22)) == 1
    assert [p.stem for p in (env / "handoffs").glob("*.md")] == ["new-1"]


def test_expire_unread_worker_note_after_90_days(env):
    _note(env, "lesson-old")
    _note(env, "lesson-young", created="2026-10-01T00:00:00+02:00")
    worker.expire(env, date(2026, 10, 22))
    assert sorted(p.stem for p in (env / "notes").glob("*.md")) == ["lesson-young"]


def test_read_worker_note_survives(env):
    _note(env, "lesson-old")
    (env / "log" / "reads.jsonl").write_text(json.dumps({"ts": "x", "session_id": "s", "id": "lesson-old"}) + "\n")
    worker.expire(env, date(2026, 10, 22))
    assert (env / "notes" / "lesson-old.md").exists()


def test_claude_note_never_expires(env):
    _note(env, "lesson-mine", source="claude")
    worker.expire(env, date(2030, 1, 1))
    assert (env / "notes" / "lesson-mine.md").exists()
