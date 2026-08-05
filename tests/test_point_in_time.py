from src.point_in_time import FundamentalSnapshot, PointInTimeStore, audit_no_lookahead


def _snapshot(published: str) -> FundamentalSnapshot:
    fetched = "2026-03-05T00:00:00+00:00" if published.startswith("2026-02") else "2026-01-05T00:00:00+00:00"
    return FundamentalSnapshot("2330", "eps", 10.0, "2025-12-31", published, fetched, "MOPS", "https://mops.twse.com.tw")


def test_store_excludes_future_filing():
    store = PointInTimeStore()
    store.append(_snapshot("2026-01-04T00:00:00+00:00"))
    store.append(_snapshot("2026-02-04T00:00:00+00:00"))
    rows = store.available_as_of("2330", "2026-01-10T00:00:00+00:00")
    assert len(rows) == 1
    assert rows[0].published_at.startswith("2026-01-04")
    store.close()


def test_audit_reports_lookahead():
    assert audit_no_lookahead([_snapshot("2026-02-04T00:00:00+00:00")], "2026-01-10T00:00:00+00:00")
