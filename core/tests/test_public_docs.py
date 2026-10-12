"""The judge-facing front page must not ship unfinished: no TODO/FIXME/TBD markers in README.md
or NOTICE (review-04 §2 #3). Internal logs and code comments are not checked."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MARKER = re.compile(r"\b(TODO|FIXME|TBD|XXX)\b")


@pytest.mark.parametrize("name", ["README.md", "NOTICE"])
def test_no_unfinished_markers(name):
    hits = [f"{name}:{n}: {line.strip()}"
            for n, line in enumerate((ROOT / name).read_text().splitlines(), 1)
            if MARKER.search(line)]
    assert not hits, "unfinished markers on a public page:\n" + "\n".join(hits)
