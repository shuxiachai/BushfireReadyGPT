import copy
import json
import os
import threading
from types import SimpleNamespace

import pytest

from scripts import run_citation_criteria_comparison as runner
from tests import test_citation_criteria_comparison as preparation_tests

fixed_sources = preparation_tests.fixed_sources
source_guard_checkout = preparation_tests.source_guard_checkout
frozen_bundle = pytest.fixture(name="frozen_bundle")(preparation_tests.bundle.__wrapped__)


def response(finish="stop"):
    raw = {
        "choices": [
            {"message": {"content": "Synthetic planning record.", "tool_calls": None}, "finish_reason": finish}
        ],
        "model": "synthetic-provider-returned-alias",
        "system_fingerprint": "synthetic-fingerprint",
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    }
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(**raw["choices"][0]["message"]), finish_reason=finish)],
        model_dump=lambda **_: copy.deepcopy(raw),
    )


@pytest.fixture
def quota_environment(monkeypatch, tmp_path):
    from src import model_limits

    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-test-key-not-a-credential")
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "0")
    monkeypatch.setenv("BUSHFIRE_MODEL_MAX_CONCURRENT", "0")
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner.engine, "_today", lambda: "2026-10-01")
    usage = {"status": "ready", "day": "2026-10-01", "calls": 6}

    def limits():
        return model_limits.ModelLimits(
            int(os.environ[runner._LIMIT_KEYS[1]]),
            int(os.environ[runner._LIMIT_KEYS[0]]),
            tmp_path / "chat_history/model-usage.sqlite3",
            False,
        )

    monkeypatch.setattr(model_limits, "load_model_limits", limits)
    monkeypatch.setattr(model_limits, "read_model_usage", lambda *a, **k: copy.deepcopy(usage))
    return usage


@pytest.fixture
def campaign(monkeypatch, tmp_path, frozen_bundle, quota_environment):
    from src import model_runtime

    monkeypatch.setattr(model_runtime, "MODEL_TEMPERATURE", 0.2)
    monkeypatch.setattr(model_runtime, "MODEL_MAX_TOKENS", 2300)
    base = tmp_path / "output" / runner.CAMPAIGN
    base.mkdir(parents=True)
    bundle = frozen_bundle
    content = runner.engine._json_bytes(bundle)
    (base / "prepared.json").write_bytes(content)
    identity = {
        "sources": {
            **bundle["source_identity"]["current_python_source_sha256"],
            **bundle["source_identity"]["experiment_and_helper_sha256"],
        },
        "new_experiment_files": {
            path: bundle["source_identity"]["experiment_and_helper_sha256"][path]
            for path in runner.preparation.EXPERIMENT_FILES
        },
        "dependencies": {"fixture": "fixed"},
        "settings": {},
        "effective": {},
    }
    monkeypatch.setattr(runner.ExecutionGuard, "_identity", lambda self: copy.deepcopy(identity))
    quota = runner.QuotaOverlay()
    quota.apply()
    settings = {"model": "synthetic-request-alias", "endpoint": "https://api.deepseek.com", "timeout_seconds": 180}
    guard = runner.ExecutionGuard(settings, bundle, runner.engine._sha(content), quota)
    state = SimpleNamespace(
        base=base,
        bundle=bundle,
        settings=settings,
        guard=guard,
        quota=quota,
        usage=quota_environment,
        identity=identity,
        requests=[],
        observers=[],
        closed=[],
        behavior=None,
        configure=None,
        before_consume=None,
        close_failure=False,
        released=threading.Event(),
    )

    def acquire():
        state.released.clear()

        def consume():
            if state.before_consume:
                state.before_consume()
            state.usage["calls"] += 1

        return SimpleNamespace(limits=SimpleNamespace(enabled=True), consume_call=consume, release=state.released.set)

    monkeypatch.setattr(model_runtime, "acquire_model_slot", acquire)

    def factory(settings, current, row, prompt):
        def create(**kwargs):
            state.requests.append((row["sequence"], copy.deepcopy(kwargs)))
            return state.behavior(row["sequence"], kwargs) if state.behavior else response()

        def close():
            state.closed.append(row["sequence"])
            if state.close_failure:
                raise OSError("SECRET")

        sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=close)
        observer = runner.engine.RecordingSDK(sdk, current, row, prompt)
        state.observers.append(observer)
        if state.configure:
            state.configure(observer)
        client = runner.engine._governed_runtime(
            completion_client=observer,
            model_name=settings["model"],
            provider="deepseek",
            is_local=False,
            timeout_seconds=settings["timeout_seconds"],
        )
        return client, observer

    state.factory = factory
    state.run = lambda: runner.execute(bundle, settings, guard, factory=factory)
    yield state
    quota.restore()


def saved(campaign, name):
    return json.loads((campaign.base / "execution-v1" / name).read_bytes())


def test_flags_precede_bundle_and_environment(monkeypatch):
    monkeypatch.setattr(runner, "_load_bundle", lambda *_: pytest.fail("No input/environment without both flags"))
    for flags in ([], ["--run-model"], ["--allow-external-deepseek"]):
        assert runner.main(["run", "--expected-prepared-file-sha256", "0" * 64, *flags]) == 2


def test_bad_bundle_rejected_before_admission(monkeypatch):
    from scripts import evaluate_body_evidence_deepseek as helper

    monkeypatch.setattr(helper, "admit_environment", lambda **_: pytest.fail("No admission after binding failure"))
    monkeypatch.setattr(runner.preparation, "validate_prepared", lambda *_: (_ for _ in ()).throw(ValueError("SECRET")))
    assert (
        runner.main(["run", "--run-model", "--allow-external-deepseek", "--expected-prepared-file-sha256", "0" * 64])
        == 2
    )
    with pytest.raises(runner.RunStopped, match="frozen_binding_failed"):
        runner._load_bundle("bad")


@pytest.mark.parametrize(
    "daily,start,allowed,effective",
    [(0, 6, True, 12), (12, 6, True, 12), (20, 6, True, 12), (6, 6, False, None), (11, 6, False, None)],
)
def test_nonzero_quota_policy_never_raises_positive_limits(
    quota_environment, monkeypatch, daily, start, allowed, effective
):
    monkeypatch.setenv(runner._LIMIT_KEYS[0], str(daily))
    quota_environment["calls"] = start
    if not allowed:
        with pytest.raises(runner.RunStopped, match="quota_configuration"):
            runner.QuotaOverlay()
        assert os.environ[runner._LIMIT_KEYS[0]] == str(daily)
        assert not (runner.PROJECT_ROOT / "output").exists()
        return
    quota = runner.QuotaOverlay()
    quota.apply()
    assert quota.effective.daily_calls == effective and quota.effective.concurrency == 1
    assert quota.snapshot()["starting_sqlite_count"] == start
    quota.restore()
    assert os.environ[runner._LIMIT_KEYS[0]] == str(daily) and os.environ[runner._LIMIT_KEYS[1]] == "0"


@pytest.mark.parametrize(
    "mutation,reason",
    [("usage", "quota_count_changed"), ("day", "quota_configuration"), ("policy", "quota_configuration")],
)
def test_quota_pre_overlay_race_fails_without_mutation(quota_environment, monkeypatch, mutation, reason):
    quota = runner.QuotaOverlay()
    if mutation == "usage":
        quota_environment["calls"] += 1
    elif mutation == "day":
        monkeypatch.setattr(runner.engine, "_today", lambda: "2026-10-02")
    else:
        monkeypatch.setenv(runner._LIMIT_KEYS[0], "6")
    with pytest.raises(runner.RunStopped, match=reason):
        quota.apply()
    assert quota.active is False


def test_real_governed_mock_six_requests_nonzero_counter_and_old_engine_untouched(campaign, monkeypatch):
    from src.model_evidence import text_sha256

    engine = runner.engine
    old_campaign, old_sha = engine.CAMPAIGN, engine.PREPARED_SHA256

    def forbidden(*args, **kwargs):
        pytest.fail("Old orchestration, paths and zero-based checks must not run")

    for name in ("execute", "_paths", "_load_bundle"):
        monkeypatch.setattr(engine, name, forbidden)
    monkeypatch.setattr(engine.ExecutionGuard, "check", forbidden)
    before = (campaign.base / "prepared.json").read_bytes()
    result = campaign.run()
    assert result["stop_reason"] is None and len(campaign.requests) == 6
    assert result["quota_end"]["calls"] == 12 and result["quota_end"]["campaign_allowances"] == 6
    assert result["quota_policy"]["starting_sqlite_count"] == 6
    assert all(row["status"] == "generated" for row in result["rows"])
    assert engine.CAMPAIGN == old_campaign and engine.PREPARED_SHA256 == old_sha
    for row, (sequence, request) in zip(result["rows"], campaign.requests):
        case = next(case for case in campaign.bundle["cases"] if case["case_id"] == row["case_id"])
        prompt = case["arms"][row["arm"]]["prompt"]
        assert request["messages"][1]["content"] == prompt.strip()
        assert request["top_p"] == 0.8 and request["temperature"] == 0.2 and request["max_tokens"] == 2300
        assert request["extra_body"] == {"thinking": {"type": "disabled"}} and request["stream"] is False
        assert set(request) == {"model", "messages", "temperature", "top_p", "max_tokens", "extra_body", "stream"}
        capture = saved(campaign, f"request-{sequence:02}.json")
        assert capture["frozen_prompt_sha256"] == text_sha256(prompt)
        assert capture["submitted_user_sha256"] == text_sha256(prompt.strip()) != text_sha256(prompt)
        details = saved(campaign, f"response-details-{sequence:02}.json")
        assert details["model_evidence"]["status"] == "captured"
        assert details["provider_returned_model"] == "synthetic-provider-returned-alias"
        assert details["provider_effective_parameters"] is None
    assert (campaign.base / "prepared.json").read_bytes() == before
    assert not (campaign.base.parent / old_campaign).exists()


def test_main_uses_runtime_mock_factory_and_restores_overlay(campaign, monkeypatch):
    import openai

    from scripts import evaluate_body_evidence_deepseek as helper

    monkeypatch.setattr(openai, "OpenAI", lambda **_: pytest.fail("Real SDK forbidden"))
    monkeypatch.setattr(runner, "_load_bundle", lambda _: campaign.bundle)
    monkeypatch.setattr(helper, "admit_environment", lambda **_: campaign.settings)
    monkeypatch.setattr(runner, "QuotaOverlay", lambda: campaign.quota)
    monkeypatch.setattr(campaign.quota, "apply", lambda: None)
    monkeypatch.setattr(runner, "_client", campaign.factory)
    assert (
        runner.main(
            [
                "run",
                "--run-model",
                "--allow-external-deepseek",
                "--expected-prepared-file-sha256",
                campaign.guard.expected,
            ]
        )
        == 0
    )
    assert len(campaign.requests) == 6 and os.environ[runner._LIMIT_KEYS[0]] == "0"


@pytest.mark.parametrize(
    "field,reason",
    [
        ("sources", "source_drift"),
        ("new_experiment_files", "source_drift"),
        ("dependencies", "dependency_drift"),
        ("settings", "configuration_drift"),
        ("effective", "configuration_drift"),
    ],
)
def test_identity_drift_after_return_stops_next_request(campaign, field, reason):
    def behavior(*_):
        campaign.identity[field]["fixture"] = "changed"
        return response()

    campaign.behavior = behavior
    result = campaign.run()
    assert result["stop_reason"] == reason and len(campaign.requests) == 1
    assert all(row["status"] == "not_run" for row in result["rows"][1:])


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("key", "credential_drift"),
        ("day", "quota_day_changed"),
        ("extra", "quota_count_changed"),
        ("unavailable", "quota_unavailable"),
        ("limits", "quota_configuration"),
        ("packet", "frozen_binding_failed"),
        ("file", "frozen_binding_failed"),
    ],
)
def test_real_guard_rejects_runtime_drift(campaign, monkeypatch, mutation, reason):
    def behavior(*_):
        if mutation == "key":
            monkeypatch.setenv("DEEPSEEK_API_KEY", "another-synthetic-key")
        elif mutation == "day":
            monkeypatch.setattr(runner.engine, "_today", lambda: "2026-10-02")
        elif mutation == "extra":
            campaign.usage["calls"] += 1
        elif mutation == "unavailable":
            campaign.usage["status"] = "unavailable"
        elif mutation == "limits":
            monkeypatch.setenv(runner._LIMIT_KEYS[0], "99")
        elif mutation == "packet":
            campaign.bundle["cases"][0]["review"]["items"][0]["question"] = "changed"
        else:
            (campaign.base / "prepared.json").write_bytes(b"changed")
        return response()

    campaign.behavior = behavior
    result = campaign.run()
    assert result["stop_reason"] == reason and len(campaign.requests) == 1
    assert "synthetic-test-key" not in json.dumps(result)


@pytest.mark.parametrize(
    "path",
    [
        "src/report_template.py",
        "src/rag/context.py",
        "scripts/run_scoped_basis_comparison.py",
        "scripts/evaluate_body_evidence_deepseek.py",
        "tests/test_citation_criteria_comparison.py",
        "tests/test_run_citation_criteria_comparison.py",
    ],
)
def test_validation_to_guard_source_drift_cannot_be_adopted_as_baseline(campaign, path):
    field = "new_experiment_files" if path in campaign.identity["new_experiment_files"] else "sources"
    campaign.identity[field][path] = "modified after prepared validation"
    with pytest.raises(runner.RunStopped, match="source_drift"):
        runner.ExecutionGuard(campaign.settings, campaign.bundle, campaign.guard.expected, campaign.quota)
    assert campaign.requests == [] and not (campaign.base / "campaign.calls.jsonl").exists()


def test_validation_to_guard_packet_mutation_is_not_adopted(campaign):
    campaign.bundle["cases"][0]["review"]["items"][0]["question"] = "changed"
    with pytest.raises(runner.RunStopped, match="frozen_binding_failed"):
        runner.ExecutionGuard(campaign.settings, campaign.bundle, campaign.guard.expected, campaign.quota)
    assert campaign.requests == [] and not (campaign.base / "campaign.calls.jsonl").exists()


def test_unexpected_initial_src_inventory_is_rejected(campaign):
    campaign.identity["sources"]["src/unapproved.py"] = "new source"
    with pytest.raises(runner.RunStopped, match="source_drift"):
        runner.ExecutionGuard(campaign.settings, campaign.bundle, campaign.guard.expected, campaign.quota)
    assert campaign.requests == []


def test_capture_failure_preserves_provider_object(campaign, monkeypatch):
    from src import model_evidence

    monkeypatch.setattr(model_evidence, "capture_model_evidence", lambda *a, **k: {"status": "unavailable"})
    result = campaign.run()
    assert result["stop_reason"] == "capture_failed" and len(campaign.requests) == 1
    assert saved(campaign, "response-01.json")["raw_response"]["choices"]


def test_existing_new_claim_blocks_without_touching_old_claim(campaign):
    claim = campaign.base / "campaign.calls.jsonl"
    claim.write_bytes(b"immutable prior claim\n")
    old = campaign.base.parent / runner.engine.CAMPAIGN
    old.mkdir()
    old_claim = old / "campaign.calls.jsonl"
    old_claim.write_bytes(b"closed old claim\n")
    with pytest.raises(runner.RunStopped, match="campaign_already_claimed"):
        campaign.run()
    assert campaign.requests == [] and claim.read_bytes() == b"immutable prior claim\n"
    assert old_claim.read_bytes() == b"closed old claim\n"


def test_initial_claim_io_failure_has_no_sdk_or_false_claim(campaign, monkeypatch):
    from pathlib import Path

    original = Path.open

    def failed(path, *args, **kwargs):
        if path.name == "campaign.calls.jsonl":
            raise OSError("SECRET")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failed)
    with pytest.raises(OSError):
        campaign.run()
    assert campaign.requests == [] and not (campaign.base / "campaign.calls.jsonl").exists()


def test_first_length_failure_retained_when_client_close_also_fails(campaign):
    campaign.close_failure = True
    campaign.behavior = lambda *_: response("length")
    result = campaign.run()
    assert result["stop_reason"] == "length" and "client_close_failed" in result["secondary_errors"]
    assert len(campaign.requests) == 1


def test_wrong_cell_stops_before_sdk(campaign):
    campaign.configure = lambda observer: observer.row.update(arm="candidate")
    result = campaign.run()
    assert result["stop_reason"] == "wrong_cell" and campaign.requests == []


def test_rebound_observer_prompt_is_rejected(campaign):
    from src.model_evidence import EvidencePrompt

    def configure(observer):
        observer.prompt = EvidencePrompt(str(observer.prompt) + "suffix", assembly=observer.prompt.assembly)

    campaign.configure = configure
    result = campaign.run()
    assert result["stop_reason"] == "frozen_binding_failed" and campaign.requests == []


@pytest.mark.parametrize(
    "field,value", [("temperature", 1), ("top_p", 1), ("max_tokens", 99), ("stream", True), ("seed", 1), ("tools", [])]
)
def test_actual_parameter_drift_blocks_dispatch(campaign, field, value):
    def configure(observer):
        original = observer.chat.completions.create

        def changed(**kwargs):
            kwargs[field] = value
            return original(**kwargs)

        observer.chat.completions.create = changed

    campaign.configure = configure
    result = campaign.run()
    assert result["stop_reason"] == "request_parameters_changed" and campaign.requests == []
    assert campaign.usage["calls"] == 7


def test_double_dispatch_and_repeat_claim_cannot_add_requests(campaign):
    def behavior(_sequence, kwargs):
        return campaign.observers[0].create(**kwargs)

    campaign.behavior = behavior
    result = campaign.run()
    assert result["stop_reason"] == "duplicate_dispatch" and len(campaign.requests) == 1
    # Model the next independent CLI's read-only preflight at the new base count.
    campaign.quota.start = 7
    with pytest.raises(runner.RunStopped, match="campaign_already_claimed"):
        campaign.run()
    assert len(campaign.requests) == 1


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("length", "length"),
        ("null_message", "protocol_failure"),
        ("metadata", "capture_failed"),
        ("transport", "transport"),
    ],
)
def test_bad_responses_are_durable_and_no_next_request(campaign, kind, reason):
    raw = {"choices": [{"message": None, "finish_reason": "stop"}]}

    def behavior(*_):
        if kind == "transport":
            raise ConnectionError("SECRET")
        if kind == "length":
            return response("length")
        if kind == "metadata":
            raw.update(choices=[{"message": {"content": "text"}, "finish_reason": "stop"}], usage="bad")
        return SimpleNamespace(model_dump=lambda **_: copy.deepcopy(raw))

    campaign.behavior = behavior
    result = campaign.run()
    assert result["stop_reason"] == reason and len(campaign.requests) == 1
    captured = saved(campaign, "response-01.json")
    if kind in {"null_message", "metadata"}:
        assert captured["raw_response"] == raw
    assert all(row["status"] == "not_run" for row in result["rows"][1:])
    assert "SECRET" not in json.dumps(result) + json.dumps(captured)


@pytest.mark.parametrize(
    "filename,calls",
    [
        ("snapshot.json", 0),
        ("request-01.json", 0),
        ("response-01.json", 1),
        ("response-details-01.json", 1),
        ("result-01.json", 1),
        ("results.json", 6),
    ],
)
def test_io_failure_stops_preserves_claim_and_reports_incomplete(campaign, monkeypatch, filename, calls):
    original = runner.engine._write_once

    def failure(path, value):
        if path.name == filename:
            raise OSError("SECRET")
        return original(path, value)

    monkeypatch.setattr(runner.engine, "_write_once", failure)
    result = campaign.run()
    assert result["stop_reason"] == "recording_failed" and result["recording_incomplete"]
    assert len(campaign.requests) == calls and len(result["rows"]) == 6
    assert (campaign.base / "campaign.calls.jsonl").exists()
    if filename == "response-details-01.json":
        assert saved(campaign, "response-01.json")["raw_response"]


@pytest.mark.parametrize(
    "kind,reason,calls",
    [("append", "journal_failed", 0), ("close", "journal_close_failed", 6), ("client", "client_close_failed", 1)],
)
def test_journal_and_close_failures_stop(campaign, monkeypatch, kind, reason, calls):
    if kind == "client":
        campaign.close_failure = True
    elif kind == "append":
        original = runner.engine.Journal.append

        def append(self, event, **values):
            if event == "allowance_consumed":
                raise OSError("SECRET")
            return original(self, event, **values)

        monkeypatch.setattr(runner.engine.Journal, "append", append)
    else:
        original = runner.engine.Journal.close

        def close(self):
            original(self)
            raise OSError("SECRET")

        monkeypatch.setattr(runner.engine.Journal, "close", close)
    result = campaign.run()
    assert result["stop_reason"] == reason and len(campaign.requests) == calls


@pytest.mark.parametrize("where,calls", [("sdk", 1), ("before_consume", 0)])
def test_timeout_overlay_stays_finite_late_worker_cannot_dispatch_or_promote(campaign, monkeypatch, where, calls):
    entered, release = threading.Event(), threading.Event()
    campaign.settings["timeout_seconds"] = 0.05
    original_start = threading.Thread.start

    def start(thread):
        original_start(thread)
        if thread.name == "governed-model-completion":
            assert entered.wait(3)

    monkeypatch.setattr(threading.Thread, "start", start)

    def behavior(*_):
        entered.set()
        assert release.wait(3)
        return response()

    if where == "sdk":
        campaign.behavior = behavior
    else:

        def configure(observer):
            original = observer.with_options

            def delay(**kwargs):
                behavior()
                return original(**kwargs)

            observer.with_options = delay

        campaign.configure = configure
    try:
        result = campaign.run()
        assert result["stop_reason"] == "timeout" and result["rows"][0]["worker_pending"]
        assert result["overlay_retained_until_cli_exit"] and campaign.closed == []
        campaign.quota.restore()
        assert os.environ[runner._LIMIT_KEYS[0]] == "12" and os.environ[runner._LIMIT_KEYS[1]] == "1"
        frozen = (campaign.base / "execution-v1/results.json").read_bytes()
        ledger = (campaign.base / "campaign.calls.jsonl").read_bytes()
    finally:
        release.set()
        assert campaign.released.wait(3)
    assert len(campaign.requests) == calls and campaign.closed == [1]
    assert (campaign.base / "execution-v1/results.json").read_bytes() == frozen
    assert (campaign.base / "campaign.calls.jsonl").read_bytes() == ledger
    assert all(row["status"] == "not_run" for row in result["rows"][1:])
    if calls:
        assert saved(campaign, "response-01.json")["after_stop"] is True
