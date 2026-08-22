import copy

import pytest

from src.pilot_evaluation import PilotEvaluationError, summarise_pilot_payload, validate_pilot_payload


def _session(code="P01", **overrides):
    value = {
        "participant_code": code,
        "perspective": "school",
        "scenario": "School preparedness",
        "session_date": "2026-08-21",
        "tasks_completed": 8,
        "workflow_minutes": 8.5,
        "export_opened": True,
        "facilitator_help_count": 0,
        "report_usefulness": 5,
        "evidence_classes_correct": 5,
        "safety_boundary_understood": True,
        "edit_extent": "light",
        "citations_checked": 3,
        "citations_supported": 3,
        "citation_trust": 5,
        "issue_ids": [],
    }
    value.update(overrides)
    return value


def test_empty_pilot_template_does_not_claim_validation():
    summary = summarise_pilot_payload({"schema_version": 1, "sessions": [], "bad_cases": []})

    assert summary["status"] == "awaiting_participants"
    assert summary["participants"] == 0
    assert summary["completion_gate_passed"] is False
    assert summary["metrics"] == {}


def test_pilot_summary_calculates_targets_and_edit_distribution():
    payload = {
        "schema_version": 1,
        "sessions": [
            _session("P01"),
            _session("P02", perspective="council", workflow_minutes=9, citations_supported=2),
            _session("P03", perspective="community", tasks_completed=7, edit_extent="none"),
        ],
        "bad_cases": [],
    }

    summary = summarise_pilot_payload(payload)

    assert summary["status"] == "complete"
    assert summary["completion_gate_passed"] is True
    assert summary["metrics"]["citation_support_rate"] == pytest.approx(8 / 9, abs=0.0001)
    assert summary["metrics"]["edit_extent_counts"] == {"light": 2, "none": 1}
    assert all(summary["target_results"].values())


def test_open_high_bad_case_blocks_completion_and_tracks_regression_test():
    payload = {
        "schema_version": 1,
        "sessions": [_session("P01", issue_ids=["BC-001"]), _session("P02"), _session("P03")],
        "bad_cases": [
            {
                "id": "BC-001",
                "title": "Draft boundary was missed",
                "severity": "High",
                "status": "Open",
                "finding_category": "safety_boundary",
                "participant_codes": ["P01"],
                "regression_test": "tests/test_governance_regressions.py::test_draft_boundary",
                "owner_role": "safety_reviewer",
                "disposition": "fix_planned",
            }
        ],
    }

    summary = summarise_pilot_payload(payload)

    assert summary["completion_gate_passed"] is False
    assert summary["bad_cases"] == {"total": 1, "open_critical_or_high": 1, "with_regression_test": 1}


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("email", "person@example.com", "privacy_field_rejected"),
        ("tasks_completed", 9, "invalid_measure"),
        ("citations_supported", 4, "invalid_citation_measure"),
        ("participant_code", "Alice", "invalid_participant_code"),
    ],
)
def test_pilot_schema_rejects_personal_or_invalid_fields(field, value, code):
    session = _session()
    session[field] = value
    payload = {"schema_version": 1, "sessions": [session], "bad_cases": []}

    with pytest.raises(PilotEvaluationError) as raised:
        validate_pilot_payload(payload)

    assert raised.value.code == code


def test_bad_case_references_must_be_bidirectionally_valid():
    payload = {"schema_version": 1, "sessions": [_session(issue_ids=["BC-999"])], "bad_cases": []}

    with pytest.raises(PilotEvaluationError) as raised:
        validate_pilot_payload(copy.deepcopy(payload))

    assert raised.value.code == "unknown_bad_case"
