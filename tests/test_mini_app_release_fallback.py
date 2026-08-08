from pathlib import Path


def test_mini_app_has_retry_last_good_release_and_degraded_status():
    root = Path(__file__).resolve().parents[1]
    app = (root / "site" / "app.js").read_text(encoding="utf-8")
    html = (root / "site" / "index.html").read_text(encoding="utf-8")
    assert "LAST_GOOD_RELEASE_KEY" in app
    assert "localStorage.setItem" in app
    assert "資料降級" in app
    assert "目前不可觸發高風險快訊" in app
    assert "setReleaseHealth" in app
    assert "release-health" in html
    assert "attempt < 2" in app
