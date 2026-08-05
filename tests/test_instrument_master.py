from datetime import date

import pytest

from src.instrument_master import Instrument, InstrumentMaster


def test_master_resolves_alias_and_preserves_point_in_time_listing() -> None:
    master = InstrumentMaster()
    assert master.resolve("台積電", market="taiwan").instrument_id == "twse:2330"
    assert master.resolve("2330.TW").ticker == "2330"
    assert master.resolve("BTCUSDT").asset_type == "crypto"
    assert master.resolve("2330", as_of=date(2026, 8, 5)).active_on(date(2026, 8, 5))


def test_master_rejects_ambiguous_alias() -> None:
    first = Instrument("a", "A", "Alpha", "us", "equity", "USD", "UTC", aliases=("shared",))
    second = Instrument("b", "B", "Beta", "us", "equity", "USD", "UTC", aliases=("shared",))
    master = InstrumentMaster((first, second))
    assert any("ambiguous alias" in issue for issue in master.validate())
    with pytest.raises(ValueError, match="ambiguous instrument"):
        master.resolve("shared")


def test_master_round_trip(tmp_path) -> None:
    path = tmp_path / "instrument-master.json"
    master = InstrumentMaster()
    master.save(path)
    loaded = InstrumentMaster.load(path)
    assert loaded.resolve("^IXIC").instrument_id == "us:nasdaq"
