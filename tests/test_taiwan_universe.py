import json

import requests

from src.taiwan_universe import load_or_fetch_taiwan_universe, parse_isin_table

def test_isin_parser_keeps_only_four_digit_ordinary_shares():
    html = """<table><tr><th>名稱</th><th>a</th><th>b</th><th>c</th><th>類別</th></tr>
    <tr><td>2330 台積電</td><td></td><td></td><td></td><td>半導體業</td></tr>
    <tr><td>12345 排除</td><td></td><td></td><td></td><td>其他</td></tr>
    <tr><td>1234 權證</td><td></td><td></td><td></td><td>權證</td></tr></table>"""
    assert parse_isin_table(html, ".TW") == [{"ticker": "2330", "name": "台積電", "symbol": "2330.TW", "category": "半導體業"}]


def test_same_run_universe_snapshot_is_reused(tmp_path, monkeypatch):
    saved = [{"ticker": "2330", "name": "台積電", "symbol": "2330.TW", "category": "半導體業"}]
    path = tmp_path / "universe.json"
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("src.taiwan_universe.fetch_taiwan_universe", lambda: (_ for _ in ()).throw(requests.RequestException()))
    assert load_or_fetch_taiwan_universe(path) == saved
