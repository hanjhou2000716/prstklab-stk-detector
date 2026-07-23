from src.taiwan_universe import parse_isin_table

def test_isin_parser_keeps_only_four_digit_ordinary_shares():
    html = """<table><tr><th>名稱</th><th>a</th><th>b</th><th>c</th><th>類別</th></tr>
    <tr><td>2330 台積電</td><td></td><td></td><td></td><td>半導體業</td></tr>
    <tr><td>12345 排除</td><td></td><td></td><td></td><td>其他</td></tr>
    <tr><td>1234 權證</td><td></td><td></td><td></td><td>權證</td></tr></table>"""
    assert parse_isin_table(html, ".TW") == [{"ticker": "2330", "name": "台積電", "symbol": "2330.TW", "category": "半導體業"}]
