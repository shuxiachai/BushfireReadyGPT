"""Pure synthetic fixtures; these tests never read the sealed holdout."""

import copy
import json
from types import SimpleNamespace

import pytest

from scripts import body_evidence_experiment as experiment
from scripts import evaluate_body_evidence_ab as cli
from src import report_generation_quality as quality
from src.model_evidence import (
    EvidencePrompt,
    bind_normalized_narrative,
    capture_model_evidence,
    json_sha256,
    text_sha256,
)
from src.model_runtime import GovernedModelClient
from src.rag.service import assemble_retrieved_context
from src.source_attribution import format_rag_citation_token


def analysis_fixture():
    text = "Families prepare household emergency supplies."
    analysis = {
        "profile": {"state": "Queensland"},
        "knowledge": {
            "status": "ready",
            "retrieved_chunks": [
                {
                    "source_id": "mock-guide",
                    "chunk_id": "mock-guide-1",
                    "title": "Mock preparation guide",
                    "agency": "Synthetic authority",
                    "text": text,
                    "chunk_sha256": text_sha256(text),
                    "jurisdictions": ["Queensland"],
                }
            ],
        },
        "data": {"sources": [{"id": "one", "name": "Mock One"}, {"id": "two", "name": "Mock Two"}]},
    }
    assembly = assemble_retrieved_context(analysis["knowledge"])
    analysis.update(rag_context_assembly=assembly, prompt_context="Synthetic data.\n" + assembly["context"])
    return analysis


def scenario_fixture(identity="mock"):
    return {
        "id": identity,
        "location": "Brisbane QLD",
        "audience": "Community volunteers",
        "scenario": "Preparedness",
        "concerns": [],
        "timeframe": "30 days",
        "extra_context": "Synthetic test",
        "rag_enabled": True,
    }


def report_fixture(analysis, basis=None):
    token = format_rag_citation_token(analysis["knowledge"]["retrieved_chunks"][0])
    basis = basis or f"Families prepare household emergency supplies {token}."
    return "\n\n".join(
        f"## {number}. Synthetic section\nEvidence basis: {basis}\n\n"
        "Local application: Proposed for local review, record the responsible owner."
        for number in experiment.TARGET_SECTIONS
    )


def mock_client(response, calls):
    def create(**kwargs):
        calls.append(copy.deepcopy(list(kwargs["messages"])))
        text = response() if callable(response) else response
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")])

    return GovernedModelClient(
        completion_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="mock",
        is_local=False,
    )


def captured(report, analysis):
    assembly = analysis["rag_context_assembly"]
    prompt = EvidencePrompt(assembly["context"], assembly=assembly)
    client = mock_client(report, [])
    response = client.generate(prompt)
    return bind_normalized_narrative(capture_model_evidence(prompt, client, response, attempt_number=1), report)


def test_variant_is_only_static_suffix_with_independent_metadata():
    analysis = analysis_fixture()
    base = EvidencePrompt("baseline\n" + analysis["prompt_context"], assembly=analysis["rag_context_assembly"])
    baseline = experiment.build_variant_prompt(base, "baseline")
    candidate = experiment.build_variant_prompt(base, "claim_pair_v1")
    assert baseline == base
    assert candidate == str(base) + experiment.LAYOUT_GUIDANCE
    assert candidate.count(base.assembly["context"]) == 1
    candidate.assembly["context"] = "changed"
    assert base.assembly == baseline.assembly == analysis["rag_context_assembly"]


def test_pairs_preserve_standard_body_classifier_and_valid_capture():
    from src.report_claim_evidence import evaluate_body_claim_evidence

    analysis = analysis_fixture()
    report = report_fixture(analysis)
    snapshot = captured(report, analysis)
    body = evaluate_body_claim_evidence(report, analysis, snapshot)
    result = experiment.parse_claim_pairs(report, analysis, snapshot)
    assert result["complete_pairs"] == result["lexically_supported_pairs"] == 3
    assert result["semantic_accuracy"] is None
    assert body == evaluate_body_claim_evidence(report, analysis, snapshot)
    for pair in result["pairs"]:
        span = pair["evidence_basis"]["span"]
        assert report[span["start"] : span["end"]].strip() == pair["evidence_basis"]["text"]


@pytest.mark.parametrize(
    "basis,status,reason",
    [
        ("To be confirmed.", "abstained", "no_evidence_claim_offered"),
        ("Families prepare supplies [O1-RAG][ref=unknown].", "malformed", "unknown_source"),
        ("Families prepare supplies.", "malformed", "missing_citation"),
    ],
)
def test_unknown_missing_and_abstained_are_not_supported(basis, status, reason):
    analysis = analysis_fixture()
    result = experiment.parse_claim_pairs(report_fixture(analysis, basis), analysis)
    assert result["complete_pairs"] == result["lexically_supported_pairs"] == 0
    assert all(row["status"] == status and reason in row["reasons"] for row in result["pairs"])


def test_duplicate_nonadjacent_and_missing_pairs():
    analysis = analysis_fixture()
    report = report_fixture(analysis)
    duplicate = experiment.parse_claim_pairs(report + "\n\n## 7. Duplicate\nText.", analysis)
    assert duplicate["pairs"][0]["status"] == "duplicate"
    nonadjacent = report.replace("\n\nLocal application:", "\n\nIntervening paragraph.\n\nLocal application:")
    assert all(row["status"] == "malformed" for row in experiment.parse_claim_pairs(nonadjacent, analysis)["pairs"])
    assert all(row["status"] == "missing" for row in experiment.parse_claim_pairs("", analysis)["pairs"])


def test_snapshot_absence_never_becomes_lexical_success():
    analysis = analysis_fixture()
    result = experiment.parse_claim_pairs(report_fixture(analysis), analysis)
    assert result["complete_pairs"] == 3
    assert result["lexically_supported_pairs"] == 0
    assert all("snapshot_unavailable" in row["support_reasons"] for row in result["pairs"])


def test_run_arm_captures_actual_variant_then_keeps_full_failed_gate(monkeypatch):
    analysis, calls = analysis_fixture(), []
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": True}})
    result = experiment.run_arm(
        scenario_fixture(), analysis, "claim_pair_v1", mock_client(report_fixture(analysis), calls)
    )
    assert len(calls) == result["model_calls"] == 1
    assert result["status"] == "completed" and result["governed_gate_passed"] is False
    assert result["initial"] and result["final"]
    record = result["attempts"][0]
    assert record["model_evidence"]["status"] == "captured"
    assert record["model_evidence"]["request_binding"]["user_prompt_sha256"] == text_sha256(calls[0][1]["content"])
    assert calls[0][1]["content"].count(experiment.LAYOUT_GUIDANCE.strip()) == 1
    assert "[ref=" in record["admitted_response"]
    assert "[source_id=" in result["final"]["report"]
    assert result["analysis_unchanged"]


def test_real_repair_loop_is_shared_and_bounded(monkeypatch):
    analysis, calls = analysis_fixture(), []
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": False}})
    monkeypatch.setattr(
        quality,
        "build_report_repair_prompt",
        lambda *_, **__: EvidencePrompt(
            "Repair.\n" + analysis["rag_context_assembly"]["context"],
            assembly=analysis["rag_context_assembly"],
            request_kind="structural_repair",
        ),
    )
    result = experiment.run_arm(
        scenario_fixture(), analysis, "claim_pair_v1", mock_client(report_fixture(analysis), calls)
    )
    assert len(calls) == result["generation_attempts"] == 3
    assert all(c[1]["content"].count(experiment.LAYOUT_GUIDANCE.strip()) == 1 for c in calls)
    assert all(record["model_evidence"]["status"] == "captured" for record in result["attempts"])


def test_suffix_cannot_expand_repair_budget(monkeypatch):
    analysis, calls = analysis_fixture(), []
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": False}})
    monkeypatch.setattr(
        quality,
        "build_report_repair_prompt",
        lambda *_, **__: EvidencePrompt(
            "x" * 18000,
            assembly=analysis["rag_context_assembly"],
            request_kind="structural_repair",
        ),
    )
    result = experiment.run_arm(
        scenario_fixture(), analysis, "claim_pair_v1", mock_client(report_fixture(analysis), calls)
    )
    assert result["status"] == "failed" and len(calls) == 1
    assert result["attempts"][1]["error_code"] == "repair_prompt_limit_exceeded"
    assert result["initial"] and result["final"] is None


@pytest.mark.parametrize("variant", experiment.VARIANTS)
@pytest.mark.parametrize("length_rejections", [1, 2, 3])
def test_long_original_protocol_retries_keep_capture_and_shared_sdk_budget(monkeypatch, variant, length_rejections):
    analysis, calls = analysis_fixture(), []
    analysis["prompt_context"] = "Synthetic planning context. " * 800 + analysis["rag_context_assembly"]["context"]
    response = report_fixture(analysis)
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": True}})

    def create(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        reason = "length" if len(calls) <= length_rejections else "stop"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response), finish_reason=reason)]
        )

    client = GovernedModelClient(
        completion_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="deepseek",
        is_local=False,
        model_name="synthetic-test-model",
    )
    result = experiment.run_arm(scenario_fixture(), analysis, variant, client)
    expected_calls = min(length_rejections + 1, 3)
    assert len(calls) == result["model_calls"] == result["generation_attempts"] == expected_calls
    assert [record["request_kind"] for record in result["attempts"]] == ["initial"] + ["protocol_retry"] * (
        expected_calls - 1
    )
    assert all(record["prompt_characters"] > 18000 for record in result["attempts"])
    assert all(record.get("error_code") != "repair_prompt_limit_exceeded" for record in result["attempts"])
    for call in calls:
        submitted = call["messages"][1]["content"]
        assert submitted.count(experiment.LAYOUT_GUIDANCE.strip()) == (1 if variant == "claim_pair_v1" else 0)
        assert submitted.count(analysis["rag_context_assembly"]["context"]) == 1
        assert call["max_tokens"] == 2300
    if length_rejections < 3:
        assert result["status"] == "completed" and result["capture_valid"]
        snapshot = result["final"]["model_evidence"]
        assert snapshot["request_kind"] == "protocol_retry" and snapshot["attempt_number"] == expected_calls
        assert snapshot["request_binding"]["user_prompt_sha256"] == text_sha256(calls[-1]["messages"][1]["content"])
        assert result["final"]["body_claim_evidence"]["snapshot_status"] == "captured"
    else:
        assert result["status"] == "failed" and result["final"] is None
        assert result["error_code"] == "ModelResponseError"


def synthetic_provenance(path):
    return {"scenario_path": str(path), "scenario_sha256": cli.sha256_file(path)}


def prepared_fixture(tmp_path):
    payload = {
        "schema": cli.SCENARIO_SCHEMA,
        "phase": "seen_pilot",
        "candidate": "claim_pair_v1",
        "target_sections": [7, 11, 12],
        "cases": [scenario_fixture("one"), scenario_fixture("two")],
    }
    calls = []

    def analyse(*args):
        calls.append(args)
        return analysis_fixture()

    scenario_path = tmp_path / "synthetic-scenarios.json"
    scenario_path.write_text(json.dumps(payload), encoding="utf-8")
    bundle = cli.prepare_bundle(payload, scenario_path, analyse=analyse, provenance=synthetic_provenance)
    assert len(calls) == 2
    return bundle


def test_prepare_binding_detects_tampering(tmp_path):
    bundle = prepared_fixture(tmp_path)
    assert cli.validate_prepared(bundle)
    bundle["cases"][0]["analysis"]["prompt_context"] += "changed"
    with pytest.raises(ValueError, match="hash mismatch"):
        cli.validate_prepared(bundle)


def test_alternating_order_and_failures_stay_in_denominator(monkeypatch, tmp_path):
    bundle, calls = prepared_fixture(tmp_path), []
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": True}})
    result = cli.run_prepared(
        bundle,
        max_calls=1,
        provenance=synthetic_provenance,
        client_factory=lambda: mock_client(report_fixture(analysis_fixture()), calls),
    )
    assert [(row["case_id"], row["variant"]) for row in result["rows"]] == [
        ("one", "baseline"),
        ("one", "claim_pair_v1"),
        ("two", "claim_pair_v1"),
        ("two", "baseline"),
    ]
    assert result["actual_model_calls"] == len(calls) == 1
    assert result["summaries"]["baseline"]["arms_denominator"] == 2
    assert result["summaries"]["claim_pair_v1"]["failed_or_invalid_arms"] == 2
    assert result["summaries"]["claim_pair_v1"]["pair_completeness_rate"] == 0
    assert result["rows"][0]["analysis_sha256"] == bundle["cases"][0]["analysis_sha256"]
    assert result["semantic_accuracy"] is None and result["release_gate"] == {"active": False}


def test_provenance_drift_invalidates_without_model_call(tmp_path):
    bundle = prepared_fixture(tmp_path)
    result = cli.run_prepared(
        bundle,
        provenance=lambda _: {"scenario_path": "mock.json", "changed": True},
        client_factory=lambda: pytest.fail("Model must not be constructed after drift"),
    )
    assert result["valid"] is False and result["actual_model_calls"] == 0
    assert len(result["rows"]) == 4


def test_cli_default_is_offline_help_and_run_requires_opt_in(monkeypatch, capsys):
    monkeypatch.setattr(cli, "require_local_runtime", lambda: pytest.fail("No runtime for help"))
    assert cli.main([]) == 0 and "--run-model" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["--prepared", "mock.json", "--output", "new.json"])


def test_output_cannot_be_overwritten(tmp_path, monkeypatch):
    target = tmp_path / "exists.json"
    target.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(cli, "require_local_runtime", lambda: None)
    with pytest.raises(FileExistsError):
        cli.main(["--prepare-only", "--scenarios", "unused.json", "--output", str(target)])
    assert target.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("endpoint", ["https://external.invalid/v1", "http://user:secret@localhost/v1"])
def test_external_or_credentialled_endpoint_is_rejected_before_config(monkeypatch, endpoint):
    monkeypatch.setenv("OLLAMA_BASE_URL", endpoint)
    with pytest.raises(ValueError, match="local Ollama"):
        cli.require_local_runtime()


def test_bundle_assembly_rebinding_rejected_even_with_new_outer_hash(tmp_path):
    bundle = prepared_fixture(tmp_path)
    bundle["cases"][0]["assembly_sha256"] = "0" * 64
    bundle["bundle_sha256"] = json_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})
    with pytest.raises(ValueError, match="case binding"):
        cli.validate_prepared(bundle)


def test_not_submitted_and_no_lexical_match_are_observable():
    analysis = analysis_fixture()
    omitted = copy.deepcopy(analysis["knowledge"]["retrieved_chunks"][0])
    omitted.update(source_id="omitted", chunk_id="omitted-1", title="Omitted guide")
    analysis["knowledge"]["retrieved_chunks"].append(omitted)
    limit = len(analysis["rag_context_assembly"]["context"])
    analysis["rag_context_assembly"] = assemble_retrieved_context(analysis["knowledge"], max_characters=limit)
    token = format_rag_citation_token(omitted)
    report = report_fixture(analysis, f"Families prepare household emergency supplies {token}.")
    result = experiment.parse_claim_pairs(report, analysis, captured(report, analysis))
    assert result["complete_pairs"] == 3 and result["lexically_supported_pairs"] == 0
    assert all("not_submitted" in row["support_reasons"] for row in result["pairs"])
    token = format_rag_citation_token(analysis["knowledge"]["retrieved_chunks"][0])
    report = report_fixture(analysis, f"Volcanic rock reflects purple sunlight {token}.")
    result = experiment.parse_claim_pairs(report, analysis, captured(report, analysis))
    assert all("no_lexical_match" in row["support_reasons"] for row in result["pairs"])


def test_local_application_unknown_tokens_are_not_silently_swallowed():
    analysis = analysis_fixture()
    report = report_fixture(analysis).replace("responsible owner.", "responsible owner [O1-RAG][ref=unknown].")
    result = experiment.parse_claim_pairs(report, analysis)
    assert len(result["unknown_citations"]) == 3
    assert all(item["reason"] == "unknown_source" for item in result["unknown_citations"])


def test_protocol_then_structural_repair_use_one_three_call_budget(monkeypatch):
    from src.model_response import ModelResponseError

    analysis, calls = analysis_fixture(), []
    client = mock_client(report_fixture(analysis), calls)
    original = client.generate
    invocations = []

    def generate(prompt):
        invocations.append(prompt)
        if len(invocations) == 1:
            raise ModelResponseError("length")
        return original(prompt)

    client.generate = generate
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": False}})
    monkeypatch.setattr(
        quality,
        "build_report_repair_prompt",
        lambda *_, **__: EvidencePrompt(
            "Repair.\n" + analysis["rag_context_assembly"]["context"],
            assembly=analysis["rag_context_assembly"],
            request_kind="structural_repair",
        ),
    )
    result = experiment.run_arm(scenario_fixture(), analysis, "claim_pair_v1", client)
    assert len(invocations) == result["model_calls"] == 3
    assert [row["request_kind"] for row in result["attempts"]] == ["initial", "protocol_retry", "structural_repair"]
    assert all(prompt.count(experiment.LAYOUT_GUIDANCE.strip()) == 1 for prompt in invocations)


def test_client_setup_failure_preserves_every_arm(tmp_path):
    def fail():
        raise RuntimeError("Synthetic client setup failure")

    result = cli.run_prepared(
        prepared_fixture(tmp_path),
        provenance=synthetic_provenance,
        client_factory=fail,
    )
    assert len(result["rows"]) == 4
    assert all(row["status"] == "failed" for row in result["rows"])
    assert all(summary["evaluable_reports"] == 0 for summary in result["summaries"].values())
    assert all(summary["citation_coverage_rate"] is None for summary in result["summaries"].values())
    assert all(summary["claims_requiring_citation"] is None for summary in result["summaries"].values())


@pytest.mark.parametrize("mutation", ["scenario_content", "scenario_order", "phase"])
def test_review_recomputed_bundle_must_match_actual_scenario_payload(tmp_path, mutation):
    bundle = prepared_fixture(tmp_path)
    if mutation == "scenario_content":
        bundle["cases"][0]["scenario"]["extra_context"] = "Changed synthetic case after freezing."
        bundle["cases"][0]["binding_sha256"] = cli._binding(bundle["cases"][0])
    elif mutation == "scenario_order":
        bundle["cases"].reverse()
    else:
        bundle["phase"] = "sealed_holdout"
    bundle["bundle_sha256"] = json_sha256({key: value for key, value in bundle.items() if key != "bundle_sha256"})
    with pytest.raises(ValueError, match="scenario payload"):
        cli.validate_prepared(bundle)


@pytest.mark.parametrize("indent", ["    ", "\t"])
def test_review_indented_pair_is_code_not_complete(indent):
    analysis = analysis_fixture()
    report = (
        report_fixture(analysis)
        .replace("Evidence basis:", indent + "Evidence basis:")
        .replace("Local application:", indent + "Local application:")
    )
    result = experiment.parse_claim_pairs(report, analysis)
    assert result["complete_pairs"] == 0
    assert all(row["status"] == "malformed" for row in result["pairs"])
    for row in result["pairs"]:
        span = row["evidence_basis"]["span"]
        assert report[span["start"] : span["end"]].startswith(indent)


@pytest.mark.parametrize("layout", ["prefix", "middle"])
def test_review_citation_must_follow_the_evidence_statement(layout):
    analysis = analysis_fixture()
    token = format_rag_citation_token(analysis["knowledge"]["retrieved_chunks"][0])
    basis = (
        f"{token} Families prepare household emergency supplies."
        if layout == "prefix"
        else f"Families {token} prepare household emergency supplies."
    )
    result = experiment.parse_claim_pairs(report_fixture(analysis, basis), analysis)
    assert result["complete_pairs"] == 0
    assert all("citation_must_follow_complete_statement" in row["reasons"] for row in result["pairs"])
