"""
Search over index.sqlite.

Stdlib only: the prompt hook imports this on every user message, so it must
stay fast and must never import yaml or read the Markdown files.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

# Weights for (id, surface_when, summary, body) — surface_when is written to be found.
_BM25 = "bm25(notes_fts, 0, 10.0, 5.0, 1.0)"
_CWD_BOOST = 1.5
_RECENT_HANDOFF_BOOST = 1.2
_RECENT_DAYS = 7
_MAX_TOKENS = 24

# Hints need this many distinct prompt terms, counted only from surface_when phrases whose
# every term is in the prompt: "xcode cloud" needs both words, so "xcode" alone adds nothing.
# bm25 only orders results: its IDF is near zero while the store holds few notes.
HINT_MIN_TERMS = 2

_STOPWORDS = frozenset("""
the and for are but not you all any can had her was one our out has his how its may
new now old see two who did get got let put say she too use what when where which why
with this that from have will your they them then than there their about into just
like some would could should been were what's it's i'm don't
og for det som med til har var jeg ikke kan den men skal fra han hun vil seg sin
der eller når hva hvor hvorfor hvordan dette disse også bare mer meg deg oss dem
""".split())


class Hit(NamedTuple):
    id: str
    kind: str
    summary: str
    date: str
    cwd: str
    score: float
    strength: int
    matched: tuple[str, ...]


_FOLD = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae"})


def fold(text: str) -> str:
    """Fold letters FTS5's remove_diacritics leaves alone, so bøtte and botte match."""
    return text.lower().translate(_FOLD)


def terms(text: str) -> list[str]:
    seen: list[str] = []
    for tok in re.findall(r"\w+", fold(text)):
        if len(tok) >= 3 and tok not in _STOPWORDS and tok not in seen:
            seen.append(tok)
        if len(seen) >= _MAX_TOKENS:
            break
    return seen


def fts_query(text: str) -> str | None:
    return " OR ".join(f'"{t}"' for t in terms(text)) or None


def matched_terms(query_terms: set[str], surface_when: str) -> tuple[str, ...]:
    covered: set[str] = set()
    for phrase in surface_when.split(","):
        phrase_terms = set(terms(phrase))
        if phrase_terms and phrase_terms <= query_terms:
            covered |= phrase_terms
    return tuple(sorted(covered))


def _related(a: str, b: str) -> bool:
    if not a or not b:
        return False
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def search(root: Path, query: str, cwd: str | None = None, kind: str | None = None,
           limit: int = 5) -> list[Hit]:
    q = fts_query(query)
    query_terms = set(terms(query))
    db_path = Path(root) / "index.sqlite"
    if q is None or not db_path.exists():
        return []
    sql = (f"SELECT n.id, n.kind, n.summary, n.created, n.cwd, n.surface_when, -{_BM25} "
           "FROM notes_fts JOIN notes n ON n.id = notes_fts.id WHERE notes_fts MATCH ?")
    args: list = [q]
    if kind:
        sql += " AND n.kind = ?"
        args.append(kind)
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = db.execute(sql, args).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return []
    recent = (datetime.now() - timedelta(days=_RECENT_DAYS)).date().isoformat()
    hits = []
    for id_, kind_, summary, created, note_cwd, surface_when, score in rows:
        if cwd and _related(cwd, note_cwd):
            score *= _CWD_BOOST
        if kind_ == "handoff" and (created or "")[:10] >= recent:
            score *= _RECENT_HANDOFF_BOOST
        matched = matched_terms(query_terms, surface_when or "")
        hits.append(Hit(id_, kind_, summary, (created or "")[:10], note_cwd, score, len(matched), matched))
    hits.sort(key=lambda h: (h.strength, h.score), reverse=True)
    return hits[:limit]
