from collector import collectors
from collector.sources import pirs


def _html(n):
    items = "".join(
        f'<div class="incident-history-item"><span class="hide-text">01/0{(i % 9) + 1}/2026</span>'
        f'<div class="incident-history-title">PIR {i}</div><div class="incident-history-tracking-id">Tracking ID: T-{i}</div>'
        f'<div class="incident-history-collapse">body {i}</div></div>'
        for i in range(n)
    )
    return f"<div>{items}</div>"


class FakeResp:
    def __init__(self, text, code=200):
        self.text, self.status_code = text, code


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, params=None, timeout=0):
        self.calls.append(params["page"])
        seq = self.pages.get(params["page"], [_html(0)])
        resp = seq.pop(0) if len(seq) > 1 else seq[0]
        return resp


def run(monkeypatch, pages):
    import requests

    monkeypatch.setattr(pirs.time, "sleep", lambda s: None)
    sess = FakeSession(pages)

    class S:
        headers = type("H", (), {"update": lambda self, d: None})()

        def get(self, *a, **k):
            return sess.get(*a, **k)

    monkeypatch.setattr(requests, "Session", lambda: S())
    return list(pirs.FetchPirSource(cache_dir=None, max_pages=5, delay_s=1).items()), sess

def test_empty_page_after_a_full_page_is_retried(monkeypatch):
    items, sess = run(monkeypatch, {1: [FakeResp(_html(10))], 2: [FakeResp(_html(0)), FakeResp(_html(10))], 3: [FakeResp(_html(4))]})
    assert len(items) == 24 and sess.calls.count(2) == 2


def test_short_page_is_the_end_without_retries(monkeypatch):
    items, sess = run(monkeypatch, {1: [FakeResp(_html(10))], 2: [FakeResp(_html(3))], 3: [FakeResp(_html(0))]})
    assert len(items) == 13 and sess.calls == [1, 2]


def test_persistently_empty_page_after_full_page_stops_after_three_tries(monkeypatch):
    items, sess = run(monkeypatch, {1: [FakeResp(_html(10))], 2: [FakeResp(_html(0))]})
    assert len(items) == 10 and sess.calls.count(2) == 3


def test_truncated_fetch_is_reported_as_partial(monkeypatch, tmp_path):
    class Src(pirs.FetchPirSource):
        def items(self):
            return iter([{"date": "01/02/2026", "title": "t", "tracking_id": "A", "text": "x"}] * 3)

    class Ing:
        def upload(self, table, rows, batch_size=500):
            return len(rows)

    res = collectors.run_pirs(Ing(), Src(cache_dir=None), None)
    assert any("truncated" in e for e in res.errors)
