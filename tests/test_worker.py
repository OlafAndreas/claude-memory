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


def test_default_profile_leaves_config_dir_unset(env, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    default = tmp_path / "home" / ".claude"
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    worker.run(env, default)
    assert calls(tmp_path)[0]["env"]["CLAUDE_CONFIG_DIR"] is None


def test_parse_result_plain_json_with_fence_in_body():
    from claude_memory.summarise import parse_result
    body = "Fixed it:\n```python\nprint(1)\n```\ndone"
    inner = json.dumps({"worth_keeping": True, "handoff": {"summary": "s", "surface_when": "w", "body": body},
                        "notes": []})
    assert parse_result(inner)["handoff"]["body"] == body
    assert parse_result(f"```json\n{inner}\n```")["handoff"]["body"] == body
    assert parse_result(f"Here you go:\n{inner}\nThanks")["handoff"]["body"] == body


def test_corrupt_queue_file_fails_and_others_continue(env, tmp_path):
    (env / "queue" / "aaa.json").write_text("{trunc")
    (env / "queue" / "bbb.json").write_text(json.dumps({"transcript_path": "/x"}))
    enqueue(env, "ccc", transcript(tmp_path / "t.jsonl"))
    res = worker.run(env, cfg(env))
    assert res["written"] == 1 and res["failed"] == 2
    assert sorted(p.name for p in (env / "queue" / "failed").glob("*.json")) == ["aaa.json", "bbb.json"]


def test_worker_note_id_built_from_scrubbed_summary(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_JSON", json.dumps({
        "worth_keeping": True, "handoff": {"summary": "h", "surface_when": "w", "body": "b"},
        "notes": [{"kind": "lesson", "summary": "sk-ant-api03-AbCdEf0123456789xyz leaked", "surface_when": "w",
                   "body": "b"}]}))
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    worker.run(env, cfg(env))
    assert not any("abcdef0123" in p.name.lower() for p in (env / "notes").glob("*.md"))


def test_claude_runs_in_neutral_cwd_without_claudecode(env, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.chdir(tmp_path)
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    worker.run(env, cfg(env))
    c = calls(tmp_path)[0]
    assert Path(c["cwd"]).resolve() == env.resolve() and c["claudecode"] is None


def test_retry_failed_requeues_with_zero_attempts(env):
    (env / "queue" / "failed" / "s1.json").write_text(json.dumps({"session_id": "s1", "attempts": 3, "error": "x"}))
    assert worker.retry_failed(env) == 1
    item = json.loads((env / "queue" / "s1.json").read_text())
    assert item["attempts"] == 0 and "error" not in item
    assert not list((env / "queue" / "failed").glob("*.json"))


def test_failure_detail_is_scrubbed(env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_JSON", "ghp_0123456789abcdefABCDEF0123456789abcd")
    enqueue(env, "s1", transcript(tmp_path / "t.jsonl"))
    worker.run(env, cfg(env))
    assert "ghp_0123" not in (env / "queue" / "s1.json").read_text()
    assert "ghp_0123" not in (env / "log" / "worker.log").read_text()


def test_long_session_is_not_cut_below_300k_chars(env, tmp_path):
    t = tmp_path / "t.jsonl"
    with open(t, "w") as f:
        for i in range(100):
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": f"Q{i:03d} " + "x" * 1000}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": f"A{i:03d} " + "y" * 1000}}) + "\n")
    enqueue(env, "s1", t)
    worker.run(env, cfg(env))
    p = calls(tmp_path)[0]["prompt"]
    assert "omitted" not in p and "Q050" in p


# --- sweep: sessions that ended without a SessionEnd hook (crash, kill -9) ---------
import os
import time

HOUR = 3600


def orphan(env, sid, age_hours, users=3, cwd="/p/Crashed"):
    proj = cfg(env) / "projects" / "-p-Crashed"
    proj.mkdir(parents=True, exist_ok=True)
    t = proj / f"{sid}.jsonl"
    with open(t, "w") as f:
        f.write(json.dumps({"type": "permission-mode", "cwd": cwd}) + "\n")
    transcript(t, users=users)
    old = time.time() - age_hours * HOUR
    os.utime(t, (old, old))
    return t


def since(env, hours_ago):
    m = env / "sweep.since"
    m.write_text("")
    old = time.time() - hours_ago * HOUR
    os.utime(m, (old, old))


def test_sweep_first_run_sets_marker_without_backfill(env):
    orphan(env, "old-session", age_hours=48)
    assert worker.sweep(env, cfg(env), time.time()) == 0
    assert (env / "sweep.since").exists()


def test_sweep_enqueues_idle_unprocessed_transcript(env):
    since(env, 24)
    t = orphan(env, "crashed1", age_hours=3)
    assert worker.sweep(env, cfg(env), time.time()) == 1
    item = json.loads((env / "queue" / "crashed1.json").read_text())
    assert item["transcript_path"] == str(t) and item["reason"] == "swept" and item["cwd"] == "/p/Crashed"
    assert item["attempts"] == 0 and item["ended"]


def test_sweep_ignores_recently_active(env):
    since(env, 24)
    orphan(env, "live", age_hours=0.5)
    assert worker.sweep(env, cfg(env), time.time()) == 0


def test_sweep_ignores_transcripts_older_than_marker(env):
    since(env, 24)
    orphan(env, "ancient", age_hours=48)
    assert worker.sweep(env, cfg(env), time.time()) == 0


def test_sweep_ignores_processed_queued_and_failed(env):
    since(env, 24)
    t = orphan(env, "done", age_hours=3)
    lines = len(t.read_text().splitlines())
    (env / "state" / "done.json").write_text(json.dumps({"offset_lines": lines, "seq": 1, "started": None,
                                                         "note_summaries": []}))
    orphan(env, "queued", age_hours=3)
    (env / "queue" / "queued.json").write_text("{}")
    orphan(env, "broken", age_hours=3)
    (env / "queue" / "failed" / "broken.json").write_text("{}")
    assert worker.sweep(env, cfg(env), time.time()) == 0


def test_sweep_picks_up_growth_after_processing(env):
    since(env, 24)
    t = orphan(env, "grew", age_hours=3)
    (env / "state" / "grew.json").write_text(json.dumps({"offset_lines": 2, "seq": 1, "started": None,
                                                         "note_summaries": []}))
    assert worker.sweep(env, cfg(env), time.time()) == 1


def test_run_sweeps_then_processes(env, tmp_path):
    since(env, 24)
    orphan(env, "crashed2", age_hours=3)
    res = worker.run(env, cfg(env))
    assert res["swept"] == 1 and res["written"] == 1
