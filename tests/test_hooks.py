import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from claude_memory.indexer import rebuild_index
from claude_memory.notes import Note, write_note

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
HOOKS = ("session_end.py", "session_start.py", "prompt_hints.py")


def run(hook, payload, env=None):
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    e = {**os.environ, **(env or {})}
    return subprocess.run([PY, str(REPO / "hooks" / hook)], input=data, capture_output=True, env=e)


def out(r):
    return r.stdout.decode()


def seed(root, id="lesson-oring", surface_when="kestrel, O-ring, hollow, hul ring", summary="Hollow O-ring is intentional"):
    write_note(root, Note(id=id, kind="lesson", summary=summary, surface_when=surface_when, body="b",
                          created="2026-10-22T10:00:00+02:00", origin={"session_id": "s", "cwd": "/x"}))


def test_end_enqueues(root, tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("{}\n")
    run("session_end.py", {"session_id": "s1", "transcript_path": str(t), "cwd": str(REPO),
                           "reason": "prompt_input_exit"})
    q = json.loads((root / "queue" / "s1.json").read_text())
    assert q["git_branch"] and q["attempts"] == 0 and q["transcript_path"] == str(t)
    assert q["cwd"] == str(REPO) and q["reason"] == "prompt_input_exit" and q["ended"]


def test_end_skips_resume(root):
    run("session_end.py", {"session_id": "s1", "transcript_path": "/t", "cwd": "/", "reason": "resume"})
    assert not list((root / "queue").glob("*.json"))


def test_child_guard_all_hooks(root):
    seed(root); rebuild_index(root)
    payload = {"session_id": "s1", "transcript_path": "/t", "cwd": "/", "reason": "other",
               "source": "startup", "prompt": "hollow O-ring kestrel"}
    for h in HOOKS:
        r = run(h, payload, env={"CLAUDE_MEMORY_CHILD": "1"})
        assert out(r) == "" and r.returncode == 0
    assert not list((root / "queue").glob("*.json"))


def test_start_line_exact_and_short(root):
    r = out(run("session_start.py", {"session_id": "s1", "cwd": "/x", "source": "compact"}))
    assert r.startswith("Claude-memory (session s1, cwd /x): your earlier handoffs")
    assert "facts about Olaf go in MEMORY.md" in r and len(r) <= 400


def test_hints_shown_then_deduped(root):
    seed(root); rebuild_index(root)
    p = {"session_id": "s1", "cwd": "/x", "prompt": "hollow O-ring kestrel"}
    first = out(run("prompt_hints.py", p))
    assert first.startswith("Claude-memory hints (open with read_memory(id, session_id)):")
    assert "• Hollow O-ring is intentional (lesson-oring, 2026-10-22)" in first
    assert out(run("prompt_hints.py", p)) == ""
    log = [json.loads(l) for l in (root / "log" / "hints.jsonl").read_text().splitlines()]
    assert log[0]["ids"] == ["lesson-oring"] and log[0]["session_id"] == "s1"


def test_hints_max_three(root):
    for i in range(5):
        seed(root, id=f"n{i}", summary=f"note {i}")
    rebuild_index(root)
    r = out(run("prompt_hints.py", {"session_id": "s1", "cwd": "/x", "prompt": "hollow O-ring kestrel"}))
    assert r.count("•") == 3


def test_no_hint_on_weak_match(root):
    seed(root); rebuild_index(root)
    assert out(run("prompt_hints.py", {"session_id": "s1", "cwd": "/x", "prompt": "what's the weather"})) == ""


def test_hint_hook_no_index_exits_clean(root):
    r = run("prompt_hints.py", {"session_id": "s1", "cwd": "/x", "prompt": "kestrel"})
    assert r.returncode == 0 and out(r) == ""


def test_hint_hook_garbage_stdin(root):
    r = run("prompt_hints.py", b"not json")
    assert r.returncode == 0 and out(r) == ""


def test_hint_hook_fast(root):
    for i in range(500):
        seed(root, id=f"n{i}", surface_when=f"topic{i}, word{i % 7}", summary=f"note {i}")
    rebuild_index(root)
    times = []
    for i in range(5):
        t = time.perf_counter()
        run("prompt_hints.py", {"session_id": f"s{i}", "cwd": "/x", "prompt": "topic42 word3 something"})
        times.append(time.perf_counter() - t)
    assert statistics.median(times) < 0.150


def test_hint_hook_does_not_import_yaml(root):
    r = subprocess.run([PY, "-X", "importtime", str(REPO / "hooks" / "prompt_hints.py")],
                       input=json.dumps({"session_id": "s", "cwd": "/", "prompt": "x"}).encode(),
                       capture_output=True)
    assert b"yaml" not in r.stderr


def test_end_skips_session_without_transcript(root, tmp_path):
    run("session_end.py", {"session_id": "s1", "transcript_path": str(tmp_path / "never-written.jsonl"),
                           "cwd": "/", "reason": "other"})
    assert not list((root / "queue").glob("*.json"))
