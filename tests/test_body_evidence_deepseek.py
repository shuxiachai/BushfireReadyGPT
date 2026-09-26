"""Network-free, synthetic-only coverage for the optional external comparison."""

import copy
import json
from types import SimpleNamespace

import pytest

from scripts import evaluate_body_evidence_ab as local
from scripts import evaluate_body_evidence_deepseek as remote
from src import report_generation_quality as quality
from src.model_evidence import json_sha256
from src.model_response import ModelResponseError, ModelServiceError
from tests.test_body_evidence_experiment import analysis_fixture, mock_client, report_fixture, scenario_fixture


@pytest.fixture
def settings(monkeypatch):
    for key, value in {
        "LLM_PROVIDER": "deepseek",
        "BUSHFIRE_ALLOW_EXTERNAL_MODEL": "true",
        "DEEPSEEK_API_KEY": "synthetic-test-key",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "BUSHFIRE_MODEL_MAX_TOKENS": "2300",
        "BUSHFIRE_MODEL_TEMPERATURE": "0.2",
        "BUSHFIRE_MODEL_TIMEOUT_SECONDS": "180",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    return remote._settings()


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path / "synthetic-project"
    (root / "src").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "src/test_source.py").write_text("# Frozen synthetic source\n", encoding="utf-8")
    for name in ("body_evidence_experiment.py", "evaluate_body_evidence_ab.py"):
        (root / "scripts" / name).write_text("# Frozen synthetic runner\n", encoding="utf-8")
    pilot_path = root / remote.PILOT_PATH
    pilot_path.parent.mkdir(parents=True)
    payload = {
        "schema": local.SCENARIO_SCHEMA,
        "phase": "seen_pilot",
        "candidate": "claim_pair_v1",
        "target_sections": [7, 11, 12],
        "cases": [scenario_fixture("one"), scenario_fixture("two")],
    }
    pilot_path.write_text(json.dumps(payload), encoding="utf-8")
    origin = {
        "scenario_path": str(pilot_path),
        "scenario_sha256": remote.sha256_file(pilot_path),
        "source_files_sha256": remote._source_hashes(root),
        "quality_policy": quality.quality_policy_metadata(),
        "model": {"provider": "ollama", "name": "synthetic-historical-model"},
    }
    bundle = local.prepare_bundle(
        payload, pilot_path, analyse=lambda *_: analysis_fixture(), provenance=lambda _: origin
    )
    prepared_path = root / "prepared.json"
    prepared_path.write_text(json.dumps(bundle), encoding="utf-8")
    return root, prepared_path, remote.sha256_file(prepared_path), bundle


@pytest.fixture
def journal(tmp_path):
    with (tmp_path / "calls.jsonl").open("x", encoding="utf-8") as handle:
        yield remote.CallJournal(handle)


def test_flags_precede_dotenv_config_and_client():
    with pytest.raises(remote.ExperimentBlocked, match="explicit_external_run_flags"):
        remote.admit_environment(
            run_model=False,
            allow_external_deepseek=True,
            dotenv_loader=lambda *_args, **_kwargs: pytest.fail("Must not read dotenv"),
        )


def test_dotenv_is_explicit_and_never_overrides_process_settings(settings):
    calls = []
    result = remote.admit_environment(
        run_model=True,
        allow_external_deepseek=True,
        model_arg="explicit-model",
        dotenv_loader=lambda path, **kwargs: calls.append((path, kwargs)),
    )
    assert calls == [(remote.PROJECT_ROOT / ".env", {"override": False})]
    assert result["model"] == "explicit-model" and result["model_selection_source"] == "cli"
    assert "synthetic-test-key" not in json.dumps(result)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.deepseek.com",
        "https://api.deepseek.com.evil.test",
        "https://user:key@api.deepseek.com",
        "https://api.deepseek.com:443",
        "https://api.deepseek.com?x=1",
        "https://api.deepseek.com/#x",
        "https://api.deepseek.com/v1/other",
        "https://API.DEEPSEEK.COM",
        " https://api.deepseek.com",
    ],
)
def test_strict_endpoint_rejection(settings, monkeypatch, endpoint):
    monkeypatch.setenv("DEEPSEEK_BASE_URL", endpoint)
    with pytest.raises(remote.ExperimentBlocked, match="endpoint_not_allowlisted"):
        remote._settings()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.deepseek.com",
        "https://api.deepseek.com/",
        "https://api.deepseek.com/v1",
        "https://api.deepseek.com/v1/",
    ],
)
def test_supported_endpoint_normalization(settings, monkeypatch, endpoint):
    monkeypatch.setenv("DEEPSEEK_BASE_URL", endpoint)
    assert remote._settings()["endpoint"] == endpoint.rstrip("/")


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("LLM_PROVIDER", "ollama", "explicit_deepseek_provider_required"),
        ("BUSHFIRE_ALLOW_EXTERNAL_MODEL", "false", "external_model_acknowledgement_required"),
        ("DEEPSEEK_API_KEY", "", "deepseek_credential_missing"),
        ("BUSHFIRE_MODEL_MAX_TOKENS", "4600", "invalid_model_configuration"),
    ],
)
def test_admission_has_no_implicit_fallback(settings, monkeypatch, field, value, code):
    monkeypatch.setenv(field, value)
    with pytest.raises(remote.ExperimentBlocked, match=code):
        remote._settings()


def test_fixed_pilot_and_original_sources_are_immutable(prepared):
    root, path, digest, bundle = prepared
    assert remote.load_seen_pilot(path, digest, root=root) == bundle
    before = path.read_bytes()
    (root / "src/test_source.py").write_text("# Changed\n", encoding="utf-8")
    with pytest.raises(remote.ExperimentBlocked, match="historical_source_binding_mismatch"):
        remote.load_seen_pilot(path, digest, root=root)
    assert path.read_bytes() == before


def test_holdout_rejected_before_legacy_validator_reads_any_path(prepared, monkeypatch):
    root, path, _, bundle = prepared
    bundle["phase"] = "sealed_holdout"
    bundle["provenance_end"]["scenario_path"] = str(root / "must-never-be-read.json")
    path.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setattr(remote, "validate_prepared", lambda _: pytest.fail("Holdout reached legacy validator"))
    with pytest.raises(remote.ExperimentBlocked, match="only_two_case_seen_pilot"):
        remote.load_seen_pilot(path, remote.sha256_file(path), root=root)


def test_nonpilot_path_rejected_before_legacy_validator(prepared, monkeypatch):
    root, path, _, bundle = prepared
    bundle["provenance_end"]["scenario_path"] = str(root / "must-never-be-read.json")
    path.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setattr(remote, "validate_prepared", lambda _: pytest.fail("Wrong path reached legacy validator"))
    with pytest.raises(remote.ExperimentBlocked, match="fixed_pilot_path"):
        remote.load_seen_pilot(path, remote.sha256_file(path), root=root)


def test_expected_file_hash_is_not_recomputed_as_authority(prepared):
    root, path, _, _ = prepared
    with pytest.raises(remote.ExperimentBlocked, match="prepared_file_hash_mismatch"):
        remote.load_seen_pilot(path, "0" * 64, root=root)


def test_independent_sdk_has_zero_retries_tls_and_no_proxy_or_redirects(settings):
    kwargs = {}
    config = SimpleNamespace(
        LLM_PROVIDER="deepseek",
        MODEL_MAX_TOKENS=2300,
        MODEL_TEMPERATURE=0.2,
        MODEL_TIMEOUT_SECONDS=180,
        MODEL_ENDPOINT="https://api.deepseek.com",
    )

    def sdk_factory(**values):
        kwargs["sdk"] = values
        return SimpleNamespace()

    runtime, _ = remote.build_client(
        settings,
        config=config,
        sdk_factory=sdk_factory,
        http_factory=lambda **values: kwargs.setdefault("http", values),
        runtime_factory=lambda **values: SimpleNamespace(**values),
    )
    assert kwargs["http"] == {"verify": True, "follow_redirects": False, "trust_env": False}
    assert kwargs["sdk"]["max_retries"] == 0
    assert runtime.provider == "deepseek" and runtime.is_local is False
    assert runtime.model_name == "deepseek-v4-flash"


def test_governed_deepseek_request_keeps_limits_thinking_and_no_seed(settings):
    from src.model_runtime import GovernedModelClient

    sent = []

    def create(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Completed draft."), finish_reason="stop")]
        )

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    runtime = GovernedModelClient(
        completion_client=sdk, provider="deepseek", is_local=False, model_name=settings["model"]
    )
    assert runtime.generate("Synthetic request") == "Completed draft."
    assert sent[0]["max_tokens"] == 2300 and sent[0]["top_p"] == 0.8
    assert sent[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "seed" not in sent[0]


def test_complete_mock_run_preserves_origin_and_all_denominators(prepared, settings, journal, monkeypatch):
    bundle, calls = prepared[3], []
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": True}})
    result = remote.run_comparison(
        bundle,
        settings,
        journal,
        provenance=lambda: {"stable": True},
        client_factory=lambda: (
            mock_client(report_fixture(analysis_fixture()), calls),
            SimpleNamespace(close=lambda: None),
        ),
    )
    assert result["valid"] and result["attempted_calls"] == len(calls) == 4
    assert result["historical_input_origin"] == bundle
    assert bundle["provenance_end"]["model"]["provider"] == "ollama"
    assert result["not_run_arms"] == 0 and result["semantic_accuracy"] is None
    assert all(summary["total_arms"] == 2 for summary in result["summaries"].values())
    assert [e["event"] for e in journal.entries] == ["before_call", "after_call"] * 4
    assert all(set(e) <= remote._JOURNAL_FIELDS for e in journal.entries)


@pytest.mark.parametrize(
    "error,reason",
    [
        (ModelServiceError("synthetic-sensitive-provider-message"), "service_or_deadline_failure"),
        (TimeoutError("synthetic-sensitive-provider-message"), "timeout"),
        (ConnectionError("synthetic-sensitive-provider-message"), "transport"),
    ],
)
def test_fatal_errors_stop_entire_batch_and_preserve_unrun_arms(prepared, settings, journal, error, reason):
    calls = []

    def generate(_prompt):
        calls.append(True)
        assert journal.entries[-1]["event"] == "before_call"
        raise error

    result = remote.run_comparison(
        prepared[3],
        settings,
        journal,
        provenance=lambda: {},
        client_factory=lambda: (SimpleNamespace(generate=generate, last_request_capture=None), None),
    )
    assert len(calls) == result["attempted_calls"] == 1
    assert result["fatal_stop_reason"] == reason and result["not_run_arms"] == 3
    assert all(summary["total_arms"] == 2 for summary in result["summaries"].values())
    assert "synthetic-sensitive-provider-message" not in json.dumps(result)


def test_retryable_protocol_rejection_journal_failure_stops_batch(prepared, settings, journal, monkeypatch):
    original = journal.append
    calls = []

    def append(**entry):
        if entry["event"] == "after_call":
            raise OSError("Synthetic journal failure")
        original(**entry)

    def generate(_prompt):
        calls.append(True)
        raise ModelResponseError("length")

    monkeypatch.setattr(journal, "append", append)
    result = remote.run_comparison(
        prepared[3],
        settings,
        journal,
        provenance=lambda: {},
        client_factory=lambda: (SimpleNamespace(generate=generate, last_request_capture=None), None),
    )
    assert len(calls) == result["attempted_calls"] == 1
    assert result["fatal_stop_reason"] == "journal_write_failed" and result["not_run_arms"] == 3


def test_budget_is_shared_and_remaining_arms_are_not_run(prepared, settings, journal, monkeypatch):
    calls = []
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": True}})
    result = remote.run_comparison(
        prepared[3],
        settings,
        journal,
        max_calls=1,
        provenance=lambda: {},
        client_factory=lambda: (mock_client(report_fixture(analysis_fixture()), calls), None),
    )
    assert len(calls) == result["attempted_calls"] == 1 and result["not_run_arms"] == 3
    assert result["fatal_stop_reason"] == "call_budget_exhausted"


def test_pre_call_provenance_drift_stops_without_submission(prepared, settings, journal):
    checks = iter([{"source": "before"}, {"source": "after"}])

    def provenance():
        return next(checks, {"source": "after"})

    result = remote.run_comparison(
        prepared[3],
        settings,
        journal,
        provenance=provenance,
        client_factory=lambda: (SimpleNamespace(generate=lambda _: pytest.fail("No model after drift")), None),
    )
    assert result["attempted_calls"] == 0 and result["fatal_stop_reason"] == "provenance_drift"
    assert journal.entries == []


def test_journal_rejects_payload_and_output_names_do_not_change_claim_path(journal, tmp_path):
    with pytest.raises(remote.ExperimentBlocked, match="journal_field_not_allowlisted"):
        journal.append(event="before_call", prompt="never persist")
    digest = "a" * 64
    assert remote.journal_path(digest, root=tmp_path) == remote.journal_path(digest.upper(), root=tmp_path)


def test_cli_no_clobber_and_duplicate_journal_block(prepared, settings, tmp_path, monkeypatch):
    root, prepared_path, digest, bundle = prepared
    monkeypatch.setattr(remote, "admit_environment", lambda **_: settings)
    monkeypatch.setattr(remote, "load_seen_pilot", lambda *_: bundle)
    ledger = tmp_path / "one-run.calls.jsonl"
    monkeypatch.setattr(remote, "journal_path", lambda _: ledger)
    monkeypatch.setattr(remote, "run_comparison", lambda *_args, **_kwargs: pytest.fail("No model call"))
    output = tmp_path / "existing.json"
    output.write_text("preserve", encoding="utf-8")
    argv = [
        "--prepared",
        str(prepared_path),
        "--expected-prepared-file-sha256",
        digest,
        "--run-model",
        "--allow-external-deepseek",
        "--output",
        str(output),
    ]
    assert remote.main(argv) == 2 and output.read_text(encoding="utf-8") == "preserve"
    assert not ledger.exists()
    ledger.write_text("existing run claim\n", encoding="utf-8")
    argv[-1] = str(tmp_path / "different-new-output.json")
    assert remote.main(argv) == 2
    assert ledger.read_text(encoding="utf-8") == "existing run claim\n"


def test_execution_settings_and_inputs_have_no_key_hash(settings, prepared):
    safe = copy.deepcopy(settings)
    assert safe["immutable_model_digest"] is None and safe["usage"] is None and safe["seed_sent"] is False
    assert "synthetic-test-key" not in json.dumps(safe)
    assert json_sha256(prepared[3]["cases"][0]["analysis"]) == prepared[3]["cases"][0]["analysis_sha256"]


def test_current_dependency_identity_is_separate_from_historical_origin(tmp_path):
    definition = tmp_path / "pyproject.toml"
    definition.write_text("# Synthetic dependency definition\n", encoding="utf-8")
    before = remote.dependency_identity(tmp_path)
    assert before["python"] and before["openai"] and before["httpx"]
    assert before["definition_files_sha256"]["pyproject.toml"] == remote.sha256_file(definition)
    definition.write_text("# Changed dependency definition\n", encoding="utf-8")
    assert remote.dependency_identity(tmp_path) != before


def test_empty_explicit_model_does_not_silently_fall_back(settings):
    with pytest.raises(remote.ExperimentBlocked, match="invalid_model_name"):
        remote._settings("")


def test_retryable_protocol_uses_shared_budget_and_preserves_capture(prepared, settings, journal, monkeypatch):
    calls, invoked = [], []
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": True}})

    def factory():
        client = mock_client(report_fixture(analysis_fixture()), calls)
        original = client.generate

        def generate(prompt):
            invoked.append(prompt)
            if len(invoked) == 1:
                raise ModelResponseError("length")
            return original(prompt)

        client.generate = generate
        return client, None

    result = remote.run_comparison(prepared[3], settings, journal, provenance=lambda: {}, client_factory=factory)
    assert result["valid"] and result["fatal_stop_reason"] is None
    assert result["attempted_calls"] == len(invoked) == 5 and len(calls) == 4
    first = result["rows"][0]
    assert first["generation_attempts"] == 2 and first["capture_valid"]
    assert [attempt["request_kind"] for attempt in first["attempts"]] == ["initial", "protocol_retry"]
    assert first["final"]["model_evidence"]["status"] == "captured"
    assert journal.entries[1]["outcome"] == "retryable_protocol_rejection"
