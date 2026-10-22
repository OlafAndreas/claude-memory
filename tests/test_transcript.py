from pathlib import Path

import pytest

from claude_memory.transcript import Turn, condense, is_trivial, read_turns

FIX = Path(__file__).parent / "fixtures" / "transcript_sample.jsonl"
EXPECTED = [
    Turn("user", "Can you check the bucket frame dimensions?"),
    Turn("assistant", "Sure, let me look."),
    Turn("assistant", "[ran Read: /x]"),
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
    assert turns == EXPECTED[4:] and total == 13


def test_condense_under_budget_unchanged():
    assert condense(EXPECTED) == ("USER: Can you check the bucket frame dimensions?\n\n"
                                  "CLAUDE: Sure, let me look.\n\n"
                                  "CLAUDE: [ran Read: /x]\n\n"
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
    assert is_trivial(EXPECTED[:4])
    assert not is_trivial([Turn("user", "q")] * 3)
    assert not is_trivial([Turn("user", "z" * 3000)])


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_turns(tmp_path / "nope.jsonl")


def test_tool_calls_become_short_action_lines(tmp_path):
    import json
    p = tmp_path / "t.jsonl"
    cmd = "gh api -X PUT repos/o/r/actions/permissions/workflow -F can_approve_pull_request_reviews=true " + "z" * 500
    p.write_text("\n".join(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [c]}}) for c in [
        {"type": "tool_use", "name": "Bash", "input": {"command": cmd, "description": "d"}},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "/a/b.py", "old_string": "x", "new_string": "y"}},
        {"type": "tool_use", "name": "mcp__jotta__jotta_browse", "input": {"path": "/Photos"}},
    ]) + "\n")
    turns, _ = read_turns(p)
    assert turns[0].text.startswith("[ran Bash: gh api -X PUT repos/o/r") and len(turns[0].text) <= 220
    assert turns[1].text == "[ran Edit: /a/b.py]"
    assert turns[2].text == '[ran mcp__jotta__jotta_browse: {"path": "/Photos"}]'
