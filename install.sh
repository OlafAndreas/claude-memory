#!/bin/bash
# Install claude-memory for one Claude Code profile.
#   ./install.sh                              # ~/.claude
#   ./install.sh --config-dir ~/.claude-work
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$HOME/.claude"
if [[ "${1:-}" == "--config-dir" ]]; then CONFIG_DIR="${2/#\~/$HOME}"; fi
CONFIG_DIR="$(cd "$CONFIG_DIR" && pwd)"
PY="$REPO/.venv/bin/python"

# The default profile runs claude with CLAUDE_CONFIG_DIR unset (it would otherwise
# look for ~/.claude/.claude.json instead of ~/.claude.json).
claude_profile() {
  if [[ "$CONFIG_DIR" == "$HOME/.claude" ]]; then env -u CLAUDE_CONFIG_DIR claude "$@"
  else CLAUDE_CONFIG_DIR="$CONFIG_DIR" claude "$@"; fi
}

# --- venv ---------------------------------------------------------------------
if [[ ! -x "$PY" ]]; then python3 -m venv "$REPO/.venv"; fi
"$PY" -m pip install -q -r "$REPO/requirements.txt"

# --- hooks ----------------------------------------------------------------------
echo "hooks: $("$PY" "$REPO/claude_memory/install_hooks.py" "$CONFIG_DIR/settings.json" "$PY" "$REPO")"

# --- MCP server -----------------------------------------------------------------
if claude_profile mcp list 2>/dev/null | grep -q '^claude-memory'; then
  echo "mcp: already registered"
else
  claude_profile mcp add --scope user --transport stdio claude-memory -- "$PY" "$REPO/mcp_server.py"
fi

# --- launchd --------------------------------------------------------------------
LABEL="$(cd "$REPO" && "$PY" -c "import sys; from pathlib import Path; from claude_memory.install_hooks import launchd_label; print(launchd_label(Path(sys.argv[1])))" "$CONFIG_DIR")"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
sed -e "s|@LABEL@|$LABEL|g" -e "s|@PYTHON@|$PY|g" -e "s|@REPO@|$REPO|g" \
    -e "s|@CONFIG_DIR@|$CONFIG_DIR|g" -e "s|@CLAUDE_BIN@|$(command -v claude)|g" \
    "$REPO/launchd/no.olafandreas.claude-memory.plist.template" > "$PLIST"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"
echo "launchd: $LABEL"

# --- index + check ----------------------------------------------------------------
"$PY" "$REPO/cli.py" --config-dir "$CONFIG_DIR" reindex
"$PY" "$REPO/cli.py" --config-dir "$CONFIG_DIR" doctor
