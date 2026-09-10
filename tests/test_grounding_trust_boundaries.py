"""U0 cannot corroborate itself; diagnostic warnings retain their limits."""

from copy import deepcopy

import pytest

from src.agents import run_analysis_pipeline
from src.report_grounding import claim_review_reasons, evaluate_report_grounding, grounding_trace_metrics

CLAIM = "The community data shows a population of 999999 residents."


def trusted_analysis():
    return {
        "profile": {"state": "Queensland", "location": "Cairns, Queensland"},
        "community": {
            "indicators": {"population": "172888", "older_people_pct": "16.5"},
            "vulnerability_notes": [
                "Older residents should be considered in smoke, heat, transport, and welfare check planning."
            ],
        },
        "risk_context": {"risk_points": ["Seasonal bushfire exposure and smoke impacts require local validation."]},
        "plan": {"one_week_focus": ["Day 7: approve the draft plan and schedule the next review."]},
        "data_provenance": {"community_profile": {"sha256": "a" * 64}},
        "data": {"sources": []},
        "knowledge": {"retrieved_chunks": []},
    }


@pytest.mark.parametrize(
    "path",
    [
        "profile.location",
        "profile.locality",
        "profile.audience",
        "profile.scenario",
        "profile.concerns",
        "profile.timeframe",
        "profile.extra_context",
        "profile.future_field",
        "prompt_context",
        "inputs.extra_context",
        "form_inputs.audience",
        "area_selection.area_name",
        "evidence_confidence",
        "knowledge.query",
        "data.user_context",
        "community.user_context",
        "community.indicators.unrecognised_metric",
        "community.data_quality.untrusted_note",
        "community.geography_reference.selected_asgs_area.untrusted_note",
        "risk_context.user_context",
        "plan.concerns",
        "plan.focus_area_concepts",
        "data_integrity.note",
        "data_provenance.extra_context",
        "resolved_data_paths.extra_context",
        "future_analysis_section",
    ],
)
def test_u0_and_unknown_fields_never_become_grounding_evidence(path):
    analysis = trusted_analysis()
    node = analysis
    parts = path.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    value = CLAIM
    if path == "evidence_confidence":
        value = [{"code": "U0", "current_use": CLAIM}, {"code": "P2", "current_use": CLAIM}]
    elif path in {"profile.concerns", "plan.concerns", "plan.focus_area_concepts"}:
        value = [CLAIM]
    node[parts[-1]] = value

    result = evaluate_report_grounding(CLAIM, analysis)

    assert result["claims"][0]["supported"] is False
    assert result["claims"][0]["numeric_consistent"] is False
    assert result["metrics"]["support_rate"] == 0
    assert result["metrics"]["numeric_consistency_rate"] == 0


def test_real_pipeline_u0_echo_cannot_corrobate_invented_population():
    analysis = run_analysis_pipeline(
        "Cairns, Queensland", CLAIM, "School bushfire preparedness", [], "7-day action plan", CLAIM
    )
    assert analysis["community"]["indicators"]["population"] != "999999"

    claim = evaluate_report_grounding(CLAIM, analysis)["claims"][0]

    assert claim["supported"] is False
    assert claim["numeric_consistent"] is False


@pytest.mark.parametrize(
    ("claim_text", "path"),
    [
        ("The community data shows a population of 172888 residents.", "community.indicators.population"),
        ("Community data records older people percentage is 16.5%.", "community.indicators.older_people_pct"),
        (
            "Community evidence indicates older residents should be considered in smoke and welfare check planning.",
            "community.vulnerability_notes[0]",
        ),
        (
            "Evidence shows seasonal bushfire exposure and smoke impacts require local validation.",
            "risk_context.risk_points[0]",
        ),
        ("Day 7: approve the draft plan and schedule the next review.", "plan.one_week_focus[0]"),
    ],
)
def test_real_processed_and_derived_evidence_remains_available(claim_text, path):
    result = evaluate_report_grounding(claim_text, trusted_analysis())
    claim = result["claims"][0]

    assert claim["supported"] is True
    assert claim["best_evidence_path"] == path
    assert len(claim["best_evidence_sha256"]) == 64
    if path.startswith("community"):
        assert claim["best_evidence_version"] == "a" * 64
    # Trusted support does not magically supply a missing external citation.
    assert result["status"] == "review_required"
    assert result["metrics"]["claims_requiring_review"] == 1
    assert "no recognised source attribution" in claim_review_reasons(claim)


def test_official_support_keeps_chunk_field_and_version_without_u0_pollution():
    analysis = trusted_analysis()
    analysis["knowledge"]["retrieved_chunks"] = [
        {
            "source_id": "qld-guide",
            "title": "Queensland Guide",
            "text": "Prepare an emergency kit and practise the household bushfire plan.",
            "chunk_sha256": "b" * 64,
            "jurisdictions": ["Queensland"],
        }
    ]
    result = evaluate_report_grounding(
        "[O1-RAG][source_id=qld-guide] Queensland Guide says prepare an emergency kit.", analysis
    )
    claim = result["claims"][0]
    assert result["status"] == "pass"
    assert claim["best_evidence_source_id"] == "qld-guide"
    assert claim["best_evidence_path"] == "knowledge.retrieved_chunks[0].text"
    assert claim["best_evidence_version"] == "b" * 64
    assert result["metrics"]["claims_requiring_review"] == 0


@pytest.mark.parametrize(
    ("path", "value", "claim"),
    [
        ("community.data_quality.source_age_years", 4, "The source age is 4 years."),
        ("community.geography_reference.selected_asgs_area.sa2_count", 12, "The selected SA2 count is 12 areas."),
        ("plan.risk_rule_count", 3, "The risk rule count is 3."),
    ],
)
def test_known_vintage_geography_and_rule_counts_are_not_lost(path, value, claim):
    analysis = trusted_analysis()
    node = analysis
    parts = path.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    result = evaluate_report_grounding(claim, analysis)["claims"][0]
    assert result["supported"] is True
    assert result["best_evidence_path"] == path


def test_trace_projection_does_not_add_claims_paths_or_conflict_values():
    trace = grounding_trace_metrics(evaluate_report_grounding(CLAIM, trusted_analysis()))
    assert "999999" not in str(trace)
    assert "community.indicators" not in str(trace)
    assert set(trace) == {
        "grounding_status",
        "claims_evaluated",
        "support_rate",
        "citation_coverage_rate",
        "numeric_consistency_rate",
        "jurisdiction_conflicts",
    }


@pytest.mark.parametrize("path", ["community.vulnerability_notes", "risk_context.risk_points", "plan.one_week_focus"])
def test_nested_objects_are_not_flattened_inside_trusted_string_list_fields(path):
    analysis = deepcopy(trusted_analysis())
    section, field = path.split(".")
    analysis[section][field] = [{"untrusted": CLAIM}]
    assert evaluate_report_grounding(CLAIM, analysis)["claims"][0]["numeric_consistent"] is False
