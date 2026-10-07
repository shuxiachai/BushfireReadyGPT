"""New approval and UI checks must not reinterpret historical quality policy."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from scripts.verify_sample_exports import verify_sample_package
from src import report_workflow
from src.governance import build_review_checklist_snapshot
from src.report_generation_quality import (
    QUALITY_POLICY_FINGERPRINT,
    QUALITY_POLICY_VERSION,
    READABLE_QUALITY_POLICY_BINDINGS,
    evaluate_governed_report,
    is_readable_quality_policy_binding,
)
from src.report_grounding import claim_review_reasons, evaluate_report_grounding
from src.report_template import append_evidence_tables, append_human_signoff, apply_governance_notice
from tests.support.report_fixtures import _valid_report

ROOT = Path(__file__).resolve().parents[1]


def _analysis():
    return {
        "profile": {"state": "Queensland"},
        "community": {"indicators": {"population": "172888", "older_people_pct": "16.5"}},
        "data_integrity": {"custom_data": False, "core_ready": True},
        "data": {
            "sources": [
                {"id": "qfd_qfes", "name": "Queensland Fire Department / QFES"},
                {"id": "get_ready_qld_bushfire", "name": "Get Ready Queensland - Current Bushfire Incidents"},
            ]
        },
        "knowledge": {
            "status": "disabled",
            "retrieved_chunks": [
                {"source_id": "qld_evacuation_plan", "title": "Evacuation plan", "text": "Prepare a household plan."}
            ],
        },
    }


def _review(status="Approved by organisation"):
    return {
        "approval_status": status,
        "reviewer_name": "Test Reviewer",
        "reviewer_role": "Safety reviewer",
        "organisation_name": "Test Organisation",
        "review_date": "2025-01-01",
        "review_checklist": build_review_checklist_snapshot(lambda _: True),
        "review_notes": "All checked; approve despite warnings.",
    }


def _record(claim, analysis=None):
    # Only an in-memory copy is modified; the committed release bytes stay intact.
    text = (ROOT / "examples/v0.6.0/cairns-council-report.md").read_text(encoding="utf-8")
    text = text.replace("# 2. Executive Summary", f"# 2. Executive Summary\n{claim}", 1)
    return {"text": text, "analysis": _analysis() if analysis is None else analysis}


def _current_record(claim=""):
    """A complete current approval fixture, separate from historical UI inputs."""
    narrative, analysis = _valid_report()
    analysis["profile"] = {"state": "Queensland"}
    analysis["data_integrity"] = {"custom_data": False, "core_ready": True}
    analysis["community"] = {
        "indicators": {
            "population": 172888,
            "older_people_pct": 16.5,
            "no_car_households_pct": None,
            "language_other_than_english_pct": None,
            "geography_type": "lga_approximation",
            "matched_sa2_count": 22,
        },
        "data_quality": {"source_period": "2021 Census and 2022 ERP"},
    }
    heading = "## 4. Selected Geography and Key Assumptions"
    before, remainder = narrative.split(heading, 1)
    _old, after = remainder.split("## 5. Data Sources and Limitations", 1)
    basis = (
        "Community population is 172,888 and older people represent 16.5% in the approximate 22-SA2 "
        "aggregation (2021 Census and 2022 ERP) [P2]. Transport and language measurements remain unknown. "
        "These community figures describe a historical regional baseline rather than premises occupancy. "
        "No site address, participant list or exact premises boundary is supplied. Local applicability "
        "remains an organisational review matter before formal use."
    )
    narrative = before + heading + "\n" + basis + "\n\n## 5. Data Sources and Limitations" + after
    if claim:
        narrative = narrative.replace("## 2. Executive Summary", "## 2. Executive Summary\n" + claim, 1)
    text = append_human_signoff(append_evidence_tables(apply_governance_notice(narrative), analysis))
    return {"text": text, "analysis": analysis}


@pytest.mark.parametrize(
    "claim",
    [
        "The community data shows a population of 999999 residents.",
        "The community profile records older people percentage is 99%.",
        "The report jurisdiction is NSW.",
        "The planning jurisdiction is New South Wales.",
        "The community population is 999999 residents, and staff should confirm the contact list.",
        "The community population is 999999 residents, AND staff SHOULD confirm the contact list.",
        "The community population is 999999 residents while staff should confirm the contact list.",
        "The community population is **999999** residents.",
        "The community population is __999999__ residents.",
        "The report jurisdiction is **NSW**.",
        "The report jurisdiction is _NSW_.",
        "The report jurisdiction is NSW, and staff should confirm the contact list.",
        "The report jurisdiction is NSW, AND staff SHOULD confirm the contact list.",
    ],
)
def test_explicit_snapshot_conflicts_block_new_approval_even_with_stale_pass_cache(claim):
    record = _current_record(claim)
    actual_quality = evaluate_governed_report(record["text"], record["analysis"])
    numeric = "population" in claim or "older people" in claim
    if numeric:
        p2 = next(check for check in actual_quality["checks"] if check["name"] == "Processed community provenance")
        assert "p2_value_mismatch" in {item["code"] for item in p2["findings"]}
        assert actual_quality["approval_gate"]["passed"] is False
    else:
        assert actual_quality["approval_gate"]["passed"] is True
    assert any(
        item.get("snapshot_conflicts")
        for item in evaluate_report_grounding(record["text"], record["analysis"])["claims"]
    )
    record["grounding_evaluation"] = {"status": "pass", "claims": []}

    error = report_workflow.validate_review_record(_review(), {"approval_gate": {"passed": True}}, record)

    if numeric:
        assert "Resolve all failed Governed Report Check items" in error
    else:
        assert "explicit frozen-evidence conflict" in error
        assert "Correct the report or regenerate" in error


@pytest.mark.parametrize("status", ["Draft - human review required", "Needs revision", "Reviewed draft"])
def test_conflicts_do_not_prevent_recording_non_approved_review_statuses(status):
    record = _record("The community data shows a population of 999999 residents.")
    assert report_workflow.validate_review_record(_review(status), report_record=record) is None


def test_new_approval_blocks_escape_paraphrases_without_reinterpreting_v6():
    record = _current_record("Drive along Smith Road now to escape the flames.")
    assert evaluate_governed_report(record["text"], record["analysis"])["approval_gate"]["passed"] is True
    assert "operational escape directions" in report_workflow.validate_review_record(_review(), report_record=record)
    assert report_workflow.validate_review_record(_review("Reviewed draft"), report_record=record) is None


@pytest.mark.parametrize(
    "claim",
    [
        "The community data shows a population of 172,888 residents.",
        "The community data shows a population of 172888.0 residents.",
        "The community profile records older people percentage is 16.5%.",
        "The report jurisdiction is Queensland.",
        "The plan records 42 contact-directory checks for the coming month.",
        "NSW guidance provides comparative preparedness context for the review.",
        "The user says the community data shows a population of 999999 residents.",
        "The community data does not show a population of 999999 residents.",
        "The community population is approximately 170000 residents.",
        "Verify whether the community data shows a population of 999999 residents.",
        "The hypothetical community data shows a population of 999999 residents.",
        "The school population is 250 students.",
        "The community data supports planning, while the school population is 250 students.",
        "The community data supports planning, WHILE the school population is 250 students.",
        "The community population is 172888 residents, compared with a school population of 250 students.",
        "The community data lists the school population is 250 students.",
        "The community population is **172888** residents.",
        "The report jurisdiction is **Queensland**.",
        "The user says the community population is **999999** residents.",
        "The community population is not **999999** residents.",
    ],
)
def test_legacy_grounding_does_not_invent_conflicts_for_unknown_comparisons_or_matching_values(claim):
    # No claim of complete current approval: this is the legacy conflict
    # classifier's boundary, independent of v7 provenance and task requirements.
    result = evaluate_report_grounding(claim, _analysis())
    assert not any(item.get("snapshot_conflicts") for item in result["claims"])


@pytest.mark.parametrize("value", [None, "", "unknown", "nan", "inf", -1, True])
def test_missing_or_invalid_reference_value_cannot_establish_numeric_contradiction(value):
    analysis = _analysis()
    analysis["community"]["indicators"]["population"] = value
    result = evaluate_report_grounding("The community data shows a population of 999999 residents.", analysis)
    assert not any(item.get("snapshot_conflicts") for item in result["claims"])


@pytest.mark.parametrize(
    "claim",
    [
        "",
        "The report jurisdiction is Queensland.",
        "Community population is 172888.0 and older people represent 16.5% in the approximate 22-SA2 "
        "aggregation (2021 Census and 2022 ERP) [P2].",
    ],
)
def test_complete_current_report_with_matching_facts_can_be_approved(claim):
    record = _current_record(claim)
    quality = evaluate_governed_report(record["text"], record["analysis"])
    assert quality["approval_gate"]["passed"] is True, quality["approval_gate"]["blocking_failures"]
    assert report_workflow.validate_review_record(_review(), report_record=record) is None


def test_review_transaction_rechecks_before_appending_any_audit_event(monkeypatch):
    record = _current_record("The community data shows a population of 999999 residents.")
    record["audit_path"] = "test-bound-audit.json"
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state={"latest_report": record}))
    monkeypatch.setattr(report_workflow, "load_and_verify_audit", lambda _: {"verified_test_snapshot": True})
    monkeypatch.setattr(report_workflow, "_report_matches_audit_snapshot", lambda *_: True)

    def should_not_append(*_args, **_kwargs):
        pytest.fail("Unresolved evidence conflict must be rejected before writing approval.")

    monkeypatch.setattr(report_workflow, "append_audit_event", should_not_append)
    original_text = record["text"]
    assert report_workflow.update_latest_audit_review(_review()) is False
    assert record["text"] == original_text
    assert "review_record" not in record


def test_review_ui_displays_missing_wrong_and_all_more_than_ten_citations():
    claims = [
        {
            "claim_id": f"issue-{index:02}",
            "claim": f"Evidence statement number {index} requires review.",
            "citation_required": True,
            "supported": True,
            "numeric_consistent": True,
            "cited_source_ids": [],
            "cited_source_supported": False,
            "jurisdiction_conflicts": [],
        }
        for index in range(13)
    ]
    claims[1]["cited_source_ids"] = ["wrong-attribution"]
    app = AppTest.from_string(
        "from src.ui.review_views import render_report_quality_summary\nrender_report_quality_summary()"
    )
    app.session_state["latest_quality"] = {"summary": {}, "approval_gate": {"passed": True}}
    app.session_state["latest_report"] = {
        "grounding_evaluation": {"status": "review_required", "metrics": {"claims_evaluated": 13}, "claims": claims}
    }
    app.run(timeout=15)

    assert not app.exception
    rendered = "\n".join(item.value for item in app.markdown)
    assert "Claims requiring review:** 13 (complete list)" in rendered
    assert "no recognised source attribution" in rendered
    assert "cited source does not support this claim" in rendered
    for claim in claims:
        assert f"`{claim['claim_id']}`" in rendered
        assert claim_review_reasons(claim)


def test_evaluation_review_count_uses_the_same_issue_selector_as_the_ui():
    evaluation = evaluate_report_grounding(
        "The community data shows a population of 172888 residents.\n"
        "The community data shows a population of 999999 residents.",
        _analysis(),
    )
    assert (
        evaluation["metrics"]["claims_requiring_review"]
        == sum(bool(claim_review_reasons(claim)) for claim in evaluation["claims"])
        == 2
    )


def test_current_review_displays_new_conflicts_without_rewriting_old_generation_evidence():
    record = _record("The community population is **999999** residents.")
    recorded = {"method": "deterministic_lexical_grounding_v3", "status": "pass", "claims": []}
    record["grounding_evaluation"] = recorded
    app = AppTest.from_string(
        "from src.ui.review_views import render_report_quality_summary\nrender_report_quality_summary()"
    )
    app.session_state["latest_quality"] = {"summary": {}, "approval_gate": {"passed": True}}
    app.session_state["latest_report"] = record
    app.run(timeout=15)

    assert not app.exception
    assert any("999999" in item.value and "explicit statement conflicts" in item.value for item in app.markdown)
    assert any("recorded generation-time evaluation" in item.value for item in app.caption)
    assert not any("evidence-alignment thresholds passed" in item.value for item in app.success)
    assert app.session_state["latest_report"]["grounding_evaluation"] == recorded


def test_current_review_cache_binds_report_text_analysis_and_method(monkeypatch):
    from src.ui import review_views

    record = _record("The community population is 172888 residents.")
    state = {}
    monkeypatch.setattr(review_views, "st", SimpleNamespace(session_state=state))
    calls = []

    def evaluate(text, analysis):
        calls.append((text, analysis))
        return {"status": "test", "claims": []}

    monkeypatch.setattr(review_views, "evaluate_report_grounding", evaluate)
    review_views._current_grounding_review(record)
    review_views._current_grounding_review(record)
    assert len(calls) == 1
    record["text"] += "\nThe report jurisdiction is NSW."
    review_views._current_grounding_review(record)
    assert len(calls) == 2
    record["analysis"]["community"]["indicators"]["population"] = "1"
    review_views._current_grounding_review(record)
    assert len(calls) == 3
    monkeypatch.setattr(review_views, "GROUNDING_METHOD", "future-review-method")
    review_views._current_grounding_review(record)
    assert len(calls) == 4
    assert "grounding_evaluation" not in record


def test_v6_policy_and_committed_release_read_validation_remain_unchanged(monkeypatch):
    legacy_fingerprint = "b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745"
    assert QUALITY_POLICY_VERSION == "governed-report-v8"
    assert QUALITY_POLICY_FINGERPRINT != legacy_fingerprint
    assert READABLE_QUALITY_POLICY_BINDINGS["governed-report-v6"] == frozenset({legacy_fingerprint})
    assert is_readable_quality_policy_binding("governed-report-v6", legacy_fingerprint)

    def new_approval_must_not_run(*_args, **_kwargs):
        pytest.fail("Historical release read validation must not call the new approval workflow.")

    monkeypatch.setattr(report_workflow, "validate_review_record", new_approval_must_not_run)
    result = verify_sample_package(
        ROOT / "examples/v0.6.0/cairns-council-pilot-package.zip", require_current_policy=False
    )
    assert result["quality_policy_version"] == "governed-report-v6"
    assert result["quality_policy_fingerprint"] == legacy_fingerprint
    assert result["current_policy"] is False
    assert result["governed_gate_passed"] is True
    assert result["verified_hashes"] == 10
