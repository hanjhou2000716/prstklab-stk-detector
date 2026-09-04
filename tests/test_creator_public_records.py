import json
from pathlib import Path

from src.creator_intelligence_pipeline import build_creator_intelligence_release


def test_reviewed_haojiao_record_is_public_safe_and_attributed():
    payload = json.loads(Path("creator/public-records.json").read_text(encoding="utf-8"))
    records = payload["records"]
    assert len(records) == 1
    record = records[0]
    assert record["content_origin"] == "haojiao"
    assert record["public_safe"] is True
    assert record["verification_state"] == "unverified"
    assert record["source_url"].startswith("https://www.youtube.com/")
    assert not {"body", "raw_body", "attachments", "gmail_message_id", "local_path"} & set(record)


def test_retired_haojiao_record_is_not_added_to_new_creator_release():
    records = json.loads(Path("creator/public-records.json").read_text(encoding="utf-8"))["records"]
    result = build_creator_intelligence_release(
        records,
        parent_manifest={
            "release_id": "release-test-haojiao",
            "market_snapshot_id": "market-test-haojiao",
            "event_snapshot_id": "event-test-haojiao",
        },
    )
    assert result["accepted_count"] == 0
    assert result["dropped_reasons"] == ["0:retired_source_suppressed"]
    assert result["artifact"]["status"] == "ready"
    assert result["artifact"]["insights"] == []
