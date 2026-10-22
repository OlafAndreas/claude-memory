"""
Locations of the memory store.

The store lives inside the active Claude Code config dir, so each profile
(~/.claude, ~/.claude-work, ...) has its own memory and nothing crosses.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

SUBDIRS = ("handoffs", "notes", "queue", "queue/failed", "state", "log", "log/hinted")


def config_dir() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def memory_root(config_dir: Path | None = None) -> Path:
    root = (config_dir or _active_config_dir()) / "claude-memory"
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


_active_config_dir = config_dir


def git_branch(cwd: str) -> str | None:
    """Current branch for `cwd`, or None outside git / on detached HEAD / on error."""
    try:
        r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"],
                           capture_output=True, text=True, timeout=0.3)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
