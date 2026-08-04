from src.lookahead_audit import audit_signal_rows


def test_rejects_entry_on_signal_close():
    result = audit_signal_rows([{"ticker": "A", "signal_date": "2026-01-01", "entry_date": "2026-01-01"}])
    assert result["status"] == "failed"


def test_accepts_next_day_with_historical_inputs():
    result = audit_signal_rows([{"ticker": "A", "signal_date": "2026-01-01", "entry_date": "2026-01-02",
                                 "fundamental_published_at": "2025-12-31", "membership_as_of": "2025-12-31", "price_as_of": "2026-01-01"}])
    assert result["status"] == "pass"
