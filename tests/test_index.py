from claude_memory.index import HINT_MIN_TERMS, fts_query, search
from claude_memory.indexer import rebuild_index
from claude_memory.notes import Note, write_note
from claude_memory.paths import memory_root


def add(root, id, surface_when="", body="", summary="s", kind="lesson", cwd="/elsewhere",
        created="2026-10-22T10:00:00+02:00"):
    write_note(root, Note(id=id, kind=kind, summary=summary, surface_when=surface_when, body=body,
                          created=created, origin={"session_id": "s", "cwd": cwd}))


def test_surface_when_outranks_body(root):
    add(root, "A", surface_when="bøtte, HÅLLBAR")
    add(root, "B", body="noe om bøtte her og der")
    rebuild_index(root)
    assert search(root, "bøtta passer ikke bøtte")[0].id == "A"


def test_norwegian_diacritics_match(root):
    add(root, "A", surface_when="bøtte")
    rebuild_index(root)
    assert [h.id for h in search(root, "botte")] == ["A"]


def test_cwd_boost_reorders(root):
    add(root, "other-note", surface_when="coupling seal", cwd="/p/Other")
    add(root, "kestrel-note", surface_when="coupling seal", cwd="/p/Kestrel")
    rebuild_index(root)
    assert search(root, "coupling", cwd="/p/Kestrel/sub")[0].id == "kestrel-note"


def test_fts_syntax_is_safe(root):
    add(root, "A", surface_when="x")
    rebuild_index(root)
    for q in ['"', 'a*b', 'NEAR(x y)', 'col:val', '-(', '🙂🙂', 'og i på', "", "AND OR NOT"]:
        search(root, q)


def test_stopwords_only_returns_empty(root):
    add(root, "A", body="og i på the and")
    rebuild_index(root)
    assert search(root, "og i på the and") == []
    assert fts_query("og i på the and") is None


def test_missing_index_returns_empty(tmp_path):
    assert search(tmp_path, "anything") == []


def test_corrupt_index_returns_empty(root):
    (root / "index.sqlite").write_bytes(b"not a database")
    assert search(root, "anything") == []


def test_kind_filter(root):
    add(root, "L", surface_when="xylofon", kind="lesson")
    add(root, "Q", surface_when="xylofon", kind="question")
    rebuild_index(root)
    assert {h.kind for h in search(root, "xylofon", kind="lesson")} == {"lesson"}


def test_strong_match_clears_gate(root):
    add(root, "lesson-oring", surface_when="kestrel, O-ring, hul ring, hollow, trykksikring",
        summary="Hollow O-ring in the Kestrel coupling is intentional")
    for i in range(20):
        add(root, f"filler-{i}", surface_when=f"filler topic {i}", body="weather today was fine")
    rebuild_index(root)
    hits = search(root, "hollow O-ring kestrel")
    assert hits[0].id == "lesson-oring" and hits[0].strength >= HINT_MIN_TERMS


def test_gate_works_with_tiny_corpus(root):
    add(root, "only", surface_when="kestrel, O-ring, hollow", summary="Hollow O-ring")
    rebuild_index(root)
    assert search(root, "is the hollow kestrel ring ok")[0].strength >= HINT_MIN_TERMS


def test_body_only_words_do_not_count(root):
    add(root, "lesson-oring", surface_when="kestrel, O-ring", body="the weather was nice when we tested today")
    rebuild_index(root)
    assert all(h.strength < HINT_MIN_TERMS for h in search(root, "what's the weather today"))


def test_single_shared_word_does_not_clear_gate(root):
    add(root, "A", surface_when="kestrel, coupling")
    rebuild_index(root)
    assert search(root, "kestrel")[0].strength == 1 < HINT_MIN_TERMS


def test_part_of_a_phrase_does_not_count(root):
    add(root, "rive", surface_when="xcode cloud, damaged app, zip", summary="Xcode Cloud build for the app")
    rebuild_index(root)
    hit = search(root, "build the app and fix the failing test in xcode")[0]
    assert hit.strength == 0 and hit.matched == ()


def test_whole_phrase_counts_each_term(root):
    add(root, "rive", surface_when="xcode cloud, damaged app, zip")
    rebuild_index(root)
    hit = search(root, "the Xcode Cloud workflow fails")[0]
    assert hit.matched == ("cloud", "xcode") and hit.strength >= HINT_MIN_TERMS


def test_summary_words_do_not_count(root):
    add(root, "A", surface_when="riveviewer", summary="Notarized build failed to open for friends")
    rebuild_index(root)
    assert search(root, "notarized build failed")[0].strength == 0


def test_profiles_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "a"))
    a = memory_root()
    add(a, "A", surface_when="kestrel")
    rebuild_index(a)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "b"))
    b = memory_root()
    rebuild_index(b)
    assert search(b, "kestrel") == []


def test_rebuild_is_atomic_and_counts(root):
    add(root, "A", surface_when="x")
    assert rebuild_index(root) == 1
    assert not (root / "index.sqlite.tmp").exists()


def test_hit_fields(root):
    add(root, "A", surface_when="zebra", summary="Zebra note", cwd="/z")
    rebuild_index(root)
    h = search(root, "zebra")[0]
    assert (h.id, h.kind, h.summary, h.date, h.cwd, h.strength, h.matched) == \
        ("A", "lesson", "Zebra note", "2026-10-22", "/z", 1, ("zebra",))


def test_rebuild_leaves_other_tmp_files_alone(root):
    other = root / "index.sqlite.tmp"
    other.write_text("another process is building this")
    add(root, "A", surface_when="x")
    rebuild_index(root)
    assert other.read_text() == "another process is building this"


def test_rebuild_waits_for_index_lock(root):
    import fcntl
    import threading
    add(root, "A", surface_when="x")
    done = threading.Event()
    with open(root / "index.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        t = threading.Thread(target=lambda: (rebuild_index(root), done.set()))
        t.start()
        assert not done.wait(0.3)
    t.join(2)
    assert done.is_set()
