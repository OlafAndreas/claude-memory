<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="Assets/wordmark-dark.svg">
    <img src="Assets/wordmark.svg" alt="claude-memory" width="440">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/OlafAndreas/claude-memory/actions/workflows/ci.yml"><img src="https://github.com/OlafAndreas/claude-memory/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-B5524A.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/Python-3.12%2B-8E3B5E.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/platform-macOS-B5524A.svg" alt="macOS">
</p>

Memory that connects Claude Code sessions, kept by Claude for itself.

- **Handoffs** — after a session with substance, a short first-person note to the next session
  (what we did, what's unresolved, what I got wrong). Expire after 30 days.
- **Notes** — lasting lessons, outcomes and open questions. Saved with the `remember` tool, or
  extracted from handoffs (those expire after 90 days unless a later session reads them).
- Nothing is loaded at startup beyond one line. Each prompt is matched against the index and up
  to three one-line hints are injected when a note clearly fits; full notes are read on demand.
- Sessions that end without the end hook (crash, `kill -9`) are picked up by the worker once their
  transcript has been idle for 2 hours.

Facts about the user and their projects stay in Claude Code's own `MEMORY.md` auto-memory; this
store holds only Claude's side.

## How it works

- A `SessionEnd` hook queues the transcript. A launchd agent runs the worker every 10 minutes; it
  asks Haiku (`claude -p --model haiku`) for a handoff and up to three notes, scrubs secrets and
  national ID numbers, and writes them as Markdown.
- `index.sqlite` (SQLite FTS5) is derived from the Markdown and can always be rebuilt.
- A `UserPromptSubmit` hook matches each prompt against the notes' `surface_when` phrases. A hint
  needs at least two prompt terms, and a phrase only counts when every word of it is in the prompt.
- An MCP server offers `search_memory` and `read_memory`, plus `remember` and `forget`.

## Requirements

macOS (launchd), Python 3.12+ and Claude Code with the `claude` CLI on `PATH`.

## Install

One profile at a time; each profile gets its own separate store.

```bash
./install.sh                                # ~/.claude
./install.sh --config-dir ~/.claude-work    # a second profile
```

This appends three hooks to `<config>/settings.json` (a backup is written first, existing hooks are
kept), registers the `claude-memory` MCP server at user scope, and loads a launchd agent that runs
the worker every 10 minutes.

`surface_when` is written in Norwegian and English; change the language pair in
`claude_memory/summarise.py` and `mcp_server.py`.

## Where things live

`<config>/claude-memory/` — `handoffs/` and `notes/` (Markdown, the source of truth), `index.sqlite`
(derived), `queue/`, `state/`, `log/`.

## Commands

```bash
.venv/bin/python cli.py [--config-dir DIR] stats         # hints shown vs read, queue, counts
.venv/bin/python cli.py [--config-dir DIR] doctor        # is everything installed?
.venv/bin/python cli.py [--config-dir DIR] run-worker    # process the queue now
.venv/bin/python cli.py [--config-dir DIR] retry-failed  # requeue failed items (e.g. after an outage)
.venv/bin/python cli.py [--config-dir DIR] reindex
.venv/bin/pytest
```

## License

MIT. See [LICENSE](LICENSE).
