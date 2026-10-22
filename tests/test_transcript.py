from pathlib import Path

import pytest

from claude_memory.transcript import Turn, condense, is_trivial, read_turns

FIX = Path(__file__).parent / "fixtures" / "transcript_sample.jsonl"
EXPECTED = [
    Turn("user", "Can you check the bucket frame dimensions?"),
    Turn("assistant", "Sure, let me look."),
    Turn("assistant", "The opening is assumed to be 247×196."),
    Turn("user", "It was 250 wide in reality."),
    Turn("assistant", "Noted — 250, not 247."),
]


def test_reads_text_only_from_fixture():
    turns, _ = read_turns(FIX)
    assert turns == EXPECTED
    joined = " ".join(t.text for t in turns)
    for leak in ("TOOL OUTPUT", "secret thoughts", "internal note", "DUPLICATE BLOB", "FUTURE",
                 "Skill body", "Sidechain"):
        assert leak not in joined


def test_total_lines_returned():
    assert read_turns(FIX)[1] == 13


def test_start_line_offset_returns_only_new_turns():
    turns, total = read_turns(FIX, start_line=11)
    assert turns == EXPECTED[3:] and total == 13


def test_condense_under_budget_unchanged():
    assert condense(EXPECTED) == ("USER: Can you check the bucket frame dimensions?\n\n"
                                  "CLAUDE: Sure, let me look.\n\n"
                                  "CLAUDE: The opening is assumed to be 247×196.\n\n"
                                  "USER: It was 250 wide in reality.\n\n"
                                  "CLAUDE: Noted — 250, not 247.")


def test_condense_large_keeps_head_and_tail():
    turns = [Turn("user" if i % 2 == 0 else "assistant", f"T{i:03d} " + "x" * 1000) for i in range(200)]
    out = condense(turns)
    assert len(out) <= 60_000 and "T000" in out and "T199" in out and "omitted" in out


def test_condense_single_huge_turn_is_bounded():
    out = condense([Turn("user", "y" * 200_000)])
    assert len(out) <= 60_000


def test_trivial_detection():
    assert is_trivial(EXPECTED[:3])
    assert not is_trivial([Turn("user", "q")] * 3)
    assert not is_trivial([Turn("user", "z" * 3000)])


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_turns(tmp_path / "nope.jsonl")
