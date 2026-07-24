import pandas as pd
import pytest

from src.public_download import download_daily_batch


def test_batch_download_retries_once_after_transient_failure():
    calls = []
    def downloader(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TimeoutError("temporary")
        return pd.DataFrame({"Close": [1]})
    result = download_daily_batch(["TEST"], downloader=downloader, timeout=7)
    assert len(calls) == 2
    assert calls[-1]["timeout"] == 7
    assert not result.empty


def test_empty_public_response_is_retried_then_disclosed_as_failure():
    calls = []
    def downloader(*args, **kwargs):
        calls.append(1)
        return pd.DataFrame()
    with pytest.raises(RuntimeError):
        download_daily_batch(["TEST"], downloader=downloader)
    assert len(calls) == 2


def test_invalid_batch_arguments_are_rejected():
    with pytest.raises(ValueError):
        download_daily_batch([])
    with pytest.raises(ValueError):
        download_daily_batch(["TEST"], timeout=0)
