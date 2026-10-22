"""
Note format: Markdown with YAML frontmatter.

Files on disk are the source of truth; index.sqlite is derived from them.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .paths import now_iso

KINDS = ("handoff", "lesson", "outcome", "question")
_FIELD_ORDER = ("id", "kind", "source", "seq", "summary", "surface_when",
                "created", "expires", "origin", "links")


@dataclass
class Note:
    id: str
    kind: str
    summary: str
    surface_when: str
    body: str
    created: str
    origin: dict
    source: str | None = None
    seq: int | None = None
    expires: str | None = None
    links: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown kind {self.kind!r}, expected one of {KINDS}")


# --- serialisation ------------------------------------------------------------
def render_note(n: Note) -> str:
    data = asdict(n)
    front = {k: data[k] for k in _FIELD_ORDER if data[k] is not None and data[k] != []}
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1000)
    return f"---\n{head}---\n{n.body}\n"


def parse_note(text: str) -> Note:
    m = re.match(r"---\n(.*?)\n---\n(.*)\Z", text, re.S)
    if not m:
        raise ValueError("missing frontmatter")
    front = yaml.safe_load(m.group(1))
    if not isinstance(front, dict):
        raise ValueError("frontmatter is not a mapping")
    body = m.group(2)
    if body.endswith("\n"):
        body = body[:-1]
    front["created"] = str(front["created"])
    if front.get("expires") is not None:
        front["expires"] = str(front["expires"])
    return Note(body=body, **front)


# --- files ----------------------------------------------------------------------
def note_path(root: Path, n: Note) -> Path:
    return root / ("handoffs" if n.kind == "handoff" else "notes") / f"{n.id}.md"


def write_note(root: Path, n: Note) -> Path:
    path = note_path(root, n)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(render_note(n), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_all(root: Path) -> list[Note]:
    out = []
    for path in sorted([*(root / "handoffs").glob("*.md"), *(root / "notes").glob("*.md")]):
        try:
            out.append(parse_note(path.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001 — one bad file must not hide the rest
            with open(root / "log" / "worker.log", "a", encoding="utf-8") as log:
                log.write(f"{now_iso()} - skip-unparsable {path.name} {e}\n")
    return out


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = text.replace("ø", "o").replace("æ", "ae").replace("å", "a")
    text = "".join(c for c in text if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug[:max_len].rstrip("-") or "note"
