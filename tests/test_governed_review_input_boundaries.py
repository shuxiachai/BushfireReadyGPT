"""Malformed restored checklist IDs must fail closed without crashing review UI."""

import pytest

from src import audit, report_workflow
from src.governance import APPROVED_STATUS, build_review_checklist_snapshot, is_review_checklist_complete


@pytest.mark.parametrize("bad_id", [[], {}, ["official_sources"], {"id": "official_sources"}, 1, True, None])
def test_non_string_checklist_ids_are_incomplete_and_rejected_by_audit(bad_id):
    checklist = build_review_checklist_snapshot(lambda _item: True)
    checklist[0]["id"] = bad_id
    assert is_review_checklist_complete(checklist) is False
    with pytest.raises(audit.AuditIntegrityError, match="unknown or duplicate"):
        audit.canonical_review_record({"approval_status": APPROVED_STATUS, "review_checklist": checklist})


@pytest.mark.parametrize("bad_id", [[], {}])
def test_review_validation_reports_malformed_checklist_instead_of_raising(bad_id):
    checklist = build_review_checklist_snapshot(lambda _item: True)
    checklist[0]["id"] = bad_id
    review = {
        "approval_status": APPROVED_STATUS,
        "reviewer_name": "Fixture reviewer",
        "reviewer_role": "Preparedness reviewer",
        "organisation_name": "Fixture council",
        "review_date": "2026-01-01",
        "review_checklist": checklist,
    }
    error = report_workflow.validate_review_record(review, report_record={"text": "Draft fixture"})
    assert "Complete every Human Review Checklist item" in error


def test_complete_canonical_checklist_remains_accepted():
    checklist = build_review_checklist_snapshot(lambda _item: True)
    assert is_review_checklist_complete(checklist) is True
    review = audit.canonical_review_record({"approval_status": APPROVED_STATUS, "review_checklist": checklist})
    assert review["review_checklist_complete"] is True
