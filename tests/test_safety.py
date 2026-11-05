"""The project is read-only: no code may send anything but GET requests, or touch credentials.

This scans the source text, so it also catches code paths no other test runs.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted([*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")])

FORBIDDEN = {
    "HTTP method other than GET": re.compile(r"\.(post|put|patch|delete|request)\(", re.I),
    "login header": re.compile(r"authorization|bearer", re.I),
    "credential": re.compile(r"api[_-]?key|private[_-]?key|secret|password|token\b", re.I),
    "environment variable": re.compile(r"os\.environ|getenv", re.I),
    "order endpoint": re.compile(r"/portfolio|/orders", re.I),
}


def test_there_is_source_to_scan():
    assert any(p.name == "kalshi.py" for p in SOURCES)


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_source_is_read_only(path):
    text = path.read_text(encoding="utf-8")
    for what, pattern in FORBIDDEN.items():
        match = pattern.search(text)
        assert match is None, f"{path.name}: {what} ({match.group(0)!r})"
