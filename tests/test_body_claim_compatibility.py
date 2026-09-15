"""Synthetic scope/citation regressions; never rewrite archived diagnostic meaning."""

import copy

import pytest

from src import report_claim_evidence as body
from src import report_generation_quality as quality
from src.focus_coverage import canonical_coverage_declarations
from src.model_evidence import EvidenceResponse, validate_model_evidence
from src.report_template import REPORT_NARRATIVE_WORD_BUDGET
from src.source_attribution import format_rag_attribution
from tests.test_model_evidence import _analysis, _capture, _chunk


def _scoped_analysis():
    from src.agents.profile_agent import ProfileAgent

    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    analysis["profile"]["scenario_concept"] = copy.deepcopy(next(iter(ProfileAgent._SCENARIO_CONCEPTS.values())))
    return analysis


def test_only_exact_analysis_bound_declaration_is_non_external_and_retained():
    analysis = _scoped_analysis()
    declaration = canonical_coverage_declarations(analysis)[0]
    report = declaration + "\n\n" + declaration.replace("covers", "safely covers")
    claims = body.extract_body_claims(report, analysis)
    assert len(claims) == 2 and claims[0]["claim"] == declaration
    assert claims[0]["classification"] == "organisational_procedure" and not claims[0]["citation_required"]
    assert claims[1]["classification"] == "external_assertion" and claims[1]["citation_required"]
    assert body.extract_body_claims(declaration, {})[0]["citation_required"]
    for altered in (
        declaration.removesuffix(".") + " and guarantees safety.",
        "Do not follow this scope: " + declaration,
        declaration.replace("This draft covers", "This draft does not cover"),
    ):
        assert all(claim["citation_required"] for claim in body.extract_body_claims(altered, analysis))


@pytest.mark.parametrize("historical", [False, True])
def test_versioned_scope_replays_exactly_in_export_and_offline_validator(historical):
    from scripts.verify_sample_exports import _verified_grounding_scan_text
    from src.audit import sha256_json
    from src.export_package import _verified_grounding_bytes
    from src.report_grounding import evaluate_model_visible_rag_grounding, evaluate_report_grounding

    analysis = _scoped_analysis()
    report = canonical_coverage_declarations(analysis)[0]
    _, snapshot, *_ = _capture(analysis, response=report)
    if historical:
        diagnostic = body._evaluate(report, analysis, validate_model_evidence(snapshot, analysis), "captured")
        assert "classification_scope" not in diagnostic
        assert diagnostic["metrics"]["missing_citations"] == 1
    else:
        diagnostic = body.evaluate_body_claim_evidence(report, analysis, snapshot)
        assert diagnostic["classification_scope"]["version"] == 2
        assert diagnostic["metrics"]["missing_citations"] == 0
    for context in ({}, {"analysis": analysis}):
        assert body.validate_body_claim_evidence(diagnostic, report, snapshot, **context) == diagnostic
    grounding = evaluate_report_grounding(report, analysis)
    grounding["model_visible_rag"] = evaluate_model_visible_rag_grounding(report, analysis, snapshot)
    grounding["body_claim_evidence"] = diagnostic
    digest = sha256_json(grounding)
    audit = {"grounding_evaluation_hash": digest, "analysis": analysis}
    manifest = {
        "grounding_diagnostic": {"sha256": digest, "model_visible_rag_status": grounding["model_visible_rag"]["status"]}
    }
    content = _verified_grounding_bytes(grounding, audit, analysis, report).decode()
    assert "body_claim_evidence" in _verified_grounding_scan_text(content, manifest, audit, report)


@pytest.mark.parametrize("mutation", ["unknown", "null", "extra", "mismatch", "removed"])
def test_scope_metadata_is_canonical_and_cannot_silently_change_classification(mutation):
    analysis = _scoped_analysis()
    report = canonical_coverage_declarations(analysis)[0]
    diagnostic = body.evaluate_body_claim_evidence(report, analysis)
    if mutation == "unknown":
        diagnostic["classification_scope"]["scenario_id"] = "arbitrary user text"
    elif mutation == "null":
        diagnostic["classification_scope"] = None
    elif mutation == "extra":
        diagnostic["classification_scope"]["private_prompt"] = "private"
    elif mutation == "mismatch":
        diagnostic["classification_scope"]["scenario_id"] = None
    else:
        diagnostic.pop("classification_scope")
    for context in ({}, {"analysis": analysis}):
        with pytest.raises(ValueError):
            body.validate_body_claim_evidence(diagnostic, report, **context)


def test_user_context_citation_does_not_suppress_feedback_during_mandatory_repair(monkeypatch):
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    label = format_rag_attribution(analysis["knowledge"]["retrieved_chunks"][0])
    report = (
        f"The user reports having household emergency supplies. {label} Families should prepare household supplies."
    )
    fixed = {
        "approval_gate": {
            "passed": False,
            "blocking_failures": [{"name": "Required sections", "detail": "Complete the required sections."}],
        }
    }
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: copy.deepcopy(fixed))
    monkeypatch.setattr(quality, "_normalise_generation_response", lambda response, _: str(response))
    monkeypatch.setattr(quality, "validate_narrative_ending", lambda *_: None)
    prompts = []

    def generate(prompt, number, is_repair):
        prompts.append(str(prompt))
        _, snapshot, *_ = _capture(
            analysis, response=report, attempt=number, kind="structural_repair" if is_repair else "initial"
        )
        return EvidenceResponse(report, snapshot)

    _, result, count = quality.generate_narrative_with_repairs(
        "Private initial request", analysis, generate, max_repair_attempts=1
    )
    assert count == 2 and result == fixed
    assert "BODY CITATION REPAIR" in prompts[1] and "NONE" in prompts[1]
    assert "separate from the governed approval checks" in prompts[1]
    assert "Private initial request" not in prompts[1] and report not in prompts[1]
    assert REPORT_NARRATIVE_WORD_BUDGET in prompts[1] and "at least 300 prose words" in prompts[1]
    assert len(prompts[1]) <= quality.MAX_REPORT_REPAIR_PROMPT_CHARACTERS


def test_advisory_gap_retains_passing_candidate_and_missing_citation_diagnostic(monkeypatch):
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    report = "Families should prepare household emergency supplies."
    fixed = {"approval_gate": {"passed": True, "blocking_failures": []}}
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: copy.deepcopy(fixed))
    monkeypatch.setattr(quality, "_normalise_generation_response", lambda response, _: str(response))
    monkeypatch.setattr(quality, "validate_narrative_ending", lambda *_: None)
    attempts = []

    def generate(_prompt, number, _is_repair):
        attempts.append(number)
        assert number == 1, "An advisory gap must not risk rewriting an already governed-passing candidate."
        _, snapshot, *_ = _capture(analysis, response=report)
        return EvidenceResponse(report, snapshot)

    narrative, final_quality, count = quality.generate_narrative_with_repairs("Prepare a draft.", analysis, generate)
    diagnostic = body.evaluate_body_claim_evidence(narrative, analysis, narrative.model_evidence)
    assert count == 1 and attempts == [1] and narrative == report and final_quality == fixed
    assert diagnostic["snapshot_status"] == "captured" and diagnostic["status"] == "review_required"
    assert diagnostic["metrics"]["claims_requiring_citation"] == diagnostic["metrics"]["missing_citations"] == 1
    assert diagnostic["metrics"]["cited_claims"] == 0


@pytest.mark.parametrize(
    "code, prompt_marker",
    [
        ("absolute_safety_guarantee", "ABSOLUTE-SAFETY REWRITE"),
        ("missing_required_section", "missing_required_section"),
    ],
)
def test_mandatory_failures_still_share_original_repair_ceiling(monkeypatch, code, prompt_marker):
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    report = "Families should prepare household emergency supplies."
    fixed = {"approval_gate": {"passed": False, "blocking_failures": [{"name": "Mandatory check", "detail": code}]}}
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: copy.deepcopy(fixed))
    monkeypatch.setattr(quality, "_normalise_generation_response", lambda response, _: str(response))
    monkeypatch.setattr(quality, "validate_narrative_ending", lambda *_: None)
    attempts = []

    def generate(prompt, number, is_repair):
        attempts.append(number)
        if is_repair:
            assert "BODY CITATION REPAIR" in prompt and prompt_marker in prompt
        _, snapshot, *_ = _capture(
            analysis, response=report, attempt=number, kind="structural_repair" if is_repair else "initial"
        )
        return EvidenceResponse(report, snapshot)

    _, final_quality, count = quality.generate_narrative_with_repairs("Prepare a draft.", analysis, generate)
    assert count == quality.MAX_REPORT_REPAIR_ATTEMPTS + 1 == 3
    assert attempts == [1, 2, 3] and final_quality == fixed


@pytest.mark.parametrize("version, passed", [(1, True), (2, False)])
def test_summary_v1_preserves_history_while_v2_requires_citation_on_external_claim(version, passed):
    from scripts.evaluation_artifacts import ArtifactValidationError, validate_report_evaluation_artifact
    from tests.test_evaluation_artifacts import _valid_report_artifact
    from tests.test_model_visible_summary_artifacts import _summary

    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    report = (
        "The user reports having household emergency supplies. "
        + format_rag_attribution(analysis["knowledge"]["retrieved_chunks"][0])
        + " Families should prepare household supplies."
    )
    diagnostic = body.evaluate_body_claim_evidence(report, analysis)
    assert diagnostic["metrics"]["cited_claims"] == 1
    assert diagnostic["metrics"]["claims_requiring_citation"] == diagnostic["metrics"]["missing_citations"] == 1
    artifact = _valid_report_artifact()
    row = artifact["rows"][0]
    row["model_visible_rag"] = _summary()
    row["body_claim_evidence"] = {
        "schema": f"body-claim-evidence-summary-v{version}",
        "method": diagnostic["method"],
        "status": diagnostic["status"],
        "snapshot_status": "captured",
        "metrics": diagnostic["metrics"],
        "processing": diagnostic["processing"],
        "delivery_required": True,
        "delivery_passed": passed,
        "release_gate_enforced": False,
    }
    gate = copy.deepcopy(artifact["release_gate"])
    validate_report_evaluation_artifact(artifact)
    assert artifact["release_gate"] == gate
    row["body_claim_evidence"]["delivery_passed"] = not passed
    with pytest.raises(ArtifactValidationError, match="delivery criterion"):
        validate_report_evaluation_artifact(artifact)
