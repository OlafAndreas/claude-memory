"""Rebuild index.sqlite from the Markdown notes (always derivable, never edited in place)."""
from __future__ import annotations

import fcntl
import os
import sqlite3
import tempfile
from pathlib import Path

from .index import fold
from .notes import load_all

SCHEMA = """
CREATE TABLE notes(id TEXT PRIMARY KEY, kind TEXT, summary TEXT, surface_when TEXT,
                   body TEXT, created TEXT, cwd TEXT, source TEXT);
CREATE VIRTUAL TABLE notes_fts USING fts5(id UNINDEXED, surface_when, summary, body,
                                          tokenize="unicode61 remove_diacritics 2");
"""


def rebuild_index(root: Path) -> int:
    # The worker and any number of MCP servers rebuild; index.lock serialises them so
    # each build sees every note written before it and swaps in a complete file.
    with open(root / "index.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        notes = load_all(root)
        fd, name = tempfile.mkstemp(dir=root, prefix="index.", suffix=".sqlite.tmp")
        os.close(fd)
        tmp = Path(name)
        try:
            db = sqlite3.connect(tmp)
            try:
                db.executescript(SCHEMA)
                for n in notes:
                    cwd = (n.origin or {}).get("cwd") or ""
                    db.execute("INSERT INTO notes VALUES (?,?,?,?,?,?,?,?)",
                               (n.id, n.kind, n.summary, n.surface_when, n.body, n.created, cwd, n.source))
                    db.execute("INSERT INTO notes_fts VALUES (?,?,?,?)",
                               (n.id, fold(n.surface_when), fold(n.summary), fold(n.body)))
                db.commit()
            finally:
                db.close()
            os.replace(tmp, root / "index.sqlite")
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    return len(notes)
