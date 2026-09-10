import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from src import model_limits
from src.model_runtime import GovernedModelClient, ModelServiceError


@pytest.fixture
def cloud_limits(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("BUSHFIRE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("BUSHFIRE_MODEL_MAX_CONCURRENT", "1")
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "100")
    return tmp_path / "model-usage.sqlite3"


def _completion(text="report"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class _Client:
    def __init__(self, create):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
        self.options = []

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self


def _count(database):
    with closing(sqlite3.connect(database)) as connection:
        return sum(row[0] for row in connection.execute("SELECT calls FROM daily_calls"))


def test_cloud_defaults_are_conservative_and_local_limits_are_optional(tmp_path):
    cloud = model_limits.load_model_limits({"BUSHFIRE_DEPLOYMENT_MODE": "cloud", "BUSHFIRE_RUNTIME_DIR": str(tmp_path)})
    assert (cloud.concurrency, cloud.daily_calls) == (1, 100)
    assert cloud.database == tmp_path / "model-usage.sqlite3"
    assert cloud.enabled
    local = model_limits.load_model_limits({})
    assert (local.concurrency, local.daily_calls) == (0, 0)
    assert not local.enabled


@pytest.mark.parametrize("name", ["BUSHFIRE_MODEL_MAX_CONCURRENT", "BUSHFIRE_MODEL_DAILY_CALL_LIMIT"])
@pytest.mark.parametrize("value", ["-1", "1.5", "nan", "", "bogus"])
def test_malformed_limits_do_not_disable_protection(name, value):
    with pytest.raises(model_limits.DeploymentConfigurationError):
        model_limits.load_model_limits({name: value})


def test_daily_allowance_is_persisted_across_clients_and_counts_repairs(cloud_limits, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "2")
    for prompt in ("initial report", "repair the report"):
        runtime = GovernedModelClient(completion_client=_Client(lambda **_: _completion()), is_local=False)
        assert runtime.generate(prompt) == "report"
    new_browser_client = GovernedModelClient(completion_client=_Client(lambda **_: _completion()), is_local=False)
    with pytest.raises(ModelServiceError, match="daily model-call allowance"):
        new_browser_client.generate("new browser after clearing session")
    assert _count(cloud_limits) == 2


def test_actual_sdk_http_retries_are_disabled_and_failed_attempts_count(cloud_limits):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(500, json={"error": {"message": "upstream failure"}})

    sdk = OpenAI(api_key="test-only", max_retries=4, http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    runtime = GovernedModelClient(completion_client=sdk, provider="deepseek", is_local=False)
    try:
        with pytest.raises(ModelServiceError, match="HTTP 500"):
            runtime.generate("report")
        assert len(requests) == 1
        assert _count(cloud_limits) == 1
        assert model_limits._ACTIVE_REQUESTS == 0
    finally:
        sdk.close()


def test_timeout_keeps_global_slot_until_provider_really_finishes(cloud_limits):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocked_create(**_):
        started.set()
        try:
            assert release.wait(2)
            return _completion("late response")
        finally:
            finished.set()

    first = GovernedModelClient(completion_client=_Client(blocked_create), is_local=False, timeout_seconds=0.04)
    next_client = GovernedModelClient(completion_client=_Client(lambda **_: _completion()), is_local=False)
    begin = time.monotonic()
    try:
        with pytest.raises(ModelServiceError, match="total deadline"):
            first.generate("first browser")
        assert time.monotonic() - begin < 0.5
        assert started.is_set() and not finished.is_set()
        with pytest.raises(ModelServiceError, match="shared model service is busy"):
            next_client.generate("new browser while first request is still in flight")
        assert _count(cloud_limits) == 1
    finally:
        release.set()
        assert finished.wait(1)
    deadline = time.monotonic() + 1
    while model_limits._ACTIVE_REQUESTS and time.monotonic() < deadline:
        time.sleep(0.005)
    assert next_client.generate("after the first request has finished") == "report"
    assert _count(cloud_limits) == 2


def test_stream_timeout_also_retains_slot_until_iterator_finishes(cloud_limits):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocked_stream():
        started.set()
        try:
            assert release.wait(2)
            yield SimpleNamespace(choices=[])
        finally:
            finished.set()

    runtime = GovernedModelClient(
        completion_client=_Client(lambda **_: blocked_stream()), is_local=True, timeout_seconds=0.04
    )
    try:
        with pytest.raises(ModelServiceError, match="total deadline"):
            runtime.generate("streaming request")
        assert started.is_set()
        with pytest.raises(model_limits.ModelAllowanceError, match="busy"):
            model_limits.acquire_model_slot()
    finally:
        release.set()
        assert finished.wait(1)
    deadline = time.monotonic() + 1
    while model_limits._ACTIVE_REQUESTS and time.monotonic() < deadline:
        time.sleep(0.005)
    assert model_limits._ACTIVE_REQUESTS == 0


def test_concurrent_reservations_cannot_overrun_daily_allowance(cloud_limits, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_MODEL_MAX_CONCURRENT", "20")
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "3")
    barrier = threading.Barrier(10)

    def reserve(_):
        slot = model_limits.acquire_model_slot()
        try:
            barrier.wait(timeout=2)
            slot.consume_call()
            return True
        except model_limits.ModelAllowanceError:
            return False
        finally:
            slot.release()

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(reserve, range(10)))
    assert sum(results) == 3
    assert _count(cloud_limits) == 3
    assert model_limits._ACTIVE_REQUESTS == 0


def test_quota_storage_failure_fails_closed_without_calling_provider(cloud_limits):
    cloud_limits.mkdir()
    calls = []
    runtime = GovernedModelClient(completion_client=_Client(lambda **_: calls.append(True)), is_local=False)
    with pytest.raises(ModelServiceError, match="persistent usage counter is unavailable"):
        runtime.generate("must not leave the application")
    assert calls == []
    assert model_limits._ACTIVE_REQUESTS == 0


def test_usage_connections_close_after_success_and_exhausted_allowance(cloud_limits, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "1")
    original_connect = sqlite3.connect
    connections = []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(model_limits.sqlite3, "connect", connect)
    slot = model_limits.acquire_model_slot()
    try:
        slot.consume_call()
        with pytest.raises(model_limits.ModelAllowanceError, match="daily model-call allowance"):
            slot.consume_call()
    finally:
        slot.release()
    assert len(connections) == 2
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")


def test_invalid_persisted_counter_fails_closed(cloud_limits):
    today = datetime.now(timezone.utc).date().isoformat()
    with closing(sqlite3.connect(cloud_limits)) as connection, connection:
        connection.execute("CREATE TABLE daily_calls (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
        connection.execute("INSERT INTO daily_calls VALUES (?, -1)", (today,))
    slot = model_limits.acquire_model_slot()
    try:
        with pytest.raises(model_limits.ModelAllowanceError, match="counter is invalid"):
            slot.consume_call()
    finally:
        slot.release()


def test_daily_allowance_rolls_over_at_utc_midnight(cloud_limits, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "1")
    current = [datetime(2026, 9, 10, 23, 59, tzinfo=timezone.utc)]
    monkeypatch.setattr(model_limits, "datetime", SimpleNamespace(now=lambda _: current[0]))
    slot = model_limits.acquire_model_slot()
    try:
        slot.consume_call()
        with pytest.raises(model_limits.ModelAllowanceError, match="daily model-call allowance"):
            slot.consume_call()
        current[0] = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)
        slot.consume_call()
    finally:
        slot.release()
    with closing(sqlite3.connect(cloud_limits)) as connection:
        rows = list(connection.execute("SELECT day, calls FROM daily_calls ORDER BY day"))
    assert rows == [("2026-09-10", 1), ("2026-09-11", 1)]


def test_relative_usage_directory_matches_shared_runtime_path(monkeypatch):
    from src.runtime_paths import runtime_path

    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "local")
    monkeypatch.setenv("BUSHFIRE_RUNTIME_DIR", "runtime-test-folder")
    assert model_limits.load_model_limits().database == runtime_path("model-usage.sqlite3")


def test_deepseek_uses_final_text_mode_with_explicit_budget():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _completion()

    runtime = GovernedModelClient(completion_client=_Client(create), provider="deepseek", is_local=False)
    assert runtime.generate("report") == "report"
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured["max_tokens"] > 0


@pytest.mark.parametrize("timeout", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_deadlines_are_rejected(timeout):
    with pytest.raises(ValueError, match="finite"):
        GovernedModelClient(timeout_seconds=timeout)
