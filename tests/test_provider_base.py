import requests
import pytest
from podscribe.providers.base import stream_with_retry, RETRY_DELAYS


class _Resp:
    def __init__(self, status=200):
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            err = requests.HTTPError(f"{self._status}")
            err.response = self
            self.status_code = self._status
            raise err


def test_success_returns_consume_result(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    out = stream_with_retry(lambda: _Resp(200), lambda r: "ok",
                            max_retries=3, on_retry=lambda a, e: None)
    assert out == "ok"


def test_4xx_returns_none_without_retry(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def make():
        calls["n"] += 1
        return _Resp(404)

    out = stream_with_retry(make, lambda r: "x", max_retries=3, on_retry=lambda a, e: None)
    assert out is None
    assert calls["n"] == 1  # no retry on 4xx


def test_5xx_retries_then_gives_up(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    retries = []
    out = stream_with_retry(lambda: _Resp(500), lambda r: "x",
                            max_retries=3, on_retry=lambda a, e: retries.append(a))
    assert out is None
    assert retries == [1, 2]  # retried before attempts 2 and 3


def test_connection_error_during_consume_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    attempts = {"n": 0}

    def consume(resp):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise requests.ConnectionError("boom")
        return "recovered"

    out = stream_with_retry(lambda: _Resp(200), consume,
                            max_retries=3, on_retry=lambda a, e: None)
    assert out == "recovered"
