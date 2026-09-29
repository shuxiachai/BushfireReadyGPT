import json
from types import SimpleNamespace

import pytest

from scripts import section_scope_comparison as comparison
from src.model_evidence import json_sha256, text_sha256
from src.model_limits import ModelLimits


@pytest.fixture
def bundle():
    return comparison.prepare_bundle()


def test_prepare_is_synthetic_offline_and_matches_old_git_builder(monkeypatch):
    import dotenv

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline preparation must not load dotenv or build a model client")

    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    monkeypatch.setattr(comparison, "build_client", forbidden)
    prepared = comparison.prepare_bundle()
    assert len(prepared["cases"]) == 3
    assert [len(case["synthetic_evidence"]) for case in prepared["cases"]] == [1, 2, 0]
    assert "Synthetic evidence" in prepared["limitations"]
    assert prepared["baseline_commit"].startswith("3a00f3c")
    assert prepared["current_commit"].startswith("f4ae47c")
    for case in prepared["cases"]:
        assert case["analysis_sha256"] == json_sha256(case["inputs"]["analysis"])
        for variant, prompt in case["prompts"].items():
            assert case["prompt_sha256"][variant] == text_sha256(prompt)
            for passage in case["synthetic_evidence"]:
                assert passage["text"] in prompt
                assert passage["citation_token"] in prompt
                assert passage["chunk_sha256"] == text_sha256(passage["text"])


def test_loading_rejects_modified_prompt_even_with_updated_external_hash(bundle, monkeypatch, tmp_path):
    monkeypatch.setattr(comparison, "OUTPUT", tmp_path)
    bundle["cases"][0]["prompts"]["baseline"] += "Unexpected extra instructions"
    comparison._write(tmp_path / "prepared.json", bundle)
    with pytest.raises(comparison.ExperimentBlocked, match="frozen_input_or_source_drift"):
        comparison._load_prepared(comparison.sha256_file(tmp_path / "prepared.json"))


@pytest.mark.parametrize("daily,concurrency", [(0, 0), (7, 1), (6, 0), (6, 2)])
def test_quota_must_be_bounded_without_reconfiguration(monkeypatch, daily, concurrency):
    import src.model_limits as limits_module

    limits = ModelLimits(concurrency, daily, comparison.PROJECT_ROOT / "chat_history/model-usage.sqlite3", False)
    monkeypatch.setattr(limits_module, "load_model_limits", lambda: limits)
    with pytest.raises(comparison.ExperimentBlocked, match="bounded_shared_quota_required"):
        comparison.quota_preflight()


def test_quota_reads_remaining_and_allows_normal_first_initialization(monkeypatch):
    import src.model_limits as limits_module

    limits = ModelLimits(1, 6, (comparison.PROJECT_ROOT / "chat_history/model-usage.sqlite3").resolve(), False)
    monkeypatch.setattr(limits_module, "load_model_limits", lambda: limits)
    monkeypatch.setattr(limits_module, "read_model_usage", lambda **kwargs: {"status": "ready", "calls": 2})
    assert comparison.quota_preflight()["remaining"] == 4
    monkeypatch.setattr(
        limits_module, "read_model_usage", lambda **kwargs: {"status": "not_initialized", "calls": None}
    )
    assert comparison.quota_preflight()["remaining"] is None
    monkeypatch.setattr(limits_module, "read_model_usage", lambda **kwargs: {"status": "unavailable", "calls": None})
    with pytest.raises(comparison.ExperimentBlocked, match="shared_quota_unavailable"):
        comparison.quota_preflight()


def test_capture_precedes_governed_admission_and_with_options_cannot_retry(tmp_path):
    raw = {
        "choices": [{"message": {"content": "Truncated raw response"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model_dump=lambda **kwargs: raw)

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    sdk.with_options = lambda **kwargs: sdk
    request = {"messages": [{"role": "system", "content": "System"}, {"role": "user", "content": "Synthetic"}]}
    with (tmp_path / "journal.jsonl").open("x") as journal:
        recorder = comparison.RecordingSDK(sdk, tmp_path, 1, journal)
        recorder.with_options(max_retries=0).create(**request)
        with pytest.raises(comparison.ExperimentBlocked, match="duplicate_sdk_submission_rejected"):
            recorder.create(**request)
    assert len(calls) == 1
    recorded = json.loads((tmp_path / "response-01.json").read_text())
    assert recorded["raw_response"] == raw
    assert json.loads((tmp_path / "request-01.json").read_text())["request"] == request
    assert "sdk_submission" in (tmp_path / "journal.jsonl").read_text()


def test_transport_errors_record_only_fixed_reason_codes(tmp_path, monkeypatch):
    def create(**kwargs):
        raise ConnectionError("SECRET_MARKER provider credential URL")

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with (tmp_path / "journal.jsonl").open("x") as journal:
        recorder = comparison.RecordingSDK(sdk, tmp_path, 1, journal)
        with pytest.raises(ConnectionError):
            recorder.create(
                messages=[{"role": "system", "content": "System"}, {"role": "user", "content": "Synthetic"}]
            )
    response = (tmp_path / "response-01.json").read_text()
    assert "SECRET_MARKER" not in response
    assert json.loads(response)["error_code"] == "transport"


def test_six_single_initial_calls_interleave_without_repairs(bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(comparison, "OUTPUT", tmp_path)
    seen = []

    class FakeClient:
        last_request_capture = None

        def generate(self, prompt):
            seen.append(prompt)
            assert prompt.request_kind == "initial"
            return "Synthetic report"

    with (tmp_path / "journal.jsonl").open("x") as journal:
        result = comparison.run_comparison(bundle, {}, journal, factory=lambda *args: (FakeClient(), None))
    assert len(seen) == result["attempted_governed_calls"] == 6
    assert [row["variant"] for row in result["rows"]] == [
        "baseline",
        "current",
        "current",
        "baseline",
        "baseline",
        "current",
    ]
    assert all(row["model_evidence"]["status"] == "unavailable" for row in result["rows"])


def test_protocol_rejection_is_retained_once_and_stops(bundle, tmp_path, monkeypatch):
    from src.model_response import ModelResponseError

    monkeypatch.setattr(comparison, "OUTPUT", tmp_path)
    count = 0

    class FakeClient:
        def generate(self, prompt):
            nonlocal count
            count += 1
            if count == 1:
                raise ModelResponseError("length")
            raise ConnectionError("SECRET_MARKER")

    with (tmp_path / "journal.jsonl").open("x") as journal:
        result = comparison.run_comparison(bundle, {}, journal, factory=lambda *args: (FakeClient(), None))
    assert count == result["attempted_governed_calls"] == 1
    assert result["stop_reason"] == "protocol_rejected"
    assert [row["status"] for row in result["rows"]] == [
        "failed",
        "not_run",
        "not_run",
        "not_run",
        "not_run",
        "not_run",
    ]
    assert "SECRET_MARKER" not in json.dumps(result)


def _mock_cli(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    output = root / "output" / comparison.CAMPAIGN
    output.mkdir(parents=True)
    monkeypatch.setattr(comparison, "PROJECT_ROOT", root)
    monkeypatch.setattr(comparison, "OUTPUT", output)
    monkeypatch.setattr(comparison, "_load_prepared", lambda expected: {})
    monkeypatch.setattr(comparison, "admit_environment", lambda **kwargs: {})
    monkeypatch.setattr(comparison, "quota_preflight", lambda: {"daily_limit": 6, "remaining": 6})
    return output


def test_fixed_claim_blocks_reopening_even_when_run_failed(monkeypatch, tmp_path, capsys):
    output = _mock_cli(monkeypatch, tmp_path)
    run_calls = []

    def fail(*args, **kwargs):
        run_calls.append(1)
        raise RuntimeError("SECRET_MARKER")

    monkeypatch.setattr(comparison, "run_comparison", fail)
    for _ in range(2):
        assert (
            comparison.main(
                ["run", "--expected-prepared-file-sha256", "a" * 64, "--run-model", "--allow-external-deepseek"]
            )
            == 2
        )
    assert len(run_calls) == 1
    assert (output / "campaign.calls.jsonl").exists()
    assert "SECRET_MARKER" not in capsys.readouterr().out


def test_insufficient_shared_allowance_reports_remaining_without_claim_or_calls(monkeypatch, tmp_path, capsys):
    output = _mock_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(comparison, "quota_preflight", lambda: {"daily_limit": 6, "remaining": 4})
    assert (
        comparison.main(
            ["run", "--expected-prepared-file-sha256", "a" * 64, "--run-model", "--allow-external-deepseek"]
        )
        == 2
    )
    assert not (output / "campaign.calls.jsonl").exists()
    assert json.loads(capsys.readouterr().out)["quota"]["remaining"] == 4


def test_run_requires_explicit_external_flags_before_dotenv(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Must not load dotenv")

    with pytest.raises(comparison.ExperimentBlocked, match="explicit_external_run_flags_required"):
        comparison.admit_environment(run_model=False, allow_external_deepseek=False, dotenv_loader=forbidden)
