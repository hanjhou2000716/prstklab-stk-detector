import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

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


def test_master_artifact_is_content_addressed_and_schema_valid() -> None:
    master = InstrumentMaster()
    artifact = master.artifact()
    schema = json.loads((Path("schemas") / "instrument-master.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(artifact))
    assert errors == []
    assert artifact["registry_id"] == master.artifact()["registry_id"]
    assert len(artifact["instruments"]) == len(master.all())


def test_research_universe_extension_resolves_explicit_public_rows() -> None:
    master = InstrumentMaster().with_research_rows([
        {"ticker": "3037", "symbol": "3037.TW", "name": "欣興", "market": "taiwan"},
        {"ticker": "AAPL", "symbol": "AAPL", "name": "Apple Inc.", "market": "us"},
        {"ticker": "", "name": "missing", "market": "us"},
    ])
    assert master.resolve("3037", market="taiwan").instrument_id == "taiwan:equity:3037"
    assert master.resolve("AAPL", market="us").instrument_id == "us:equity:aapl"
    assert len(master.all()) == len(InstrumentMaster().all()) + 2
