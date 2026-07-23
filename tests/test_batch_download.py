from src.batch_download import batches, download_in_batches

def test_batches_and_failure_isolation():
    items = [{"ticker": str(i)} for i in range(5)]
    assert [len(group) for group in batches(items, 2)] == [2, 2, 1]
    data, errors = download_in_batches(items, lambda group: (_ for _ in ()).throw(ValueError()) if group[0]["ticker"] == "2" else {x["ticker"]: x for x in group}, 2)
    assert set(data) == {"0", "1", "4"} and len(errors) == 2
