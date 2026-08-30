from src.report_grounding import evaluate_report_grounding, grounding_trace_metrics


def _analysis():
    return {
        "profile": {"state": "Queensland", "location": "Cairns, Queensland"},
        "community": {"indicators": {"population": "171000", "older_people_pct": "15"}},
        "knowledge": {
            "retrieved_chunks": [
                {
                    "source_id": "qld-guide",
                    "title": "Queensland Bushfire Preparation Guide",
                    "agency": "Queensland Fire Department",
                    "text": "Households should prepare an emergency kit and practise their bushfire plan.",
                    "jurisdictions": ["Queensland"],
                }
            ]
        },
        "data": {"sources": []},
    }


def test_grounding_supports_attributed_claim_against_retrieved_passage():
    result = evaluate_report_grounding(
        (
            "[O1-RAG][source_id=qld-guide] Queensland Bushfire Preparation Guide says households "
            "should prepare an emergency kit."
        ),
        _analysis(),
    )

    assert result["status"] == "pass"
    assert result["metrics"]["claims_evaluated"] == 1
    assert result["metrics"]["support_rate"] == 1.0
    assert result["metrics"]["citation_precision_rate"] == 1.0
    assert result["claims"][0]["best_evidence_source_id"] == "qld-guide"


def test_grounding_does_not_count_plain_agency_or_title_as_a_citation():
    result = evaluate_report_grounding(
        "Queensland Fire Department guidance says households should prepare an emergency kit.",
        _analysis(),
    )

    assert result["status"] == "review_required"
    assert result["metrics"]["citation_coverage_rate"] == 0.0
    assert result["claims"][0]["cited_source_ids"] == []


def test_canonical_label_title_cannot_create_false_lexical_support():
    result = evaluate_report_grounding(
        (
            "[O1-RAG][source_id=qld-guide] Queensland Bushfire Preparation Guide confirms "
            "cryptocurrency investments are safe."
        ),
        _analysis(),
    )

    assert result["status"] == "review_required"
    assert result["metrics"]["support_rate"] == 0.0
    assert result["metrics"]["citation_precision_rate"] == 0.0
    assert result["claims"][0]["cited_source_ids"] == ["qld-guide"]


def test_repeating_source_title_after_label_cannot_create_false_support():
    result = evaluate_report_grounding(
        (
            "[O1-RAG][source_id=qld-guide] Queensland Bushfire Preparation Guide "
            "Queensland Bushfire Preparation Guide confirms cryptocurrency investments are safe."
        ),
        _analysis(),
    )

    assert result["status"] == "review_required"
    assert result["metrics"]["support_rate"] == 0.0
    assert result["metrics"]["citation_precision_rate"] == 0.0


def test_grounding_flags_number_not_present_in_frozen_evidence():
    result = evaluate_report_grounding(
        "The community data shows a population of 999999 residents.",
        _analysis(),
    )

    assert result["status"] == "review_required"
    assert result["metrics"]["numeric_consistency_rate"] == 0.0
    assert result["claims"][0]["numeric_consistent"] is False


def test_grounding_flags_wrong_jurisdiction_reference():
    result = evaluate_report_grounding(
        "NSW Rural Fire Service guidance reports that households should prepare an emergency kit.",
        _analysis(),
    )

    assert result["status"] == "review_required"
    assert result["metrics"]["jurisdiction_conflicts"] == 1
    assert result["claims"][0]["jurisdiction_conflicts"] == ["New South Wales"]


def test_grounding_does_not_treat_lowercase_act_as_act_jurisdiction():
    result = evaluate_report_grounding(
        "Queensland Fire Department guidance says households should act early and prepare an emergency kit.",
        _analysis(),
    )

    assert result["metrics"]["jurisdiction_conflicts"] == 0


def test_grounding_excludes_deterministic_appendices_from_claim_extraction():
    report = """# Plan

Assign owners and review the draft locally.

## Evidence Tables

| Field | Value |
| --- | --- |
| Population data | 999999 |

## Human Review Sign-off

Reviewer: pending
"""
    result = evaluate_report_grounding(report, _analysis())

    assert result["status"] == "not_applicable"
    assert result["metrics"]["claims_evaluated"] == 0


def test_grounding_excludes_application_owned_retrieval_provenance_line():
    report = (
        "## Data Sources and Limitations\n"
        "The application retrieved this static official passage as preparedness-planning evidence for human "
        "review. [O1-RAG][source_id=qld-guide] Queensland Bushfire Preparation Guide"
    )

    result = evaluate_report_grounding(report, _analysis())

    assert result["status"] == "not_applicable"
    assert result["metrics"]["claims_evaluated"] == 0


def test_trace_projection_does_not_include_claim_text():
    result = evaluate_report_grounding(
        "The community data shows a population of 999999 residents.",
        _analysis(),
    )

    trace = grounding_trace_metrics(result)

    assert trace["grounding_status"] == "review_required"
    assert trace["claims_evaluated"] == 1
    assert "claims" not in trace
    assert "claim" not in trace
