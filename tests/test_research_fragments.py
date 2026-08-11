import csv
import json

from src.research_fragments import merge_taiwan_scan_fragments


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "score"])
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(path, *, requested, complete, offset):
    path.write_text(json.dumps({
        "requested": requested,
        "data_complete": complete,
        "universe_expected": 2,
        "universe_scanned": complete,
        "universe_completed": complete,
        "universe_failed": 0,
        "failed": 0,
        "offset": offset,
        "scan_state": "complete",
    }), encoding="utf-8")


def test_merges_offset_fragments_and_aggregates_summary(tmp_path):
    _write_csv(tmp_path / "taiwan-momentum-scan-0.csv", [{"ticker": "2330", "score": "10"}])
    _write_csv(tmp_path / "taiwan-momentum-scan-1000.csv", [{"ticker": "2317", "score": "20"}])
    _write_summary(tmp_path / "taiwan-momentum-summary-0.json", requested=2, complete=1, offset=0)
    _write_summary(tmp_path / "taiwan-momentum-summary-1000.json", requested=2, complete=1, offset=1000)

    audit = merge_taiwan_scan_fragments(tmp_path)

    assert audit == [{"strategy": "momentum", "fragment_count": 2, "candidate_rows": 2}]
    rows = list(csv.DictReader((tmp_path / "taiwan-momentum-scan-0.csv").open(encoding="utf-8-sig")))
    assert [row["ticker"] for row in rows] == ["2317", "2330"]
    summary = json.loads((tmp_path / "taiwan-momentum-summary-0.json").read_text(encoding="utf-8"))
    assert summary["fragment_count"] == 2
    assert summary["universe_completed"] == 2
    assert summary["scan_state"] == "complete"


def test_does_not_rewrite_single_canonical_scan(tmp_path):
    _write_csv(tmp_path / "taiwan-resonance-scan-0.csv", [{"ticker": "2330", "score": "1"}])
    assert merge_taiwan_scan_fragments(tmp_path) == []
