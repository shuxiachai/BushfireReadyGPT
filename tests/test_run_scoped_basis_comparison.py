import copy
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from scripts import run_scoped_basis_comparison as runner


@pytest.fixture(scope="module")
def frozen_bundle():
    from scripts.scoped_basis_comparison import prepare_bundle

    # No dependency on ignored real-run artifacts in clean CI checkouts.
    return prepare_bundle()


class FakeGuard:
    def __init__(self):
        self.calls = 0
        self.day = "2026-10-01"
        self.current_day = self.day
        self.failure = None
        self.identity = {"sources": {"test": "fixed"}, "dependencies": {"test": "fixed"}}
        self._credential = "unit-test-key"
        self.checks = []
        self.before_consume = None
        self.released = threading.Event()

    def check(self, expected):
        self.checks.append(expected)
        if self.failure:
            raise runner.RunStopped(self.failure)
        if self.current_day != self.day:
            raise runner.RunStopped("quota_day_changed")
        if self.calls != expected:
            raise runner.RunStopped("quota_count_changed")
        return {"day": self.day, "calls": self.calls, "remaining": 6 - self.calls}

    def acquire(self):
        self.released.clear()

        def consume():
            if self.before_consume:
                self.before_consume()
            self.calls += 1

        return SimpleNamespace(limits=SimpleNamespace(enabled=True), consume_call=consume, release=self.released.set)


def response(*, finish="stop", content="Synthetic planning text.", tool_calls=None):
    raw = {
        "choices": [{"message": {"content": content, "tool_calls": tool_calls}, "finish_reason": finish}],
        "model": "provider-returned-fixture-alias",
        "system_fingerprint": "fixture-fingerprint",
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(**raw["choices"][0]["message"]), finish_reason=finish)],
        model_dump=lambda **_: copy.deepcopy(raw),
    )


@pytest.fixture
def campaign(monkeypatch, tmp_path, frozen_bundle):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    from src import model_runtime

    monkeypatch.setattr(model_runtime, "MODEL_TEMPERATURE", 0.2)
    monkeypatch.setattr(model_runtime, "MODEL_MAX_TOKENS", 2300)
    guard = FakeGuard()
    monkeypatch.setattr(model_runtime, "acquire_model_slot", guard.acquire)
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    base = tmp_path / "output" / runner.CAMPAIGN
    base.mkdir(parents=True)
    original = json.dumps(frozen_bundle, sort_keys=True).encode("utf-8")
    (base / "prepared.json").write_bytes(original)
    state = SimpleNamespace(
        guard=guard,
        bundle=copy.deepcopy(frozen_bundle),
        base=base,
        requests=[],
        observers=[],
        close_calls=[],
        behavior=None,
        configure=None,
        close_failure=False,
        runtime_kwargs={},
        settings={"model": "fixture-request-alias", "endpoint": "https://api.deepseek.com", "timeout_seconds": 1.0},
    )

    def factory(settings, current, row, prompt):
        def create(**kwargs):
            state.requests.append((row["sequence"], copy.deepcopy(kwargs)))
            return state.behavior(row["sequence"], kwargs) if state.behavior else response()

        def close():
            state.close_calls.append(row["sequence"])
            if state.close_failure:
                raise OSError("SECRET must never appear in diagnostics")

        sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=close)
        observer = runner.RecordingSDK(sdk, current, row, prompt)
        state.observers.append(observer)
        if state.configure:
            state.configure(observer)
        client = runner._governed_runtime(
            completion_client=observer,
            model_name=settings["model"],
            provider="deepseek",
            is_local=False,
            timeout_seconds=settings["timeout_seconds"],
            **state.runtime_kwargs,
        )
        return client, observer

    state.factory = factory
    state.run = lambda: runner.execute(state.bundle, state.settings, guard, factory=factory)
    return state


def _events(campaign):
    return [
        json.loads(line) for line in (campaign.base / "campaign.calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def _saved(campaign, name):
    return json.loads((campaign.base / "execution-v1" / name).read_bytes())


def _synchronise_worker_start(monkeypatch, entered):
    original = threading.Thread.start

    def start_and_wait(thread):
        original(thread)
        if thread.name == "governed-model-completion":
            assert entered.wait(3)

    monkeypatch.setattr(threading.Thread, "start", start_and_wait)


def test_flags_reject_before_any_bundle_or_environment_access(monkeypatch):
    monkeypatch.setattr(
        runner, "_load_bundle", lambda *_: pytest.fail("No input/environment access without both flags")
    )
    for flags in ([], ["--run-model"], ["--allow-external-deepseek"]):
        assert runner.main(["run", "--expected-prepared-file-sha256", runner.PREPARED_SHA256, *flags]) == 2


def test_frozen_hash_and_rebuild_failure_precede_environment(monkeypatch):
    from scripts import scoped_basis_comparison

    with pytest.raises(runner.RunStopped, match="frozen_binding_failed"):
        runner._load_bundle("0" * 64)
    monkeypatch.setattr(
        scoped_basis_comparison, "validate_prepared", lambda *_: (_ for _ in ()).throw(ValueError("SECRET"))
    )
    with pytest.raises(runner.RunStopped, match="^frozen_binding_failed$"):
        runner._load_bundle(runner.PREPARED_SHA256)


def test_main_resolves_mock_factory_at_call_time_without_constructing_openai(campaign, monkeypatch):
    import openai

    from scripts import evaluate_body_evidence_deepseek as helpers

    monkeypatch.setattr(openai, "OpenAI", lambda **_: pytest.fail("A real SDK must not be constructed in this test"))
    monkeypatch.setattr(helpers, "admit_environment", lambda **_: campaign.settings)
    monkeypatch.setattr(runner, "_load_bundle", lambda _: campaign.bundle)
    monkeypatch.setattr(runner, "ExecutionGuard", lambda _: campaign.guard)
    monkeypatch.setattr(runner, "_client", campaign.factory)
    assert (
        runner.main(
            [
                "run",
                "--run-model",
                "--allow-external-deepseek",
                "--expected-prepared-file-sha256",
                runner.PREPARED_SHA256,
            ]
        )
        == 0
    )
    assert len(campaign.requests) == 6


@pytest.mark.parametrize(
    "field,value", [("max_requests", 7), ("attempts_per_case_arm", 2), ("stop_on_first_request_failure", False)]
)
def test_changed_frozen_plan_is_rejected(monkeypatch, frozen_bundle, field, value):
    from scripts import scoped_basis_comparison

    altered = copy.deepcopy(frozen_bundle)
    altered["execution_plan"][field] = value
    monkeypatch.setattr(scoped_basis_comparison, "validate_prepared", lambda *_: altered)
    with pytest.raises(runner.RunStopped, match="plan_rejected"):
        runner._load_bundle(runner.PREPARED_SHA256)


def test_six_real_governed_mock_requests_match_order_normalisation_capture_and_quota(campaign):
    from src.model_evidence import json_sha256, text_sha256, validate_recorded_assembly
    from src.model_runtime import GOVERNED_MODEL_SYSTEM_PROMPT

    before = (campaign.base / "prepared.json").read_bytes()
    result = campaign.run()
    assert result["stop_reason"] is None and not result["recording_incomplete"]
    assert len(campaign.requests) == campaign.guard.calls == result["sdk_dispatches_committed"] == 6
    assert campaign.close_calls == [1, 2, 3, 4, 5, 6]
    assert [row["arm"] for row in result["rows"]] == [
        "baseline",
        "candidate",
        "candidate",
        "baseline",
        "baseline",
        "candidate",
    ]
    for row, (_, kwargs) in zip(result["rows"], campaign.requests):
        case = next(case for case in campaign.bundle["cases"] if case["case_id"] == row["case_id"])
        frozen = case["arms"][row["arm"]]["prompt"]
        assert kwargs["messages"] == [
            {"role": "system", "content": GOVERNED_MODEL_SYSTEM_PROMPT},
            {"role": "user", "content": frozen.strip()},
        ]
        assert set(kwargs) == {"model", "messages", "temperature", "top_p", "max_tokens", "stream", "extra_body"}
        assert kwargs["temperature"] == 0.2 and kwargs["max_tokens"] == 2300 and kwargs["stream"] is False
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        request = _saved(campaign, f"request-{row['sequence']:02}.json")
        assert request["frozen_prompt_sha256"] == text_sha256(frozen)
        assert request["submitted_user_sha256"] == text_sha256(frozen.strip()) != text_sha256(frozen)
        assert request["request_binding"]["messages_sha256"] == json_sha256(kwargs["messages"])
        assert (
            validate_recorded_assembly(request["rag_assembly"], case["arms"][row["arm"]]["analysis"])
            == case["shared_rag"]["visible_chunks"]
        )
        raw = _saved(campaign, f"response-details-{row['sequence']:02}.json")
        assert raw["provider_returned_model"] == "provider-returned-fixture-alias"
        assert raw["system_fingerprint"] == "fixture-fingerprint" and raw["usage"]["total_tokens"] == 13
        assert raw["model_evidence"]["status"] == row["model_evidence"]["status"] == "captured"
        assert row["status"] == "generated" and row["allowance_consumed"] is True
    events = _events(campaign)
    assert [event["event"] for event in events].count("reserved") == 6
    assert [event["event"] for event in events].count("allowance_consumed") == 6
    assert [event["event"] for event in events].count("sdk_started") == 6
    assert events[-1]["quota"]["calls"] == 6
    assert (campaign.base / "prepared.json").read_bytes() == before
    assert result["semantic_accuracy"] is None and result["production_enabled"] is False


def test_claim_cannot_be_reopened_after_a_failed_or_completed_campaign(campaign):
    campaign.behavior = lambda *_: (_ for _ in ()).throw(ConnectionError("SECRET"))
    result = campaign.run()
    assert result["stop_reason"] == "transport" and len(result["rows"]) == 6
    assert len(campaign.requests) == 1
    with pytest.raises(runner.RunStopped, match="campaign_already_claimed"):
        campaign.run()
    assert len(campaign.requests) == 1
    assert "SECRET" not in json.dumps(result) + json.dumps(_saved(campaign, "response-01.json"))


def test_with_options_preserves_observer_and_double_dispatch_stops(campaign):
    def behavior(_sequence, kwargs):
        observer = campaign.observers[0]
        assert observer.with_options(max_retries=0) is observer
        return observer.create(**kwargs)

    campaign.behavior = behavior
    result = campaign.run()
    assert result["stop_reason"] == "duplicate_dispatch" and len(campaign.requests) == 1
    assert all(row["status"] == "not_run" for row in result["rows"][1:])


def test_concurrent_duplicate_does_not_close_the_original_inflight_sdk(campaign):
    observed = {}

    def behavior(_sequence, kwargs):
        observer = campaign.observers[0]

        def duplicate():
            try:
                observer.create(**kwargs)
            except runner.RunStopped as error:
                observed["reason"] = error.code

        duplicate_worker = threading.Thread(target=duplicate)
        duplicate_worker.start()
        duplicate_worker.join(1)
        observed["done_while_first_sdk_active"] = observer.done.is_set()
        observed["closed_while_first_sdk_active"] = list(campaign.close_calls)
        return response()

    campaign.behavior = behavior
    result = campaign.run()
    assert observed == {
        "reason": "duplicate_dispatch",
        "done_while_first_sdk_active": False,
        "closed_while_first_sdk_active": [],
    }
    assert result["stop_reason"] == "duplicate_dispatch" and len(campaign.requests) == 1
    assert campaign.close_calls == [1]


def test_wrong_cell_is_blocked_before_sdk(campaign):
    campaign.guard.before_consume = lambda: setattr(campaign.observers[0].state, "active_sequence", 2)
    result = campaign.run()
    assert result["stop_reason"] == "wrong_cell" and campaign.requests == []


def test_wrong_frozen_order_cannot_be_dispatched(campaign):
    campaign.configure = lambda observer: observer.row.update(arm="candidate")
    result = campaign.run()
    assert result["stop_reason"] == "wrong_cell" and campaign.requests == []


def test_observer_cannot_rebind_both_its_prompt_and_actual_sdk_messages(campaign):
    from src.model_evidence import EvidencePrompt, bind_submitted_messages

    def configure(observer):
        observer.prompt = EvidencePrompt(str(observer.prompt) + "Unapproved suffix", assembly=observer.prompt.assembly)
        original = observer.chat.completions.create

        def changed(**kwargs):
            kwargs["messages"][1]["content"] = str(observer.prompt).strip()
            bind_submitted_messages(kwargs["messages"])
            return original(**kwargs)

        observer.chat.completions.create = changed

    campaign.configure = configure
    result = campaign.run()
    assert result["stop_reason"] == "frozen_binding_failed" and campaign.requests == []


@pytest.mark.parametrize(
    "field,value", [("temperature", 0.8), ("max_tokens", 999), ("stream", True), ("seed", 42), ("tools", [])]
)
def test_unexpected_actual_sdk_parameters_are_blocked(campaign, field, value):
    def configure(observer):
        original = observer.chat.completions.create

        def changed(**kwargs):
            kwargs[field] = value
            return original(**kwargs)

        observer.chat.completions.create = changed

    campaign.configure = configure
    result = campaign.run()
    assert result["stop_reason"] == "request_parameters_changed" and campaign.requests == []
    assert campaign.guard.calls == 1


@pytest.mark.parametrize(
    "drift",
    [
        "source_drift",
        "dependency_drift",
        "configuration_drift",
        "credential_drift",
        "quota_day_changed",
        "quota_count_changed",
        "quota_unavailable",
    ],
)
def test_drift_after_return_stops_before_next_cell(campaign, drift):
    def behavior(*_):
        campaign.guard.failure = drift
        return response()

    campaign.behavior = behavior
    result = campaign.run()
    assert result["stop_reason"] == drift and len(campaign.requests) == 1
    assert result["rows"][0]["status"] == "failed"
    assert all(row["status"] == "not_run" for row in result["rows"][1:])


@pytest.mark.parametrize(
    "finish,content,tool_calls,reason",
    [
        ("length", "Partial planning text", None, "length"),
        ("content_filter", "", None, "protocol_failure"),
        ("stop", None, [{"id": "forbidden"}], "protocol_failure"),
    ],
)
def test_protocol_failures_keep_raw_response_and_never_retry(campaign, finish, content, tool_calls, reason):
    campaign.behavior = lambda *_: response(finish=finish, content=content, tool_calls=tool_calls)
    result = campaign.run()
    assert result["stop_reason"] == reason and len(campaign.requests) == 1
    raw = _saved(campaign, "response-01.json")
    assert raw["raw_response"]["choices"][0]["finish_reason"] == finish
    assert raw["raw_response"]["choices"][0]["message"]["content"] == content
    assert result["rows"][0]["status"] == "failed"


def test_capture_failure_preserves_raw_and_stops(campaign, monkeypatch):
    from src import model_evidence

    monkeypatch.setattr(model_evidence, "capture_model_evidence", lambda *a, **k: {"status": "unavailable"})
    result = campaign.run()
    assert result["stop_reason"] == "capture_failed" and len(campaign.requests) == 1
    assert _saved(campaign, "response-01.json")["raw_response"]["choices"]


@pytest.mark.parametrize(
    "raw,reason",
    [
        ({"choices": [{"message": None, "finish_reason": "stop"}]}, "protocol_failure"),
        ({"choices": [{"message": [], "finish_reason": "stop"}]}, "protocol_failure"),
        ({"choices": None}, "protocol_failure"),
        ({"choices": [None]}, "protocol_failure"),
        ([], "protocol_failure"),
        (
            {"choices": [{"message": {"content": "text"}, "finish_reason": "stop"}], "usage": "invalid metadata"},
            "capture_failed",
        ),
    ],
)
def test_malformed_dump_is_durable_before_any_protocol_or_metadata_derivation(campaign, raw, reason):
    campaign.behavior = lambda *_: SimpleNamespace(model_dump=lambda **_: copy.deepcopy(raw))
    result = campaign.run()
    assert result["stop_reason"] == reason and len(campaign.requests) == 1
    assert _saved(campaign, "response-01.json")["raw_response"] == raw
    assert all(row["status"] == "not_run" for row in result["rows"][1:])


@pytest.mark.parametrize(
    "filename,expected_calls",
    [("snapshot.json", 0), ("request-01.json", 0), ("response-01.json", 1), ("result-01.json", 1), ("results.json", 6)],
)
def test_recording_failures_stop_and_keep_claim(campaign, monkeypatch, filename, expected_calls):
    original = runner._write_once

    def failure(path, value):
        if path.name == filename:
            raise OSError("SECRET path")
        return original(path, value)

    monkeypatch.setattr(runner, "_write_once", failure)
    result = campaign.run()
    assert result["stop_reason"] == "recording_failed" and result["recording_incomplete"]
    assert len(campaign.requests) == expected_calls and len(result["rows"]) == 6
    assert (campaign.base / "campaign.calls.jsonl").exists()
    assert "SECRET" not in json.dumps(result)


def test_journal_failure_stops_before_sdk(campaign, monkeypatch):
    original = runner.Journal.append

    def failure(self, event, **values):
        if event == "allowance_consumed":
            raise OSError("SECRET")
        return original(self, event, **values)

    monkeypatch.setattr(runner.Journal, "append", failure)
    result = campaign.run()
    assert result["stop_reason"] == "journal_failed" and campaign.requests == []


def test_journal_close_failure_is_visible_in_final_result(campaign, monkeypatch):
    original = runner.Journal.close

    def failure(self):
        original(self)
        raise OSError("SECRET")

    monkeypatch.setattr(runner.Journal, "close", failure)
    result = campaign.run()
    assert result["stop_reason"] == "journal_close_failed" and result["recording_incomplete"]
    assert _saved(campaign, "results.json")["stop_reason"] == "journal_close_failed"


@pytest.mark.parametrize("finish,first_reason", [("stop", "client_close_failed"), ("length", "length")])
def test_client_close_failure_preserves_first_reason_and_stops(campaign, finish, first_reason):
    campaign.close_failure = True
    campaign.behavior = lambda *_: response(finish=finish)
    result = campaign.run()
    assert result["stop_reason"] == first_reason and len(campaign.requests) == 1
    if finish == "length":
        assert "client_close_failed" in result["secondary_errors"]


def test_local_deadline_adapter_preserves_runtime_exception_boundary(campaign):
    from src.model_response import ModelServiceError
    from src.model_runtime import GovernedModelClient

    client = runner._governed_runtime(completion_client=object(), timeout_seconds=1)
    error = client._deadline_error()
    assert isinstance(client, GovernedModelClient)
    assert isinstance(error, ModelServiceError) and isinstance(error, runner.RunStopped)
    assert runner._reason(error) == "timeout"
    # The production/shared runtime's error constructor remains untouched.
    assert not isinstance(GovernedModelClient(completion_client=object())._deadline_error(), runner.RunStopped)
    assert campaign.requests == []


def test_production_client_factory_uses_the_local_deadline_adapter(campaign, monkeypatch):
    from scripts import evaluate_body_evidence_deepseek as helpers

    observed = {}

    def build(settings, **kwargs):
        observed.update(kwargs)
        return "synthetic runtime", "synthetic observer"

    monkeypatch.setattr(helpers, "build_client", build)
    assert runner._client(campaign.settings, None, None, None) == ("synthetic runtime", "synthetic observer")
    assert observed["runtime_factory"] is runner._governed_runtime
    assert campaign.requests == []


def test_worker_deadline_stays_timeout_after_sdk_completion(campaign, monkeypatch):
    # The worker's own clock expires after the response. The observer clock is
    # intentionally uninformative; it must not determine the error category.
    campaign.settings["timeout_seconds"] = 10
    campaign.runtime_kwargs["clock"] = iter((0.0, 20.0)).__next__
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: 100.0))
    result = campaign.run()
    assert result["stop_reason"] == "timeout" and len(campaign.requests) == 1
    assert result["rows"][0]["worker_pending"] is False
    assert result["rows"][0]["governed_elapsed_seconds"] == 0.0
    assert all(row["status"] == "not_run" for row in result["rows"][1:])
    assert _saved(campaign, "response-01.json")["raw_response"]["choices"]


def test_long_observed_elapsed_does_not_reclassify_an_unrelated_service_error(campaign, monkeypatch):
    from src.model_response import ModelServiceError

    ticks = iter((0.0, 0.0, 100.0, 100.0))
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: next(ticks, 100.0)))

    def factory(*args):
        client, observer = campaign.factory(*args)

        def fail(_prompt):
            raise ModelServiceError("Synthetic non-deadline failure")

        client.generate = fail
        return client, observer

    try:
        result = runner.execute(campaign.bundle, campaign.settings, campaign.guard, factory=factory)
    finally:
        for observer in campaign.observers:
            observer.close()  # This synthetic generate never created a worker.
    assert result["stop_reason"] == "service_or_deadline_failure"
    assert result["rows"][0]["governed_elapsed_seconds"] > campaign.settings["timeout_seconds"]
    assert campaign.requests == [] and campaign.guard.calls == 0


def test_timeout_keeps_worker_resource_and_late_capture_cannot_promote_result(campaign, monkeypatch):
    arrived, release = threading.Event(), threading.Event()
    campaign.settings["timeout_seconds"] = 0.05
    _synchronise_worker_start(monkeypatch, arrived)

    def behavior(*_):
        arrived.set()
        assert release.wait(3)
        return response()

    campaign.behavior = behavior
    try:
        result = campaign.run()
        assert arrived.is_set() and result["stop_reason"] == "timeout"
        assert result["rows"][0]["worker_pending"] is True and campaign.close_calls == []
        saved = (campaign.base / "execution-v1/results.json").read_bytes()
        ledger = (campaign.base / "campaign.calls.jsonl").read_bytes()
    finally:
        release.set()
        assert campaign.guard.released.wait(3)
    assert campaign.close_calls == [1] and len(campaign.requests) == 1
    assert _saved(campaign, "response-01.json")["after_stop"] is True
    assert (campaign.base / "execution-v1/results.json").read_bytes() == saved
    assert (campaign.base / "campaign.calls.jsonl").read_bytes() == ledger


@pytest.mark.parametrize("coarse_clock", [False, True], ids=["normal-clock", "coarse-observer-clock"])
def test_delayed_worker_never_starts_sdk_after_timeout(campaign, monkeypatch, coarse_clock):
    entered, release = threading.Event(), threading.Event()
    campaign.settings["timeout_seconds"] = 0.05
    _synchronise_worker_start(monkeypatch, entered)
    if coarse_clock:
        # Only the recorder's observation is coarse. The real governed client
        # and Event.wait retain their real clocks and deadline decision.
        monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: 100.0))

    def configure(observer):
        original = observer.with_options

        def delayed(**kwargs):
            entered.set()
            assert release.wait(3)
            return original(**kwargs)

        observer.with_options = delayed

    campaign.configure = configure
    try:
        result = campaign.run()
        if coarse_clock:
            assert result["rows"][0]["governed_elapsed_seconds"] == 0.0
        assert entered.is_set() and result["stop_reason"] == "timeout"
    finally:
        release.set()
        assert campaign.guard.released.wait(3)
    assert campaign.requests == [] and campaign.guard.calls == 0 and campaign.close_calls == [1]


def test_timeout_during_post_consume_guard_cannot_write_closed_journal_or_dispatch(campaign, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    campaign.settings["timeout_seconds"] = 0.05
    _synchronise_worker_start(monkeypatch, entered)
    original = campaign.guard.check
    waiting = False

    def delayed(expected):
        nonlocal waiting
        if expected == 1 and not waiting:
            waiting = True
            entered.set()
            assert release.wait(3)
        return original(expected)

    campaign.guard.check = delayed
    try:
        result = campaign.run()
        assert entered.is_set() and result["stop_reason"] == "timeout"
        assert campaign.requests == [] and campaign.guard.calls == 1
        ledger = (campaign.base / "campaign.calls.jsonl").read_bytes()
    finally:
        release.set()
        assert campaign.guard.released.wait(3)
    assert campaign.requests == [] and campaign.close_calls == [1]
    assert _saved(campaign, "late-boundary-01.json")["quota"]["calls"] == 1
    assert (campaign.base / "campaign.calls.jsonl").read_bytes() == ledger


@pytest.fixture
def identity_guard(monkeypatch, tmp_path):
    from src import model_limits

    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-secret-never-serialized")
    monkeypatch.setattr(runner, "_today", lambda: "2026-10-01")
    base = tmp_path / "output" / runner.CAMPAIGN
    base.mkdir(parents=True)
    (base / "prepared.json").write_bytes(b"synthetic prepared binding")
    monkeypatch.setattr(runner, "PREPARED_SHA256", hashlib.sha256(b"synthetic prepared binding").hexdigest())
    current = {"sources": {"x": "a"}, "dependencies": {"x": "b"}, "settings": {}, "effective": {}}
    monkeypatch.setattr(runner.ExecutionGuard, "_identity", lambda self: copy.deepcopy(current))
    limits = model_limits.ModelLimits(1, 6, tmp_path / "chat_history/model-usage.sqlite3", False)
    usage = {"status": "ready", "day": "2026-10-01", "calls": 0}
    monkeypatch.setattr(model_limits, "load_model_limits", lambda: limits)
    monkeypatch.setattr(model_limits, "read_model_usage", lambda *a, **k: copy.deepcopy(usage))
    return runner.ExecutionGuard({}), current, usage, limits


@pytest.mark.parametrize(
    "field,code",
    [
        ("sources", "source_drift"),
        ("dependencies", "dependency_drift"),
        ("settings", "configuration_drift"),
        ("effective", "configuration_drift"),
    ],
)
def test_real_identity_guard_rejects_changes_without_dumping_secrets(identity_guard, field, code):
    guard, current, *_ = identity_guard
    current[field]["x"] = "changed"
    with pytest.raises(runner.RunStopped, match=code):
        guard.check(0)
    assert "unit-secret" not in json.dumps(guard.identity)


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("credential", "credential_drift"),
        ("day", "quota_day_changed"),
        ("extra_call", "quota_count_changed"),
        ("unavailable", "quota_unavailable"),
        ("not_initialized", "quota_unavailable"),
    ],
)
def test_real_guard_requires_same_key_day_and_exact_ready_usage(identity_guard, monkeypatch, mutation, code):
    guard, _, usage, _ = identity_guard
    if mutation == "credential":
        monkeypatch.setenv("DEEPSEEK_API_KEY", "different-unit-secret")
    elif mutation == "day":
        monkeypatch.setattr(runner, "_today", lambda: "2026-10-02")
    elif mutation == "extra_call":
        usage["calls"] = 1
    else:
        usage["status"] = mutation
    with pytest.raises(runner.RunStopped, match=f"^{code}$"):
        guard.check(0)


@pytest.mark.parametrize(
    "concurrency,daily,path", [(2, 6, "chat_history"), (1, 7, "chat_history"), (1, 6, "alternate")]
)
def test_real_guard_rejects_alternate_quota_configuration(identity_guard, monkeypatch, concurrency, daily, path):
    from src import model_limits

    guard, _, _, limits = identity_guard
    monkeypatch.setattr(
        model_limits,
        "load_model_limits",
        lambda: model_limits.ModelLimits(
            concurrency, daily, limits.database.parents[1] / path / "model-usage.sqlite3", False
        ),
    )
    with pytest.raises(runner.RunStopped, match="quota_configuration"):
        guard.check(0)
