"""
Queue worker: transcripts → handoffs and notes, then reindex and expire.

One instance at a time per profile (flock on worker.lock). Started by launchd
every 10 minutes and kicked by the SessionStart hook.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .indexer import rebuild_index
from .notes import Note, load_all, note_path, parse_note, slugify, write_note
from .paths import now_iso
from .scrub import scrub
from .summarise import SummariseError, build_prompt, call_claude
from .transcript import condense, is_trivial, read_turns

HANDOFF_TTL_DAYS = 30
WORKER_NOTE_TTL_DAYS = 90
MAX_ATTEMPTS = 3
SWEEP_IDLE_HOURS = 2
# ~75–100k tokens: well inside Haiku's context, so only day-long sessions get trimmed.
CONDENSE_BUDGET = 300_000


class _Permanent(Exception):
    """Failure that retrying cannot fix."""


# --- helpers ------------------------------------------------------------------
def _log(root: Path, sid: str, outcome: str, detail: str = "") -> None:
    with open(root / "log" / "worker.log", "a", encoding="utf-8") as f:
        f.write(f"{now_iso()} {sid} {outcome} {detail}".rstrip() + "\n")


def _memory_index(config_dir: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in sorted(config_dir.glob("projects/*/memory/MEMORY.md")))


def _load_state(root: Path, sid: str) -> dict:
    p = root / "state" / f"{sid}.json"
    return json.loads(p.read_text()) if p.exists() else {"offset_lines": 0, "seq": 0, "started": None,
                                                         "note_summaries": []}


def _save_state(root: Path, sid: str, state: dict) -> None:
    (root / "state" / f"{sid}.json").write_text(json.dumps(state))


def _unique_id(root: Path, n: Note) -> str:
    base, i = n.id, 1
    while note_path(root, n).exists():
        i += 1
        n.id = f"{base}-{i}"
    return n.id


def _clean(text: str) -> str:
    return scrub(text.strip())


# --- one queue item -------------------------------------------------------------
def _process(root: Path, config_dir: Path, item: dict, timeout: int) -> str:
    sid = item["session_id"]
    tpath = Path(item.get("transcript_path") or "")
    if not tpath.is_file():
        raise _Permanent(f"transcript missing: {tpath}")
    state = _load_state(root, sid)
    turns, total = read_turns(tpath, start_line=state["offset_lines"])
    if not turns and state["offset_lines"] == 0:
        raise _Permanent("no readable turns in transcript")
    if state["started"] is None:
        st = tpath.stat()
        born = getattr(st, "st_birthtime", st.st_mtime)
        state["started"] = datetime.fromtimestamp(born).astimezone().isoformat(timespec="seconds")

    def advance():
        state["offset_lines"] = total
        _save_state(root, sid, state)

    if is_trivial(turns):
        advance()
        return "skipped"

    sid8 = sid[:8]
    prev_id = f"{sid8}-{state['seq']}" if state["seq"] else None
    prev_summary = None
    if prev_id and (root / "handoffs" / f"{prev_id}.md").exists():
        prev_summary = parse_note((root / "handoffs" / f"{prev_id}.md").read_text()).summary

    prompt = build_prompt(condense(turns, CONDENSE_BUDGET), _memory_index(config_dir), prev_summary, state["note_summaries"])
    result = call_claude(prompt, config_dir, timeout=timeout, cwd=root)
    if not result["worth_keeping"]:
        advance()
        return "skipped"

    created = now_iso()
    origin = {"session_id": sid, "cwd": item.get("cwd"), "git_branch": item.get("git_branch"),
              "started": state["started"], "ended": item.get("ended")}
    seq = state["seq"] + 1
    h = result["handoff"]
    handoff = Note(id=f"{sid8}-{seq}", kind="handoff", summary=_clean(h["summary"]),
                   surface_when=_clean(h["surface_when"]), body=_clean(h["body"]), created=created,
                   origin=origin, seq=seq,
                   expires=(date.fromisoformat(created[:10]) + timedelta(days=HANDOFF_TTL_DAYS)).isoformat(),
                   links=[prev_id] if prev_id else [])
    notes = [Note(id=f"{n['kind']}-{slugify(_clean(n['summary']))}", kind=n["kind"], summary=_clean(n["summary"]),
                  surface_when=_clean(n["surface_when"]), body=_clean(n["body"]), created=created,
                  origin=dict(origin), source="worker", links=[handoff.id])
             for n in result["notes"]]

    write_note(root, handoff)
    for n in notes:
        _unique_id(root, n)
        write_note(root, n)
    state["seq"] = seq
    state["note_summaries"] += [n.summary for n in notes]
    advance()
    return "written"


# --- sweep ------------------------------------------------------------------------
def _transcript_cwd(path: Path) -> str | None:
    """Best-effort working directory from the transcript (the field is undocumented)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for _, line in zip(range(50), f):
                try:
                    cwd = json.loads(line).get("cwd")
                except (ValueError, AttributeError):
                    continue
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        pass
    return None


def sweep(root: Path, config_dir: Path, now: float) -> int:
    """Queue transcripts whose session ended without a SessionEnd hook (crash, kill -9).

    Only transcripts modified after sweep.since (created on the first run) and idle
    for SWEEP_IDLE_HOURS are considered, so the first run never backfills history.
    """
    marker = root / "sweep.since"
    if not marker.exists():
        marker.write_text("")
        return 0
    since = marker.stat().st_mtime
    idle_before = now - SWEEP_IDLE_HOURS * 3600
    queued = 0
    for t in config_dir.glob("projects/*/*.jsonl"):
        sid = t.stem
        try:
            mtime = t.stat().st_mtime
        except OSError:
            continue
        if not since <= mtime <= idle_before:
            continue
        if (root / "queue" / f"{sid}.json").exists() or (root / "queue" / "failed" / f"{sid}.json").exists():
            continue
        state = root / "state" / f"{sid}.json"
        if state.exists():
            try:
                with open(t, "rb") as f:
                    lines = sum(1 for _ in f)
                if json.loads(state.read_text()).get("offset_lines", 0) >= lines:
                    continue
            except (OSError, ValueError):
                continue
        item = {"session_id": sid, "transcript_path": str(t), "cwd": _transcript_cwd(t),
                "git_branch": None, "reason": "swept", "attempts": 0,
                "ended": datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds")}
        (root / "queue" / f"{sid}.json").write_text(json.dumps(item))
        _log(root, sid, "swept")
        queued += 1
    return queued


# --- entry points -----------------------------------------------------------------
def run(root: Path, config_dir: Path, timeout: int = 180) -> dict:
    lock = open(root / "worker.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return {"locked": True}
    counts = {"swept": 0, "processed": 0, "written": 0, "skipped": 0, "failed": 0, "expired": 0}
    try:
        counts["swept"] = sweep(root, config_dir, time.time())
        for qfile in sorted((root / "queue").glob("*.json")):
            sid, item = qfile.stem, {}
            counts["processed"] += 1
            try:
                item = json.loads(qfile.read_text())
                if not isinstance(item, dict):
                    raise _Permanent("queue item is not an object")
                sid = item.get("session_id", sid)
                outcome = _process(root, config_dir, item, timeout)
            except Exception as e:  # noqa: BLE001 — one bad item must not block the queue
                counts["failed"] += 1
                retryable = isinstance(e, (SummariseError, OSError)) and not isinstance(e, _Permanent)
                item["attempts"] = item.get("attempts", 0) + 1
                item["error"] = scrub(repr(e) if not retryable else str(e))
                if not retryable or item["attempts"] >= MAX_ATTEMPTS:
                    (root / "queue" / "failed" / qfile.name).write_text(json.dumps(item))
                    qfile.unlink()
                else:
                    qfile.write_text(json.dumps(item))
                _log(root, sid, "failed", item["error"])
                continue
            counts[outcome] += 1
            qfile.unlink()
            _log(root, sid, outcome)
        if counts["written"]:
            rebuild_index(root)
        counts["expired"] = expire(root, date.today())
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return counts


def retry_failed(root: Path) -> int:
    """Move failed items back into the queue with a fresh attempt count."""
    moved = 0
    for f in (root / "queue" / "failed").glob("*.json"):
        try:
            item = json.loads(f.read_text())
        except ValueError:
            continue
        item["attempts"] = 0
        item.pop("error", None)
        (root / "queue" / f.name).write_text(json.dumps(item))
        f.unlink()
        moved += 1
    return moved


def expire(root: Path, today: date) -> int:
    reads_log = root / "log" / "reads.jsonl"
    read_ids = set()
    if reads_log.exists():
        for line in reads_log.read_text().splitlines():
            try:
                read_ids.add(json.loads(line)["id"])
            except (ValueError, KeyError):
                pass
    cutoff = (today - timedelta(days=WORKER_NOTE_TTL_DAYS)).isoformat()
    removed = 0
    for n in load_all(root):
        stale_handoff = n.kind == "handoff" and n.expires and n.expires < today.isoformat()
        stale_worker = n.source == "worker" and n.created[:10] < cutoff and n.id not in read_ids
        if stale_handoff or stale_worker:
            note_path(root, n).unlink(missing_ok=True)
            removed += 1
    if removed:
        rebuild_index(root)
    return removed
