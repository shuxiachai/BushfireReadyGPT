from datetime import date

import pytest

from src import audit
from src.governance import validate_review_date
from src.input_validation import (
    REPORT_FIELD_LIMITS,
    REVISION_REQUEST_MAX_CHARS,
    validate_report_input_budget,
    validate_review_input_budget,
    validate_revision_request_budget,
)
from src.report_workflow import _review_date_text, validate_report_inputs, validate_review_record


def _valid_report_inputs():
    return {
        "location": "Cairns, Queensland",
        "audience": "School community",
        "scenario": "School preparedness",
        "concerns": ["Evacuation planning"],
        "timeframe": "7-day action plan",
        "extra_context": "",
        "report_status": "Draft - human review required",
    }


def test_report_field_boundary_is_accepted_and_overflow_is_rejected():
    inputs = _valid_report_inputs()
    limit = REPORT_FIELD_LIMITS["extra_context"][1]
    inputs["extra_context"] = "x" * limit
    assert validate_report_input_budget(inputs) is None

    inputs["extra_context"] += "x"
    assert "Additional context exceeds" in validate_report_inputs(inputs)


def test_report_budget_counts_utf8_bytes_not_only_characters():
    inputs = _valid_report_inputs()
    for field, (_label, limit) in REPORT_FIELD_LIMITS.items():
        inputs[field] = "澳" * limit

    assert "combined report input" in validate_report_input_budget(inputs)

    inputs = _valid_report_inputs()
    for field, (_label, limit) in REPORT_FIELD_LIMITS.items():
        inputs[field] = "x" * limit
    inputs["concerns"] = ["澳" * 200] * 20
    assert "combined report input" in validate_report_input_budget(inputs)


def test_report_and_review_shapes_fail_closed():
    assert validate_report_input_budget({"concerns": "Evacuation"}) == "Focus areas must be a list."
    assert validate_report_input_budget({"concerns": ""}) == "Focus areas must be a list."
    assert validate_review_input_budget({"review_notes": ["not", "text"]}) == "Review notes must be text."


def test_revision_request_has_a_service_level_limit():
    assert validate_revision_request_budget("x" * REVISION_REQUEST_MAX_CHARS) is None
    assert "exceeds" in validate_revision_request_budget("x" * (REVISION_REQUEST_MAX_CHARS + 1))
    assert "must be text" in validate_revision_request_budget({"instruction": "change"})


def test_review_dates_reject_malformed_and_future_values():
    today = date(2026, 8, 24)
    assert validate_review_date("2026-08-24", today=today) is None
    assert "valid ISO date" in validate_review_date("24/08/2026", today=today)
    assert "valid ISO date" in validate_review_date("20260824", today=today)
    assert "valid ISO date" in validate_review_date("2026-W35-1", today=today)
    assert "valid ISO date" in validate_review_date(" 2026-08-24", today=today)
    assert "valid ISO date" in validate_review_date("2026-08-24 ", today=today)
    assert "future" in validate_review_date("2026-08-25", today=today)
    assert "required" in validate_review_date("", required=True, today=today)
    assert "future" in validate_review_record({"approval_status": "Needs revision", "review_date": "2099-01-01"})
    assert _review_date_text(None) == ""
    assert _review_date_text(today) == "2026-08-24"


def test_audit_transition_rejects_future_review_date():
    with pytest.raises(audit.AuditIntegrityError, match="future"):
        audit._validate_review_transition(
            {"approval_status": "Needs revision", "review_date": "2099-01-01"},
            {},
            {},
        )


def test_audit_transition_rejects_oversized_review_text():
    with pytest.raises(audit.AuditIntegrityError, match="Review notes exceeds"):
        audit._validate_review_transition(
            {"approval_status": "Needs revision", "review_notes": "x" * 4_001},
            {},
            {},
        )
