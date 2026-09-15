"""Synthetic unit cases; numeric-context regressions were added after challenge measurement."""

import copy
import json

import pytest

from src import report_claim_evidence as body
from src import report_generation_quality as quality
from src.model_evidence import EvidenceResponse
from src.rag.service import assemble_retrieved_context
from src.report_template import GOVERNANCE_NOTICE_MARKDOWN, append_evidence_tables, append_human_signoff
from src.source_attribution import format_rag_attribution, format_rag_citation_token
from tests.test_model_evidence import _analysis, _capture, _chunk


def test_zero_citations_remain_visible_with_and_without_capture():
    report = "Families should prepare household emergency supplies."
    analysis = _analysis(_chunk("Families should prepare household emergency supplies."))
    _, snapshot, *_ = _capture(analysis, response=report)
    for capture, status in ((snapshot, "captured"), (None, "unavailable")):
        result = body.evaluate_body_claim_evidence(report, analysis, capture)
        assert result["snapshot_status"] == status
        assert result["metrics"]["missing_citations"] == 1
        assert result["claims"][0]["support_status"] == "unknown"


def test_complete_labels_and_opaque_tokens_do_not_leak_across_sentences():
    chunk = _chunk("Families prepare household emergency supplies.")
    chunk["title"] = "Preparedness. Guide with punctuation!"
    analysis = _analysis(chunk)
    for citation in (format_rag_attribution(chunk), format_rag_citation_token(chunk)):
        report = f"Families prepare household emergency supplies. {citation} Volunteers should drink water."
        claims = body.extract_body_claims(report, analysis)
        assert len(claims) == 2
        assert claims[0]["cited_source_ids"] == ["guide"]
        assert claims[1]["cited_source_ids"] == []
        assert claims[1]["claim"] == "Volunteers should drink water."


def test_long_duplicates_tables_checklists_and_short_recommendations_are_complete():
    long = (
        "Families should prepare household emergency supplies " + "including personal supplies " * 40 + "before review."
    )
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    citation = format_rag_attribution(analysis["knowledge"]["retrieved_chunks"][0])
    report = (
        f"## Action Plan\n{long}\n\n{long}\n\n"
        f"| Action | Other action |\n| --- | --- |\n| Families prepare household emergency supplies. {citation} "
        "| Volunteers should drink water. |\n- [ ] Stay informed.\n- Drink water."
    )
    claims = body.extract_body_claims(report, analysis)
    assert len(claims) == 6
    assert claims[0]["claim"] == claims[1]["claim"] == long
    assert claims[0]["claim_id"] != claims[1]["claim_id"]
    for claim in claims:
        assert report[claim["span"]["start"] : claim["span"]["end"]] == claim["claim"]
    table = [item for item in claims if item["block_type"] == "table_cell"]
    assert [(item["table_row"], item["table_column"]) for item in table] == [(1, 1), (1, 2)]
    assert table[0]["cited_source_ids"] == ["guide"] and table[1]["cited_source_ids"] == []
    assert claims[-2]["block_type"] == "checklist" and claims[-1]["citation_required"]


def test_hidden_code_source_lines_and_application_appendices_are_excluded():
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    label = format_rag_attribution(analysis["knowledge"]["retrieved_chunks"][0])
    source_line = (
        "The application retrieved this static official passage as preparedness-planning evidence for human review."
    )
    report = (
        GOVERNANCE_NOTICE_MARKDOWN + "\n## Priorities\nFamilies should prepare household emergency supplies.\n"
        "<!-- Invisible advice should disappear. -->\n<div hidden>Other advice should disappear.</div>\n"
        "```markdown\nMasked advice should disappear.\n```\n"
        f"## 5. Data Sources and Limitations\n{source_line} {label}\n"
    )
    report = append_human_signoff(append_evidence_tables(report, analysis))
    claims = body.extract_body_claims(report, analysis)
    assert [item["claim"] for item in claims] == ["Families should prepare household emergency supplies."]


def test_organisational_user_uncertain_and_external_claims_are_separate():
    report = (
        "Assign the preparedness lead to maintain the contact list.\n"
        "The user reports having a household emergency kit.\n"
        "Unverified proposal for local review: provide additional drinking water.\n"
        "People may suffer smoke exposure.\n"
        "Confirm that extra drinking water reduces heat exposure.\n"
        "Families should prepare household emergency supplies."
    )
    claims = body.extract_body_claims(report, {})
    assert [item["classification"] for item in claims] == [
        "organisational_procedure",
        "user_context",
        "uncertain",
        "external_assertion",
        "external_assertion",
        "external_assertion",
    ]
    assert sum(item["citation_required"] for item in claims) == 3


def test_wrong_source_multiple_citations_and_u0_never_self_corroborate():
    first = _chunk("Families prepare household emergency supplies.", "supplies")
    wrong = _chunk("Administrative archives register meeting minutes.", "archive")
    analysis = _analysis(first, wrong)
    analysis["profile"]["extra_context"] = "Volunteers should drink water in hot weather."
    report = (
        f"Families prepare household emergency supplies. {format_rag_attribution(first)} "
        f"{format_rag_attribution(wrong)}\nVolunteers should drink water in hot weather. [U0]"
    )
    _, snapshot, *_ = _capture(analysis, response=report)
    result = body.evaluate_body_claim_evidence(report, analysis, snapshot)
    checks = {item["source_id"]: item for item in result["claims"][0]["source_checks"]}
    assert checks["supplies"]["support_status"] == "lexical_match"
    assert checks["archive"]["support_status"] == "no_lexical_match"
    assert result["claims"][0]["support_status"] == "no_lexical_match"
    assert result["claims"][1]["citation_status"] == "missing"
    assert result["claims"][1]["support_status"] == "unknown"
    assert "passage_refs" in checks["supplies"] and "text" not in checks["supplies"]["passage_refs"][0]


def test_label_words_cannot_create_lexical_match():
    chunk = _chunk("Administrative archive paperwork only.")
    chunk["title"] = "Household emergency supplies guidance"
    analysis = _analysis(chunk)
    report = f"Families prepare household emergency supplies. {format_rag_attribution(chunk)}"
    _, snapshot, *_ = _capture(analysis, response=report)
    assert (
        body.evaluate_body_claim_evidence(report, analysis, snapshot)["claims"][0]["support_status"]
        == "no_lexical_match"
    )


@pytest.mark.parametrize("omitted", [True, False])
def test_omitted_and_truncated_passages_cannot_support_claims(omitted):
    first = _chunk("Archive paperwork register administration. " * 90, "first")
    second = _chunk("Families prepare household emergency supplies.", "second")
    analysis = _analysis(first, second) if omitted else _analysis(_chunk(first["text"] + second["text"], "second"))
    if omitted:
        budget = len(assemble_retrieved_context({"retrieved_chunks": [first]})["context"])
        assembly = assemble_retrieved_context(analysis["knowledge"], max_characters=budget)
    else:
        assembly = assemble_retrieved_context(analysis["knowledge"], max_chunk_characters=900)
    report = f"Families prepare household emergency supplies. {format_rag_attribution(analysis['knowledge']['retrieved_chunks'][-1])}"
    _, snapshot, *_ = _capture(analysis, assembly, response=report)
    result = body.evaluate_body_claim_evidence(report, analysis, snapshot)
    assert result["claims"][0]["support_status"] == "no_lexical_match"
    assert result["claims"][0]["source_checks"][0]["visible_passage_present"] is (not omitted)


@pytest.mark.parametrize(
    "claim, passage, reason",
    [
        (
            "Families prepare household emergency supplies.",
            "Families should not prepare household emergency supplies.",
            "possible_negation_mismatch",
        ),
        (
            "Families prepare household emergency supplies.",
            "If advised, families prepare household emergency supplies.",
            "possible_omitted_condition",
        ),
        (
            "Families prepare 30 emergency supplies.",
            "Families prepare 3 emergency supplies.",
            "numeric_context_mismatch",
        ),
    ],
)
def test_bounded_mismatch_flags_are_diagnostic(claim, passage, reason):
    analysis = _analysis(_chunk(passage))
    report = f"{claim} {format_rag_attribution(analysis['knowledge']['retrieved_chunks'][0])}"
    _, snapshot, *_ = _capture(analysis, response=report)
    result = body.evaluate_body_claim_evidence(report, analysis, snapshot)
    assert reason in result["claims"][0]["reasons"]
    assert result["claims"][0]["support_status"] == "no_lexical_match"


@pytest.mark.parametrize("separator", [". ", "; "])
def test_repeated_numeric_value_cannot_join_distinct_populations_and_measures(separator):
    passage = (
        "At Northbank College, 27% of enrolled students stored paper timetables"
        + separator
        + "At Southbank College, 27% of enrolled tutors stored digital attendance registers."
    )
    analysis = _analysis(_chunk(passage))
    report = (
        "At Northbank College, 27% of enrolled students stored digital attendance registers. "
        + format_rag_attribution(analysis["knowledge"]["retrieved_chunks"][0])
    )
    _, snapshot, *_ = _capture(analysis, response=report)
    result = body.evaluate_body_claim_evidence(report, analysis, snapshot)
    assert result["status"] == "review_required"
    assert "possible_cross_statement_numeric_context" in result["claims"][0]["reasons"]
    assert result["claims"][0]["support_status"] == "no_lexical_match"


@pytest.mark.parametrize(
    "claim",
    [
        "In 2031, 12.5% of surveyed park wardens carried paper maps.",
        "In 2031, 12.5% of surveyed library staff carried electronic catalogues.",
    ],
)
def test_repeated_value_keeps_independently_supported_statement_and_shared_context(claim):
    passage = (
        "In 2031, 12.5% of surveyed park wardens carried paper maps. "
        "In the same survey, 12.5% of library staff carried electronic catalogues."
    )
    analysis = _analysis(_chunk(passage))
    report = claim + " " + format_rag_attribution(analysis["knowledge"]["retrieved_chunks"][0])
    _, snapshot, *_ = _capture(analysis, response=report)
    result = body.evaluate_body_claim_evidence(report, analysis, snapshot)
    assert result["status"] == "clear"
    assert result["claims"][0]["reasons"] == []
    assert result["claims"][0]["support_status"] == "lexical_match"


def test_distinct_values_and_a_single_statement_do_not_trigger_repeated_value_guard():
    passage = (
        "River wardens carried 24 paper maps and 8 printed catalogues. Library staff carried 16 electronic catalogues."
    )
    analysis = _analysis(_chunk(passage))
    report = "River wardens carried 24 paper maps and 8 printed catalogues. " + format_rag_attribution(
        analysis["knowledge"]["retrieved_chunks"][0]
    )
    _, snapshot, *_ = _capture(analysis, response=report)
    result = body.evaluate_body_claim_evidence(report, analysis, snapshot)
    assert result["status"] == "clear"
    assert result["claims"][0]["reasons"] == []


def test_snapshot_tampering_and_previous_response_binding_fail_closed():
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    report = f"Families prepare household emergency supplies. {format_rag_attribution(analysis['knowledge']['retrieved_chunks'][0])}"
    _, snapshot, *_ = _capture(analysis, response=report)
    altered = copy.deepcopy(snapshot)
    altered["visible_passages"][0]["text"] += " hidden new evidence"
    for capture, text in ((altered, report), (snapshot, report + " New guidance must be checked.")):
        result = body.evaluate_body_claim_evidence(text, analysis, capture)
        assert result["snapshot_status"] == "invalid_snapshot"
        assert result["claims"][0]["support_status"] == "unknown"
        with pytest.raises(ValueError):
            body.validate_body_claim_evidence(result, text, capture, analysis=analysis)


def test_offline_validator_recomputes_checks_and_rejects_unknown_fields():
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    report = f"Families prepare household emergency supplies. {format_rag_attribution(analysis['knowledge']['retrieved_chunks'][0])}"
    _, snapshot, *_ = _capture(analysis, response=report)
    evaluation = body.evaluate_body_claim_evidence(report, analysis, snapshot)
    assert body.validate_body_claim_evidence(evaluation, report, snapshot) == evaluation
    for mutation in ("extra", "check", "reference", "claim"):
        altered = copy.deepcopy(evaluation)
        if mutation == "extra":
            altered["claims"][0]["private_prompt"] = "do not export"
        elif mutation == "check":
            altered["claims"][0]["source_checks"][0]["support_score"] = 0
        elif mutation == "reference":
            altered["claims"][0]["source_checks"][0]["passage_refs"][0]["passage_index"] = 2
        else:
            altered["claims"][0]["claim"] = "Invented claim."
        with pytest.raises(ValueError, match="differs"):
            body.validate_body_claim_evidence(altered, report, snapshot)


@pytest.mark.parametrize(
    "report",
    ["Smoke kills.", "Hydrate regularly.", "- Preparations\n    - [ ] Families should prepare household supplies."],
)
def test_short_claims_and_visible_nested_lists_are_not_silently_dropped(report):
    result = body.evaluate_body_claim_evidence(report, {})
    assert result["metrics"]["missing_citations"] == 1
    assert result["status"] == "review_required"
    assert result["processing"]["complete"]
    if "[ ]" in report:
        assert result["claims"][0]["block_type"] == "checklist"


def test_indented_code_outside_a_list_is_still_excluded():
    assert body.extract_body_claims("    - [ ] Families should prepare household supplies.", {}) == []


def test_indented_list_continuation_is_visible_but_deeper_code_is_excluded():
    report = (
        "- Preparations\n\n    Families should prepare household supplies.\n\n        Hidden code should disappear."
    )
    claims = body.extract_body_claims(report, {})
    assert [claim["claim"] for claim in claims] == ["Families should prepare household supplies."]


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_fenced_code_inside_list_is_excluded(fence):
    report = f"- Preparations\n\n    {fence}text\n    Smoke kills.\n    {fence}\n\n    Hydrate regularly."
    claims = body.extract_body_claims(report, {})
    assert [claim["claim"] for claim in claims] == ["Hydrate regularly."]


@pytest.mark.parametrize("outer", [False, True])
def test_optional_outer_pipes_preserve_table_cells_and_citation_boundaries(outer):
    chunk = _chunk("Stay informed about local guidance.")
    analysis = _analysis(chunk)
    citation = format_rag_attribution(chunk)
    lines = ["Action | Other", "--- | ---", f"Stay informed. {citation} | Drink water."]
    if outer:
        lines = ["| " + line + " |" for line in lines]
    report = "\n".join(lines)
    claims = body.extract_body_claims(report, analysis)
    assert len(claims) == 2
    assert [(claim["block_type"], claim["table_row"], claim["table_column"]) for claim in claims] == [
        ("table_cell", 1, 1),
        ("table_cell", 1, 2),
    ]
    assert claims[0]["cited_source_ids"] == ["guide"]
    assert claims[1]["cited_source_ids"] == [] and claims[1]["claim"] == "Drink water."
    for claim in claims:
        assert report[claim["span"]["start"] : claim["span"]["end"]] == claim["claim"]


def test_processing_cap_reports_exact_omissions(monkeypatch):
    monkeypatch.setattr(body, "MAX_BODY_CLAIMS", 2)
    report = "Families should prepare household supplies. " * 3
    result = body.evaluate_body_claim_evidence(report, {})
    assert result["processing"] == {
        "complete": False,
        "claims_extracted": 3,
        "claims_evaluated": 2,
        "claims_omitted": 1,
        "max_claims": 2,
    }


def test_export_creation_and_scanner_validate_new_sibling_without_relaxing_old_shape():
    from scripts.verify_sample_exports import _verified_grounding_scan_text
    from src.audit import AuditIntegrityError, sha256_json
    from src.export_package import _verified_grounding_bytes
    from src.report_grounding import evaluate_model_visible_rag_grounding, evaluate_report_grounding

    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    report = f"Families prepare household emergency supplies. {format_rag_attribution(analysis['knowledge']['retrieved_chunks'][0])}"
    _, snapshot, *_ = _capture(analysis, response=report)
    evaluation = evaluate_report_grounding(report, analysis)
    evaluation["model_visible_rag"] = evaluate_model_visible_rag_grounding(report, analysis, snapshot)
    evaluation["body_claim_evidence"] = body.evaluate_body_claim_evidence(report, analysis, snapshot)

    def bindings(value):
        digest = sha256_json(value)
        audit = {"grounding_evaluation_hash": digest, "analysis": analysis}
        manifest = {
            "grounding_diagnostic": {"sha256": digest, "model_visible_rag_status": value["model_visible_rag"]["status"]}
        }
        return audit, manifest

    audit, manifest = bindings(evaluation)
    content = _verified_grounding_bytes(evaluation, audit, analysis, report).decode()
    scanned = _verified_grounding_scan_text(content, manifest, audit, report)
    assert "<retrieved-official-evidence>" not in scanned
    assert "body_claim_evidence" in scanned
    for mode in ("check", "unknown_field", "previous_attempt"):
        altered = copy.deepcopy(evaluation)
        if mode == "check":
            altered["body_claim_evidence"]["claims"][0]["source_checks"][0]["support_score"] = 0
        elif mode == "unknown_field":
            altered["body_claim_evidence"]["prior_prompt"] = "sensitive content"
        else:
            altered["model_visible_rag"]["snapshot"]["normalized_narrative_sha256"] = "a" * 64
        changed_audit, changed_manifest = bindings(altered)
        with pytest.raises(AuditIntegrityError):
            _verified_grounding_bytes(altered, changed_audit, analysis, report)
        with pytest.raises(ValueError):
            _verified_grounding_scan_text(json.dumps(altered), changed_manifest, changed_audit, report)
    legacy = copy.deepcopy(evaluation)
    legacy.pop("body_claim_evidence")
    legacy["model_visible_rag"]["claims"][0]["new_body_field"] = "unexpected"
    legacy_audit, legacy_manifest = bindings(legacy)
    with pytest.raises(ValueError, match="Unknown model-visible claim fields"):
        _verified_grounding_scan_text(json.dumps(legacy), legacy_manifest, legacy_audit, report)


def test_optional_benchmark_summary_is_validated_and_old_release_gate_is_unchanged():
    from scripts.evaluation_artifacts import ArtifactValidationError, validate_report_evaluation_artifact
    from tests.test_evaluation_artifacts import _valid_report_artifact
    from tests.test_model_visible_summary_artifacts import _summary

    artifact = _valid_report_artifact()
    original_gate = copy.deepcopy(artifact["release_gate"])
    row = artifact["rows"][0]
    row["model_visible_rag"] = _summary()
    diagnostic = body.evaluate_body_claim_evidence("Families prepare household emergency supplies.", {})
    row["body_claim_evidence"] = {
        "schema": "body-claim-evidence-summary-v1",
        "method": diagnostic["method"],
        "status": diagnostic["status"],
        "snapshot_status": "captured",
        "metrics": diagnostic["metrics"],
        "processing": diagnostic["processing"],
        "delivery_required": True,
        "delivery_passed": False,
        "release_gate_enforced": False,
    }
    validate_report_evaluation_artifact(artifact)
    assert artifact["release_gate"] == original_gate
    for changes in (
        {"delivery_passed": True},
        {"release_gate_enforced": True},
        {"private_claim": "secret"},
        {"snapshot_status": "unavailable"},
    ):
        altered = copy.deepcopy(artifact)
        altered["rows"][0]["body_claim_evidence"].update(changes)
        with pytest.raises(ArtifactValidationError, match="body-claim"):
            validate_report_evaluation_artifact(altered)


@pytest.mark.parametrize("capture, citation, expected_attempts", [(True, False, 2), (False, False, 1), (True, True, 1)])
def test_zero_body_citation_repair_shares_ceiling_and_does_not_modify_gate(
    monkeypatch, capture, citation, expected_attempts
):
    analysis = _analysis(_chunk("Families prepare household emergency supplies."))
    report = "Families should prepare household emergency supplies."
    if citation:
        report += " " + format_rag_attribution(analysis["knowledge"]["retrieved_chunks"][0])
    fixed_quality = {"approval_gate": {"passed": True, "blocking_failures": []}}
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: copy.deepcopy(fixed_quality))
    monkeypatch.setattr(quality, "_normalise_generation_response", lambda response, _: str(response))
    monkeypatch.setattr(quality, "validate_narrative_ending", lambda *_: None)
    attempts = []

    def generate(prompt, number, is_repair):
        attempts.append(number)
        _, snapshot, *_ = _capture(
            analysis, response=report, attempt=number, kind="structural_repair" if is_repair else "initial"
        )
        return EvidenceResponse(report, snapshot) if capture else report

    narrative, final_quality, count = quality.generate_narrative_with_repairs(
        "Generate a report.", analysis, generate, max_repair_attempts=1
    )
    assert count == len(attempts) == expected_attempts
    assert final_quality == fixed_quality
    assert body.evaluate_body_claim_evidence(narrative, analysis, getattr(narrative, "model_evidence", None))[
        "metrics"
    ]["missing_citations"] == (0 if citation else 1)
