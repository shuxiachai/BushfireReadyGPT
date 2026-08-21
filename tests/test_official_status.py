from threading import Barrier
from unittest.mock import Mock

import pytest
import requests

from src import official_status


def _response(status_code):
    response = Mock()
    response.status_code = status_code
    return response


def test_status_checks_run_concurrently_and_keep_source_order(monkeypatch):
    sources = [{"name": f"Source {index}", "url": f"https://example.test/{index}"} for index in range(4)]
    all_started = Barrier(len(sources))

    def head(*args, **kwargs):
        all_started.wait(timeout=1)
        return _response(200)

    monkeypatch.setattr(official_status.requests, "head", head)

    result = official_status.check_official_sources(sources, timeout=1)

    assert [row["name"] for row in result["rows"]] == [source["name"] for source in sources]
    assert result["summary"] == {"total": 4, "reachable": 4, "warnings": 0, "failed": 0}


def test_head_fallback_shares_one_total_timeout_budget(monkeypatch):
    observed_timeouts = []
    clock_values = iter([10.0, 10.0, 10.6, 10.8])

    def head(*args, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        return _response(405)

    def get(*args, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        return _response(200)

    monkeypatch.setattr(official_status, "perf_counter", lambda: next(clock_values))
    monkeypatch.setattr(official_status.requests, "head", head)
    monkeypatch.setattr(official_status.requests, "get", get)

    status_code, elapsed_ms = official_status._request_source("https://example.test", timeout=1)

    assert status_code == 200
    assert elapsed_ms in {799, 800}
    assert observed_timeouts == pytest.approx([1.0, 0.4])


def test_failed_head_and_get_are_reported_without_stopping_other_checks(monkeypatch):
    def head(url, **kwargs):
        if url.endswith("failed"):
            raise requests.ConnectionError("network unavailable")
        return _response(204)

    def get(*args, **kwargs):
        raise requests.Timeout("fallback timed out")

    monkeypatch.setattr(official_status.requests, "head", head)
    monkeypatch.setattr(official_status.requests, "get", get)

    result = official_status.check_official_sources(
        [
            {"name": "Failed", "url": "https://example.test/failed"},
            {"name": "Working", "url": "https://example.test/working"},
        ]
    )

    assert result["rows"][0]["status"] == "Check failed"
    assert result["rows"][0]["message"] == "fallback timed out"
    assert result["rows"][1]["status"] == "Reachable"
    assert result["summary"] == {"total": 2, "reachable": 1, "warnings": 0, "failed": 1}


def test_empty_source_list_returns_empty_summary():
    result = official_status.check_official_sources([])

    assert result["rows"] == []
    assert result["summary"] == {"total": 0, "reachable": 0, "warnings": 0, "failed": 0}
