"""Synthetic SDK mocks exercise submitted evidence without provider calls."""

import copy
import json
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from src import audit, export_package
from src import report_generation_quality as quality
from src.model_evidence import (
    EvidencePrompt,
    EvidenceResponse,
    bind_normalized_narrative,
    capture_model_evidence,
    normalized_evidence_response,
    protocol_retry_prompt,
    text_sha256,
    validate_model_evidence,
)
from src.model_runtime import GovernedModelClient, ModelServiceError
from src.rag.context import assemble_planning_context
from src.rag.service import assemble_retrieved_context
from src.report_grounding import evaluate_model_visible_rag_grounding, evaluate_report_grounding
from src.report_template import append_human_signoff


def _chunk(text, identity="guide"):
    return {
        "source_id": identity,
        "chunk_id": identity + "-1",
        "title": "Preparedness guide " + identity,
        "agency": "Test authority",
        "text": text,
        "chunk_sha256": text_sha256(text),
        "jurisdictions": ["Queensland"],
    }


def _analysis(*chunks):
    return {
        "profile": {"state": "Queensland"},
        "knowledge": {"status": "ready", "retrieved_chunks": list(chunks)},
        "data": {"sources": [{"id": "one", "name": "Official One"}, {"id": "two", "name": "Official Two"}]},
    }


def _claim(identity="guide"):
    return f"[O1-RAG][source_id={identity}] Preparedness guide {identity} says families prepare household emergency supplies."


def _runtime(response, calls=None):
    def create(**kwargs):
        if calls is not None:
            calls.append(copy.deepcopy(list(kwargs["messages"])))
        content = response() if callable(response) else response
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")]
        )

    return GovernedModelClient(
        completion_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="test",
        is_local=False,
    )


def _capture(analysis, assembly=None, *, response=None, kind="initial", attempt=1, prefix="PRIVATE U0 VALUE\n"):
    assembly = assembly or assemble_retrieved_context(analysis["knowledge"])
    prompt = EvidencePrompt(prefix + assembly["context"], assembly=assembly, request_kind=kind)
    runtime = _runtime(response or _claim())
    text = runtime.generate(prompt)
    snapshot = capture_model_evidence(prompt, runtime, text, attempt_number=attempt)
    return text, bind_normalized_narrative(snapshot, text), prompt, runtime


def test_sdk_capture_matches_actual_messages_without_storing_private_input():
    calls = []
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    assembly = assemble_planning_context(analysis["knowledge"])
    prompt = EvidencePrompt("  PRIVATE U0 VALUE\n" + assembly["context"] + "  ", assembly=assembly)
    runtime = _runtime(_claim(), calls)
    response = runtime.generate(prompt)
    snapshot = bind_normalized_narrative(capture_model_evidence(prompt, runtime, response, attempt_number=1), response)
    assert snapshot["request_binding"]["user_prompt_sha256"] == text_sha256(calls[0][1]["content"])
    assert snapshot["request_binding"]["system_prompt_sha256"] == text_sha256(calls[0][0]["content"])
    assert (
        validate_model_evidence(snapshot, analysis, report_text=response)[0]["text"]
        == assembly["visible_chunks"][0]["text"]
    )
    assert "PRIVATE U0 VALUE" not in json.dumps(snapshot)
    assert "PRIVATE U0 VALUE" not in json.dumps(runtime.last_request_capture)
    assert evaluate_model_visible_rag_grounding(response, analysis, snapshot)["status"] == "pass"


def test_tail_support_in_full_chunk_is_not_support_in_submitted_prefix():
    analysis = _analysis(
        _chunk("Archive paperwork register administration. " * 90 + "Families prepare household emergency supplies.")
    )
    assembly = assemble_retrieved_context(analysis["knowledge"], max_chunk_characters=2200)
    response, snapshot, *_ = _capture(analysis, assembly)
    assert evaluate_report_grounding(response, analysis)["metrics"]["support_rate"] == 1
    visible = evaluate_model_visible_rag_grounding(response, analysis, snapshot)
    assert visible["status"] == "review_required"
    assert visible["metrics"]["support_rate"] == 0


def test_citation_to_totally_omitted_source_is_still_recognised():
    first = _chunk("Administrative registers document archive entries.", "first")
    second = _chunk("Families prepare household emergency supplies.", "second")
    limit = len(assemble_retrieved_context({"retrieved_chunks": [first]})["context"])
    analysis = _analysis(first, second)
    assembly = assemble_retrieved_context(analysis["knowledge"], max_characters=limit)
    assert assembly["manifest"]["included_count"] == 1
    response, snapshot, *_ = _capture(analysis, assembly, response=_claim("second"))
    visible = evaluate_model_visible_rag_grounding(response, analysis, snapshot)
    assert visible["claims"][0]["cited_source_ids"] == ["second"]
    assert visible["claims"][0]["source_checks"][0]["visible_passage_present"] is False


def test_fake_client_and_historical_absence_are_unknown_not_zero_or_reconstruction():
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    fake = SimpleNamespace(generate=lambda _: _claim())
    assert capture_model_evidence("fake prompt", fake, _claim(), attempt_number=1)["status"] == "unavailable"
    visible = evaluate_model_visible_rag_grounding(_claim(), analysis)
    assert visible["status"] == "unavailable" and visible["metrics"]["support_rate"] is None
    assert "model_visible_rag" not in evaluate_report_grounding(_claim(), analysis)


def test_marker_spoof_and_duplicate_context_do_not_create_a_capture():
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    assembly = assemble_retrieved_context(analysis["knowledge"])
    runtime = _runtime(_claim())
    fake = "<retrieved-official-evidence>invented support</retrieved-official-evidence>"
    for prompt, reason in [
        (EvidencePrompt(fake), "request_assembly_not_recorded"),
        (EvidencePrompt(assembly["context"] * 2, assembly=assembly), "assembly_not_uniquely_submitted"),
        (EvidencePrompt(fake, assembly=assembly), "assembly_not_uniquely_submitted"),
    ]:
        response = runtime.generate(prompt)
        snapshot = capture_model_evidence(prompt, runtime, response, attempt_number=1)
        assert snapshot["reason"] == reason


def test_capture_does_not_leak_across_failed_or_different_requests():
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    response, snapshot, prompt, runtime = _capture(analysis)
    assert (
        capture_model_evidence(str(prompt) + " changed", runtime, response, attempt_number=2)["status"] == "unavailable"
    )
    runtime._completion_client.chat.completions.create = lambda **_: (_ for _ in ()).throw(
        ModelServiceError("synthetic failure")
    )
    with pytest.raises(ModelServiceError):
        runtime.generate("next private request")
    assert runtime.last_request_capture is None


@pytest.mark.parametrize("mutation", ["text", "source", "offset", "hash", "narrative", "schema", "private_field"])
def test_tampered_snapshot_is_rejected(mutation):
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    response, snapshot, *_ = _capture(analysis)
    if mutation == "text":
        snapshot["visible_passages"][0]["text"] += " invented"
    elif mutation == "source":
        snapshot["visible_passages"][0]["source_id"] = "unknown"
    elif mutation == "offset":
        snapshot["assembly_manifest"]["chunks"][0]["visible_start"] += 1
    elif mutation == "hash":
        snapshot["assembly_manifest"]["context_sha256"] = "0" * 64
    elif mutation == "narrative":
        snapshot["normalized_narrative_sha256"] = "0" * 64
    elif mutation == "schema":
        snapshot["schema"] = "future"
    else:
        snapshot["private_prompt"] = "secret"
    with pytest.raises(ValueError):
        validate_model_evidence(snapshot, analysis, report_text=response)
    assert evaluate_model_visible_rag_grounding(response, analysis, snapshot)["status"] == "invalid_snapshot"


def test_protocol_retry_preserves_its_own_assembly_and_changes_actual_message_hash():
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    response, snapshot, original, runtime = _capture(analysis)
    retry = protocol_retry_prompt(original, "\nRewrite the whole report.")
    response = runtime.generate(retry)
    retried = bind_normalized_narrative(capture_model_evidence(retry, runtime, response, attempt_number=2), response)
    assert retried["request_kind"] == "protocol_retry" and retried["attempt_number"] == 2
    assert retried["context"] == snapshot["context"]
    assert retried["request_binding"]["messages_sha256"] != snapshot["request_binding"]["messages_sha256"]


def test_repair_is_recorded_with_its_smaller_budget_not_initial_evidence():
    analysis = _analysis(
        _chunk("Administrative registers record procedures. " * 40 + "Families prepare household emergency supplies.")
    )
    original = EvidencePrompt("Original private request", assembly=assemble_retrieved_context(analysis["knowledge"]))
    repair = quality.build_report_repair_prompt(original, "Private rejected response", {}, analysis=analysis)
    assert isinstance(repair, EvidencePrompt) and repair.request_kind == "structural_repair"
    runtime = _runtime(_claim())
    response = runtime.generate(repair)
    snapshot = bind_normalized_narrative(capture_model_evidence(repair, runtime, response, attempt_number=2), response)
    assert snapshot["assembly_manifest"]["max_characters"] == 3500
    assert snapshot["assembly_manifest"]["max_chunk_characters"] == 900
    assert "Private rejected response" not in str(repair)
    assert "Original private request" not in str(repair)
    validate_model_evidence(snapshot, analysis, report_text=response)


def test_normalized_response_retains_exact_source_capture_without_old_attempt_union(monkeypatch):
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    assembly = assemble_retrieved_context(analysis["knowledge"])
    prompt = EvidencePrompt(assembly["context"], assembly=assembly)
    runtime = _runtime(_claim())
    seen = []

    def generate(attempt_prompt, number, _repair):
        response = runtime.generate(attempt_prompt)
        snapshot = capture_model_evidence(attempt_prompt, runtime, response, attempt_number=number)
        seen.append(snapshot)
        return EvidenceResponse(response, snapshot)

    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": len(seen) > 1}})
    narrative, _, count = quality.generate_narrative_with_repairs(prompt, analysis, generate)
    assert count == 2
    assert narrative.model_evidence["attempt_number"] == 2
    assert narrative.model_evidence["request_kind"] == "structural_repair"
    assert narrative.model_evidence["assembly_manifest"]["max_chunk_characters"] == 900
    assert "attempts" not in narrative.model_evidence
    validate_model_evidence(narrative.model_evidence, analysis, report_text=narrative)


def test_response_hash_mismatch_cannot_be_bound_to_a_normalized_narrative():
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    response, snapshot, *_ = _capture(analysis)
    altered = EvidenceResponse(response + " Altered private narrative.", snapshot)
    normalized = normalized_evidence_response(altered, "Different normalized narrative.")
    assert normalized.model_evidence["status"] == "unavailable"


def test_prior_draft_is_not_visible_official_evidence_without_submitted_passages():
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    limit = len(assemble_retrieved_context(analysis["knowledge"])["context"]) - 1
    assembly = assemble_retrieved_context(analysis["knowledge"], max_characters=limit)
    assert not assembly["visible_chunks"]
    response, snapshot, *_ = _capture(analysis, assembly, kind="revision", prefix="Prior draft: " + _claim() + "\n")
    assert evaluate_model_visible_rag_grounding(response, analysis, snapshot)["status"] == "review_required"


@pytest.fixture
def export_case(monkeypatch, tmp_path):
    from src.export_register import REGISTER_SNAPSHOT_FILES
    from src.governance import build_review_checklist_snapshot

    monkeypatch.setenv("BUSHFIRE_AUDIT_DIR", str(tmp_path / "audit"))
    fixed_quality = {
        "checks": [],
        "summary": {"passed": 1, "warnings": 0, "failed": 0, "total": 1},
        "approval_gate": {"passed": True, "status": "passed", "blocking_failures": []},
        "quality_policy_version": quality.QUALITY_POLICY_VERSION,
        "quality_policy_fingerprint": quality.QUALITY_POLICY_FINGERPRINT,
    }
    monkeypatch.setattr(audit, "evaluate_governed_report", lambda *_: copy.deepcopy(fixed_quality))
    monkeypatch.setattr(export_package, "evaluate_governed_report", lambda *_: copy.deepcopy(fixed_quality))
    monkeypatch.setattr(export_package, "create_report_pdf", lambda _: b"synthetic pdf")
    monkeypatch.setattr(export_package, "create_report_docx", lambda _: b"synthetic docx")
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    response, snapshot, *_ = _capture(analysis)
    review = audit.canonical_review_record(
        {
            "approval_status": "Draft - human review required",
            "review_checklist": build_review_checklist_snapshot(),
        }
    )
    report = append_human_signoff(response, review)
    grounding = evaluate_report_grounding(report, analysis)
    grounding["model_visible_rag"] = evaluate_model_visible_rag_grounding(report, analysis, snapshot)
    context = {"report_id": "evidence-test", "report_version": 1, "report_status": review["approval_status"]}
    registers = {path: "Synthetic register\n" for path in REGISTER_SNAPSHOT_FILES}
    path = audit.save_report_audit(
        {
            "report_id": context["report_id"],
            "report_version": 1,
            "report_text": report,
            "analysis": analysis,
            "human_review": review,
            "report_status": review["approval_status"],
            "package_context": context,
            "export_register_snapshot": registers,
            "grounding_evaluation": grounding,
        }
    )
    return dict(
        report_text=report,
        audit_path=path,
        review_record=review,
        package_context=context,
        register_snapshot=registers,
        analysis=analysis,
        grounding_evaluation=grounding,
    )


def test_export_includes_only_audit_bound_grounding_with_artifact_hash(export_case):
    package = export_package.create_pilot_export_package(**export_case)
    with ZipFile(BytesIO(package["content"])) as archive:
        content = archive.read("governance/grounding_evaluation.json")
        assert json.loads(content) == export_case["grounding_evaluation"]
        assert (
            text_sha256(content.decode())
            == package["manifest"]["artifact_hashes"]["governance/grounding_evaluation.json"]
        )
        assert "PRIVATE U0 VALUE" not in content.decode()


def test_export_rejects_diagnostic_tampering_but_legacy_optional_call_is_unchanged(export_case):
    altered = copy.deepcopy(export_case)
    altered["grounding_evaluation"]["model_visible_rag"]["metrics"]["support_rate"] = 0
    with pytest.raises(audit.AuditIntegrityError, match="grounding diagnostic"):
        export_package.create_pilot_export_package(**altered)
    export_case.pop("grounding_evaluation")
    package = export_package.create_pilot_export_package(**export_case)
    assert "governance/grounding_evaluation.json" not in package["manifest"]["included_files"]


def test_legacy_v6_fingerprint_is_unchanged():
    assert quality.QUALITY_POLICY_VERSION == "governed-report-v6"
    assert quality.QUALITY_POLICY_FINGERPRINT == "b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745"


@pytest.mark.parametrize("field", ["manifest", "entry", "fragment", "context_tail", "context_header"])
def test_rehashed_unknown_private_fields_and_unaccounted_context_are_rejected(field):
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    assembly = assemble_planning_context(analysis["knowledge"])
    response, snapshot, *_ = _capture(analysis, assembly)
    manifest = snapshot["assembly_manifest"]
    if field == "manifest":
        manifest["private_form_input"] = "SYNTHETIC_U0_SECRET"
    elif field == "entry":
        manifest["chunks"][0]["private_form_input"] = "SYNTHETIC_U0_SECRET"
    elif field == "fragment":
        manifest["chunks"][0]["fragments"][0]["private_form_input"] = "SYNTHETIC_U0_SECRET"
    elif field == "context_tail":
        snapshot["context"] += "\nSYNTHETIC_U0_SECRET"
    else:
        snapshot["context"] = snapshot["context"].replace("hybrid_score=None", "hybrid_score=NONE")
    manifest["context_sha256"] = text_sha256(snapshot["context"])
    manifest["context_characters"] = len(snapshot["context"])
    for frozen in (analysis, None):
        with pytest.raises(ValueError):
            validate_model_evidence(snapshot, frozen, report_text=response)


def test_offline_binding_validation_is_explicitly_distinct_from_full_source_revalidation():
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    response, snapshot, *_ = _capture(analysis, assemble_planning_context(analysis["knowledge"]))
    assert len(validate_model_evidence(snapshot, report_text=response)) == 1
    analysis["knowledge"]["retrieved_chunks"][0]["text"] = "Changed source text."
    with pytest.raises(ValueError, match="source identity"):
        validate_model_evidence(snapshot, analysis, report_text=response)


def test_new_optional_evidence_file_passes_sample_scanner_without_global_marker_exception(
    export_case, monkeypatch, tmp_path
):
    from scripts import verify_sample_exports as verifier

    package = export_package.create_pilot_export_package(**export_case)
    path = tmp_path / "synthetic-evidence.zip"
    path.write_bytes(package["content"])
    # This fixture tests ZIP/audit/marker binding; PDF/DOCX renderers have their own suite.
    monkeypatch.setattr(verifier, "_verify_pdf", lambda _: (1, "synthetic rendered report"))
    monkeypatch.setattr(verifier, "_verify_docx", lambda _: (1, "synthetic rendered report"))
    monkeypatch.setattr(verifier, "REQUIRED_REPORT_MARKERS", ())
    assert verifier.verify_sample_package(path)["report_id"] == "evidence-test"
    assert "<retrieved-official-evidence>" in verifier.FORBIDDEN_INTERNAL_MARKERS
    monkeypatch.setattr(verifier, "_verify_pdf", lambda _: (1, "<retrieved-official-evidence>"))
    with pytest.raises(ValueError, match="boundary leaked into PDF"):
        verifier.verify_sample_package(path)


def test_sample_scanner_rejects_unknown_context_fields_even_with_updated_audit_binding(export_case):
    from scripts.verify_sample_exports import _verified_grounding_scan_text

    package = export_package.create_pilot_export_package(**export_case)
    altered = copy.deepcopy(export_case["grounding_evaluation"])
    altered["model_visible_rag"]["snapshot"]["assembly_manifest"]["private_input"] = "SECRET"
    record = audit.load_and_verify_audit(export_case["audit_path"])
    record["grounding_evaluation_hash"] = audit.sha256_json(altered)
    manifest = package["manifest"]
    manifest["grounding_diagnostic"]["sha256"] = record["grounding_evaluation_hash"]
    with pytest.raises(ValueError, match="manifest fields"):
        _verified_grounding_scan_text(json.dumps(altered), manifest, record, export_case["report_text"])


def test_revision_workflow_attaches_new_frozen_evidence_without_retrieval(export_case, monkeypatch):
    from src import report_workflow as workflow

    class State(dict):
        __getattr__ = dict.__getitem__
        __setattr__ = dict.__setitem__

    original_analysis = copy.deepcopy(export_case["analysis"])
    parent = {
        "id": "parent",
        "version": 1,
        "text": export_case["report_text"],
        "analysis": original_analysis,
        "inputs": {},
        "area_selection": None,
        "export_register_snapshot": export_case["register_snapshot"],
        "audit_path": export_case["audit_path"],
    }
    calls, finalized = [], []
    state = State(latest_report=parent, model_client=_runtime(_claim(), calls))
    monkeypatch.setattr(workflow, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(workflow, "validate_model_privacy_boundary", lambda: None)
    monkeypatch.setattr(workflow, "_cloud_rag_availability_error", lambda _: None)
    monkeypatch.setattr(workflow, "_report_matches_audit_snapshot", lambda *_: True)
    monkeypatch.setattr(workflow, "run_analysis_pipeline", lambda *_a, **_k: pytest.fail("Revision must not retrieve"))
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": True}})

    def finalize(text, analysis, *_args, **kwargs):
        finalized.append(kwargs["model_evidence"])
        validate_model_evidence(kwargs["model_evidence"], analysis, report_text=text)
        return text, None

    monkeypatch.setattr(workflow, "_finalize_report_version", finalize)
    response, error = workflow.revise_current_report("Clarify private wording.", lambda: None)
    assert response and error is None
    assert len(calls) == 1 and finalized[0]["request_kind"] == "revision"
    assert finalized[0]["context"] in calls[0][1]["content"]
    assert "Clarify private wording." not in json.dumps(finalized)
    assert parent["analysis"] == export_case["analysis"]
