from src.advice_gate import FAIL_MESSAGE, add_counterargument, build_scenario_advice, evaluate_advice_gate


def test_gate_rejects_missing_backtest():
    result = evaluate_advice_gate({"data_quality_ok": True})
    assert not result["allowed"]
    assert "backtest_valid" in result["missing"]


def test_allowed_output_is_neutral_and_has_counterargument():
    context = {key: True for key in ("data_quality_ok", "freshness_ok", "sources_cross_checked", "backtest_valid", "candidate_complete", "policy_valid")}
    advice = build_scenario_advice(context, horizon="medium", thesis="trend evidence", evidence=["price"], trigger=["confirm"], invalidation=["break"], risks=["gap"], confidence="medium", alternative="range")
    assert advice["stance"] == "觀察"
    assert add_counterargument(advice, strongest_counterargument="data may reverse", review_when="next close")["counterargument"]


def test_fail_message_is_stable():
    assert "資料不足" in FAIL_MESSAGE
