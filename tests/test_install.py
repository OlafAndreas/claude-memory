import json
import os
import subprocess
import sys
from pathlib import Path

from claude_memory.install_hooks import add_hooks, launchd_label

REPO = Path(__file__).resolve().parent.parent
EVENTS = ["Notification", "PermissionRequest", "PostToolUse", "PreToolUse", "SessionEnd", "SessionStart",
          "Stop", "StopFailure", "SubagentStop", "UserPromptSubmit"]
CC = {"hooks": [{"type": "command", "command": "/Users/x/.config/iterm2/cc-status"}]}


def existing(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"model": "opus", "hooks": {e: [CC] for e in EVENTS}}, indent=2))
    return p


def test_add_hooks_preserves_existing(tmp_path):
    p = existing(tmp_path)
    assert add_hooks(p, "/venv/python", Path("/repo")) is True
    s = json.loads(p.read_text())
    assert s["model"] == "opus"
    for e in EVENTS:
        assert s["hooks"][e][0] == CC
    for event, script, timeout in [("SessionStart", "session_start.py", 10), ("SessionEnd", "session_end.py", 5),
                                   ("UserPromptSubmit", "prompt_hints.py", 5)]:
        assert s["hooks"][event][1] == {"hooks": [{"type": "command",
                                                   "command": f"/venv/python /repo/hooks/{script}",
                                                   "timeout": timeout}]}
    assert len(s["hooks"]["Stop"]) == 1


def test_add_hooks_idempotent(tmp_path):
    p = existing(tmp_path)
    add_hooks(p, "/venv/python", Path("/repo"))
    before = p.read_bytes()
    assert add_hooks(p, "/venv/python", Path("/repo")) is False
    assert p.read_bytes() == before


def test_add_hooks_backup_written(tmp_path):
    p = existing(tmp_path)
    original = p.read_text()
    add_hooks(p, "/venv/python", Path("/repo"))
    backups = list(tmp_path.glob("settings.json.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == original


def test_add_hooks_missing_settings_creates_file(tmp_path):
    p = tmp_path / "settings.json"
    assert add_hooks(p, "/venv/python", Path("/repo")) is True
    assert set(json.loads(p.read_text())["hooks"]) == {"SessionStart", "SessionEnd", "UserPromptSubmit"}


def test_label_for_profiles():
    assert launchd_label(Path.home() / ".claude") == "no.olafandreas.claude-memory"
    assert launchd_label(Path.home() / ".claude-work") == "no.olafandreas.claude-memory.work"


def test_cli_reindex_and_stats_run(tmp_path):
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}
    r = subprocess.run([sys.executable, str(REPO / "cli.py"), "reindex"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "0 notes" in r.stdout
    root = tmp_path / "cfg" / "claude-memory"
    (root / "log" / "hints.jsonl").write_text(
        json.dumps({"ts": "t", "session_id": "s1", "cwd": "/", "ids": ["a", "b"]}) + "\n")
    (root / "log" / "reads.jsonl").write_text(json.dumps({"ts": "t", "session_id": "s1", "id": "a"}) + "\n")
    r = subprocess.run([sys.executable, str(REPO / "cli.py"), "--config-dir", str(tmp_path / "cfg"), "stats"],
                       capture_output=True, text=True, env={**os.environ, "CLAUDE_CONFIG_DIR": ""})
    assert r.returncode == 0
    assert "hints shown: 2" in r.stdout and "hinted then read: 1/2" in r.stdout


def test_add_hooks_quotes_paths_with_spaces(tmp_path):
    p = tmp_path / "settings.json"
    add_hooks(p, "/my venv/python", Path("/my repo"))
    cmd = json.loads(p.read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert cmd == "'/my venv/python' '/my repo/hooks/session_start.py'"


def test_add_hooks_keeps_symlink(tmp_path):
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text("{}")
    link = tmp_path / "settings.json"
    link.symlink_to(real)
    add_hooks(link, "/venv/python", Path("/repo"))
    assert link.is_symlink() and "SessionStart" in json.loads(real.read_text())["hooks"]


def test_cli_retry_failed(tmp_path):
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}
    root = tmp_path / "cfg" / "claude-memory"
    (root / "queue" / "failed").mkdir(parents=True)
    (root / "queue" / "failed" / "s1.json").write_text(json.dumps({"session_id": "s1", "attempts": 3}))
    r = subprocess.run([sys.executable, str(REPO / "cli.py"), "retry-failed"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "requeued 1" in r.stdout
