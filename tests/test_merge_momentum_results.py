import pandas as pd
from src.merge_momentum_results import merge_results

def test_merge_keeps_global_top_ten(tmp_path):
    pd.DataFrame({"ticker":["A"], "score":[10]}).to_csv(tmp_path / "taiwan-momentum-scan-0.csv", index=False)
    pd.DataFrame({"ticker":["B"], "score":[20]}).to_csv(tmp_path / "taiwan-momentum-scan-1000.csv", index=False)
    assert list(merge_results(tmp_path)["ticker"]) == ["B", "A"]

def test_merge_skips_empty_segment_files(tmp_path):
    (tmp_path / "taiwan-momentum-scan-0.csv").write_text("", encoding="utf-8")
    assert merge_results(tmp_path).empty
