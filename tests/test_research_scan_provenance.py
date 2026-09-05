import pandas as pd
import pytest

from src.research_scan_provenance import (
    quote_cutoff_from_frame,
    quote_cutoff_from_records,
    scan_trading_date,
)


def test_scan_date_comes_from_explicit_target_or_stable_slot(monkeypatch):
    monkeypatch.setenv("RESEARCH_SLOT_KEY", "taiwan:2026-09-04:close-research,us:2026-09-04:close-research")
    assert scan_trading_date("taiwan") == "2026-09-04"
    assert scan_trading_date("us", "2026-09-05") == "2026-09-05"


def test_invalid_explicit_scan_date_is_rejected():
    with pytest.raises(ValueError, match="invalid scan trading date"):
        scan_trading_date("taiwan", "not-a-date")


def test_quote_cutoff_comes_from_downloaded_bar_evidence():
    frame = pd.DataFrame({"Close": [1, 2]}, index=pd.to_datetime(["2026-09-03", "2026-09-04"]))
    assert quote_cutoff_from_frame(frame) == "2026-09-04"
    assert quote_cutoff_from_records([{"bars": frame}]) == "2026-09-04"


def test_empty_quote_evidence_does_not_fallback_to_slot_date():
    assert quote_cutoff_from_frame(pd.DataFrame()) is None
    assert quote_cutoff_from_records([]) is None
