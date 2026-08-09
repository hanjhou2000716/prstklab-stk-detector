from src.provider_health import classify_provider_error, error_token


class ResponseError(Exception):
    def __init__(self, status_code: int):
        self.response = type("Response", (), {"status_code": status_code})()


def test_provider_error_classification_is_stable_and_non_sensitive():
    assert classify_provider_error(ResponseError(403)) == {
        "code": "http_403",
        "retryable": False,
        "http_status": 403,
    }
    assert classify_provider_error(TimeoutError("secret endpoint"))["code"] == "timeout"
    assert error_token("binance", "BTC", ResponseError(429)) == "binance:BTC:http_429"

