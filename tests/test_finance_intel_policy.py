from src.finance_intel_policy import load_finance_intel_policy, polling_rule, threshold_rule


def test_public_intelligence_policy_keeps_required_safety_and_timing_rules():
    policy = load_finance_intel_policy()
    assert policy["mode"] == "public-read-only"
    assert polling_rule("firstRunBaselineOnly") is True
    assert polling_rule("officialEventMaxAgeMinutes") == 90
    assert polling_rule("discoveryEventMaxAgeMinutes") == 45
    assert polling_rule("topicCooldownMinutes") == 30
    assert polling_rule("retryOn429") is False
    assert policy["security"]["noPrivateAccounts"] is True
    assert threshold_rule("usgsMagnitude") == 6.5
