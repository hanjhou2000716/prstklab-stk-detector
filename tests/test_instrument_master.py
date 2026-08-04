from pathlib import Path

import pytest

from src.instrument_master import AmbiguousInstrument, Instrument, InstrumentError, InstrumentMaster


def make(**updates):
    value = {
        "ticker": "2330", "symbol": "2330.TW", "name": "TSMC", "market": "taiwan",
        "exchange": "TWSE", "currency": "TWD", "timezone": "Asia/Taipei", "calendar": "XTAI",
        "aliases": ["TSM"],
    }
    value.update(updates)
    return Instrument.from_mapping(value)


def test_normalizes_cik_and_resolves_aliases():
    master = InstrumentMaster([make(sec_cik="320193")])
    assert master.resolve("tsm").ticker == "2330"
    assert master.resolve("2330.TW", market="TAIWAN").instrument_id == "taiwan:TWSE:2330"
    assert master.resolve("TSM").sec_cik == "0000320193"


def test_alias_collision_is_rejected():
    master = InstrumentMaster([make()])
    with pytest.raises(AmbiguousInstrument):
        master.add(make(ticker="TSM", symbol="TSM", name="Other", aliases=["2330"]))


def test_date_and_required_fields_are_validated():
    with pytest.raises(InstrumentError):
        InstrumentMaster([make(listed_from="2026-08-04", listed_to="2026-08-03")])
    invalid = make()
    invalid = Instrument(**{**invalid.as_dict(), "aliases": tuple(invalid.aliases), "currency": ""})
    with pytest.raises(InstrumentError):
        InstrumentMaster([invalid])


def test_save_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "master.json"
    master = InstrumentMaster([make()])
    master.save(path)
    loaded = InstrumentMaster.load(path)
    assert len(loaded) == 1
    assert loaded.resolve("2330").name == "TSMC"
    assert loaded.as_dict()["schema_version"] == "1.0"


def test_unknown_resolution_is_explicit():
    master = InstrumentMaster([make()])
    with pytest.raises(InstrumentError, match="not found"):
        master.resolve("missing")