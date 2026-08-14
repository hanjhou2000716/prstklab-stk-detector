import re
from pathlib import Path

DOC = Path(__file__).parents[1] / "docs" / "p0-traceability-2026-08-15.md"
ALLOWED = {"PASS / LOCKED", "NEEDS_REVERIFY", "IN_PROGRESS", "FAIL", "BLOCKED"}


def _rows() -> list[list[str]]:
    lines = DOC.read_text(encoding="utf-8").splitlines()
    return [
        [part.strip() for part in line.strip().strip("|").split("|")]
        for line in lines
        if re.match(r"^\| P0-\d{2} ", line)
    ]


def test_all_p0_requirements_have_unique_traceability_rows():
    rows = _rows()
    assert len(rows) == 29
    numbers = [int(re.match(r"P0-(\d{2})", row[0]).group(1)) for row in rows]
    assert numbers == list(range(1, 30))
    assert len({row[1] for row in rows}) == 29


def test_each_row_has_dod_ids_evidence_and_allowed_status():
    for row in _rows():
        assert re.fullmatch(r"`?REQ-P0-\d{2}-DOD-01\.\.03`?", row[1])
        assert row[3] and row[4]
        assert row[5].strip("`") in ALLOWED
