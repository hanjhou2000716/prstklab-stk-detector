from src.macro_program_feed import fetch_yutinghao_latest_program


def test_public_program_feed_reads_latest_title_and_original_link(monkeypatch):
    xml = '''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>最新節目</title><link rel="alternate" href="https://www.youtube.com/watch?v=abc"/><published>2026-07-24T02:00:00+00:00</published></entry></feed>'''.encode()

    class Response:
        content = xml

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr("src.macro_program_feed.requests.get", lambda *args, **kwargs: Response())

    assert fetch_yutinghao_latest_program() == {
        "title": "最新節目",
        "url": "https://www.youtube.com/watch?v=abc",
        "published_at": "2026-07-24T02:00:00+00:00",
        "source": "游庭皓的財經皓角｜YouTube",
    }
