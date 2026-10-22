#!/usr/bin/env python3
"""
claude-memory command line: reindex, run the worker, show stats, check the install.

Run:  ./.venv/bin/python cli.py [--config-dir DIR] {reindex|run-worker|retry-failed|stats|doctor}
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def cmd_reindex(root: Path, cfg: Path) -> int:
    from claude_memory.indexer import rebuild_index
    print(f"indexed {rebuild_index(root)} notes")
    return 0


def cmd_run_worker(root: Path, cfg: Path) -> int:
    from claude_memory.worker import run
    print(json.dumps(run(root, cfg)))
    return 0


def cmd_retry_failed(root: Path, cfg: Path) -> int:
    from claude_memory.worker import retry_failed
    print(f"requeued {retry_failed(root)}")
    return 0


def cmd_stats(root: Path, cfg: Path) -> int:
    hints = _jsonl(root / "log" / "hints.jsonl")
    reads = {(r.get("session_id"), r.get("id")) for r in _jsonl(root / "log" / "reads.jsonl")}
    shown = [(h.get("session_id"), i) for h in hints for i in h.get("ids", [])]
    followed = sum(1 for pair in shown if pair in reads)
    print(f"hints shown: {len(shown)} ({len({i for _, i in shown})} distinct notes)")
    print(f"reads: {len(reads)}")
    print(f"hinted then read: {followed}/{len(shown)}")
    print(f"queue: {len(list((root / 'queue').glob('*.json')))}, "
          f"failed: {len(list((root / 'queue' / 'failed').glob('*.json')))}")
    print(f"handoffs: {len(list((root / 'handoffs').glob('*.md')))}, "
          f"notes: {len(list((root / 'notes').glob('*.md')))}")
    return 0


def cmd_doctor(root: Path, cfg: Path) -> int:
    from claude_memory.install_hooks import HOOKS, launchd_label
    ok = True

    def check(name: str, passed: bool) -> None:
        nonlocal ok
        ok &= passed
        print(f"{'OK     ' if passed else 'MISSING'} {name}")

    settings = cfg / "settings.json"
    text = settings.read_text() if settings.exists() else ""
    for event, script, _ in HOOKS:
        check(f"{event} hook ({settings})", f"{REPO}/hooks/{script}" in text)
    from claude_memory.paths import profile_env
    env = profile_env(cfg)
    try:
        mcp = subprocess.run(["claude", "mcp", "list"], capture_output=True, text=True, env=env, timeout=60)
        check("MCP server claude-memory registered", "claude-memory" in mcp.stdout)
    except (OSError, subprocess.SubprocessError):
        check("MCP server claude-memory registered", False)
    label = launchd_label(cfg)
    check(f"launchd agent {label}",
          subprocess.run(["launchctl", "list", label], capture_output=True).returncode == 0)
    check("venv", (REPO / ".venv" / "bin" / "python").exists())
    check(f"index ({root / 'index.sqlite'})", (root / "index.sqlite").exists())
    return 0 if ok else 1


COMMANDS = {"reindex": cmd_reindex, "run-worker": cmd_run_worker, "retry-failed": cmd_retry_failed,
            "stats": cmd_stats, "doctor": cmd_doctor}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--config-dir", help="Claude Code config dir (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    ap.add_argument("command", choices=COMMANDS)
    args = ap.parse_args()
    if args.config_dir:
        os.environ["CLAUDE_CONFIG_DIR"] = str(Path(args.config_dir).expanduser())
    from claude_memory.paths import config_dir, memory_root
    cfg = config_dir()
    return COMMANDS[args.command](memory_root(cfg), cfg)


if __name__ == "__main__":
    sys.exit(main())
