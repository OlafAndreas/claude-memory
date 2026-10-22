# claude-memory

Memory that connects Claude Code sessions, kept by Claude for itself.

- **Handoffs** — after a session with substance, a short first-person note to the next session
  (what we did, what's unresolved, what I got wrong). Expire after 30 days.
- **Notes** — lasting lessons, outcomes and open questions. Saved with the `remember` tool, or
  extracted from handoffs (those expire after 90 days unless a later session reads them).
- Nothing is loaded at startup beyond one line. Each prompt is matched against the index and up
  to three one-line hints are injected when a note clearly fits; full notes are read on demand.
- Sessions that end without the end hook (crash, `kill -9`) are picked up by the worker once their
  transcript has been idle for 2 hours.

Facts about Olaf and his projects stay in the existing `MEMORY.md` auto-memory. Design:
`docs/superpowers/specs/2026-10-22-claude-memory-design.md`.

## Install

One profile at a time; each profile gets its own separate store.

```bash
./install.sh                                # personal: ~/.claude
./install.sh --config-dir ~/.claude-work  # work
```

This appends three hooks to `<config>/settings.json` (a backup is written first, existing hooks are
kept), registers the `claude-memory` MCP server at user scope, and loads a launchd agent that runs
the worker every 10 minutes.

## Where things live

`<config>/claude-memory/` — `handoffs/` and `notes/` (Markdown, the source of truth), `index.sqlite`
(derived), `queue/`, `state/`, `log/`.

## Commands

```bash
.venv/bin/python cli.py [--config-dir DIR] stats       # hints shown vs read, queue, counts
.venv/bin/python cli.py [--config-dir DIR] doctor      # is everything installed?
.venv/bin/python cli.py [--config-dir DIR] run-worker    # process the queue now
.venv/bin/python cli.py [--config-dir DIR] retry-failed  # requeue failed items (e.g. after an outage)
.venv/bin/python cli.py [--config-dir DIR] reindex
.venv/bin/pytest
```
