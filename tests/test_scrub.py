import pytest

from claude_memory.scrub import scrub

CASES = [
    ("key sk-ant-api03-AbCdEf0123456789xyz", "sk-ant-api03"),
    ("ctx7sk-0a1b2c3d-0000-4000-8000-123456789abc", "0a1b2c3d"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123_-", "eyJhbGci"),
    ("ghp_0123456789abcdefABCDEF0123456789abcd", "ghp_0123"),
    ("fnr 01019912345", "01019912345"),
    ("password: hunter2", "hunter2"),
    ("passord=Sommer2026!", "Sommer2026"),
    ("Bearer abc.def.ghi123", "abc.def"),
]


@pytest.mark.parametrize("text,secret", CASES)
def test_scrubs(text, secret):
    out = scrub(text)
    assert "[redacted]" in out
    assert secret not in out


def test_password_key_kept():
    assert scrub("password: hunter2").startswith("password")


def test_leaves_normal_text():
    assert scrub("målt 247×196 mm, 1000 bar") == "målt 247×196 mm, 1000 bar"


def test_does_not_eat_long_numbers_with_separators():
    assert scrub("ordre 2026-10-22 12345") == "ordre 2026-10-22 12345"


@pytest.mark.parametrize("text,secret", [
    ("aws AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
    ("slack xoxb-123456789012-abcdefghijkl", "xoxb-1234"),
    ("api_key=abc123def456", "abc123def456"),
    ("token: abcdef123456789", "abcdef123456789"),
    ("secret=s3cr3tvalue", "s3cr3tvalue"),
])
def test_scrubs_more_patterns(text, secret):
    assert secret not in scrub(text)
