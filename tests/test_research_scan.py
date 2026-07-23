import pandas as pd

from src.research_scan import build_price_action_snapshot


class StubScanner:
    def scan_daily(self, data):
        if data.attrs["symbol"] == "NONE":
            return None
        return {
            "turnover": data.attrs["turnover"],
            "funnel_labels": ["假跌破收復"],
            "atr": 2.1,
            "reference_risk": 4.2,
        }


def test_snapshot_ranks_research_candidates_and_limits_to_five():
    watchlist = tuple({"symbol": f"S{i}", "ticker": f"T{i}", "name": f"N{i}", "market": "us"} for i in range(6))

    def downloader(symbol):
        frame = pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]})
        frame.attrs["symbol"] = symbol
        frame.attrs["turnover"] = int(symbol[1:])
        return frame

    snapshot = build_price_action_snapshot(watchlist, scanner=StubScanner(), downloader=downloader)
    assert len(snapshot["candidates"]) == 5
    assert snapshot["candidates"][0]["ticker"] == "T5"
    assert snapshot["status"] == "已有結構研究候選"


def test_snapshot_has_neutral_no_candidate_conclusion():
    watchlist = ({"symbol": "NONE", "ticker": "NONE", "name": "None", "market": "us"},)

    def downloader(symbol):
        frame = pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]})
        frame.attrs["symbol"] = symbol
        return frame

    snapshot = build_price_action_snapshot(watchlist, scanner=StubScanner(), downloader=downloader)
    assert snapshot["candidates"] == []
    assert snapshot["status"] == "本次無符合裸 K 結構的代表標的"
