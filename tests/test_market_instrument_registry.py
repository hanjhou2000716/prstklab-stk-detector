from src.artifact_contract import validate_market
from src.instrument_master import InstrumentMaster
from src.production_evidence import bind_market_evidence


def _market(rows: list[dict]) -> dict:
    return {
        "generated_at": "2026-08-11T01:00:00+00:00",
        "snapshot_id": "market-12345678",
        "indices": rows,
        "quotes": [],
        "source_health": {},
    }


def test_market_snapshot_embeds_registry_used_by_quote_binding() -> None:
    rows = bind_market_evidence(
        [{
            "ticker": "TAIEX",
            "price": 43119,
            "quote_date": "2026-08-11",
            "quote_time": "2026-08-11T01:00:00+00:00",
            "freshness": "live",
            "quote_source": "TWSE official MIS",
            "source_label": "TWSE",
            "cross_checked": True,
        }]
    )
    registry = InstrumentMaster().artifact()
    market = _market(rows)
    market["instrument_master"] = registry

    assert rows[0]["instrument_master_id"] == registry["registry_id"]
    assert validate_market(market) == []


def test_market_registry_mismatch_fails_closed() -> None:
    rows = bind_market_evidence(
        [{
            "ticker": "TAIEX",
            "price": 43119,
            "quote_date": "2026-08-11",
            "quote_time": "2026-08-11T01:00:00+00:00",
            "freshness": "live",
            "quote_source": "TWSE official MIS",
            "source_label": "TWSE",
            "cross_checked": True,
        }]
    )
    market = _market(rows)
    market["instrument_master"] = InstrumentMaster().artifact()
    rows[0]["instrument_master_id"] = "instrument-0000000000000000"
    rows[0]["instrument_master_version"] = 999

    errors = validate_market(market)

    assert any("instrument_master_id does not match" in error for error in errors)
    assert any("instrument_master_version does not match" in error for error in errors)


def test_market_registry_rejects_non_object_and_skips_non_object_quote() -> None:
    market = _market([None])
    market["instrument_master"] = []
    errors = validate_market(market)

    assert "market.instrument_master must be an object" in errors

    market["instrument_master"] = InstrumentMaster().artifact()
    errors = validate_market(market)
    assert errors
