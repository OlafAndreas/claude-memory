"""Register the claude-memory hooks in a Claude Code settings.json without touching other entries."""
from __future__ import annotations

import json
import os
import shlex
import shutil
from datetime import datetime
from pathlib import Path

HOOKS = (("SessionStart", "session_start.py", 10),
         ("SessionEnd", "session_end.py", 5),
         ("UserPromptSubmit", "prompt_hints.py", 5))


def add_hooks(settings_path: Path, python: str, repo: Path) -> bool:
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    hooks = settings.setdefault("hooks", {})
    changed = False
    for event, script, timeout in HOOKS:
        command = f"{shlex.quote(python)} {shlex.quote(f'{repo}/hooks/{script}')}"
        entries = hooks.setdefault(event, [])
        if any(h.get("command") == command for e in entries for h in e.get("hooks", [])):
            continue
        entries.append({"hooks": [{"type": "command", "command": command, "timeout": timeout}]})
        changed = True
    if not changed:
        return False
    if settings_path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(settings_path, settings_path.with_name(f"{settings_path.name}.bak-{stamp}"))
    # Replace the resolved target atomically, so a symlinked settings.json stays a symlink.
    target = settings_path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.claude-memory.tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, target)
    return True


def launchd_label(config_dir: Path) -> str:
    base = "no.olafandreas.claude-memory"
    name = Path(config_dir).name
    if name == ".claude":
        return base
    return f"{base}.{name.removeprefix('.claude-').lstrip('.')}"


if __name__ == "__main__":
    import sys
    print("changed" if add_hooks(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])) else "unchanged")
