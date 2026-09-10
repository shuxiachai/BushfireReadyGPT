"""Revision transactions must retain their parent's frozen planning evidence."""

from copy import deepcopy

import pytest

from src import audit
from src.export_register import REGISTER_SNAPSHOT_FILES
from src.governance import DRAFT_STATUS, build_review_checklist_snapshot
from src.report_template import append_human_signoff


@pytest.fixture
def revision_case(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_AUDIT_DIR", str(tmp_path / "audit"))
    review = audit.canonical_review_record(
        {
            "approval_status": DRAFT_STATUS,
            "review_checklist": build_review_checklist_snapshot(),
        }
    )
    original = {
        "report_id": "frozen-parent",
        "report_version": 1,
        "report_source": "generated",
        "inputs": {"location": "Cairns", "scenario": "Community bushfire preparedness"},
        "analysis": {"data": {"sources": [], "community_profile": {"population": 1000}}},
        "area_selection": {"sa2_codes": ["306021152"], "name": "Cairns"},
        "human_review": review,
        "report_status": DRAFT_STATUS,
        "report_text": append_human_signoff("# Original draft", review),
        "export_register_snapshot": {path: f"Fixture register: {path}\n" for path in REGISTER_SNAPSHOT_FILES},
    }
    parent_path = audit.save_report_audit(original)
    child = deepcopy(original)
    child.update(
        {
            "report_id": "frozen-child",
            "report_version": 2,
            "report_source": "revised",
            "parent_report_id": "frozen-parent",
            "revision_request": "Clarify the existing draft.",
            "report_text": append_human_signoff("# Revised wording", review),
        }
    )
    return parent_path, child, tmp_path / "audit"


@pytest.mark.parametrize(
    "field,value",
    [
        ("analysis", {"data": {"sources": [], "community_profile": {"population": 999999}}}),
        ("inputs", {"location": "Darwin", "scenario": "Community bushfire preparedness"}),
        ("area_selection", {"sa2_codes": ["701011001"], "name": "Darwin"}),
    ],
)
def test_revision_cannot_replace_frozen_parent_evidence(revision_case, field, value):
    parent_path, child, directory = revision_case
    child[field] = value
    with pytest.raises(audit.AuditIntegrityError, match="frozen"):
        audit.save_revision_audit(parent_path, child)
    assert not list(directory.glob(".revision_*.json"))
    assert len(list(directory.glob("audit_*.json"))) == 1


def test_unchanged_evidence_allows_new_wording_and_model(revision_case):
    parent_path, child, _ = revision_case
    child["model_provider"] = "deepseek"
    child["model_name"] = "deepseek-v4-flash"
    child["model_endpoint_boundary"] = "external"
    path = audit.save_revision_audit(parent_path, child)
    record = audit.load_and_verify_audit(path)
    parent = audit.load_and_verify_audit(parent_path)
    assert record["analysis"]["analysis_hash"] == parent["analysis"]["analysis_hash"]
    assert record["inputs_hash"] == parent["inputs_hash"]
    assert record["area_selection_hash"] == parent["area_selection_hash"]
    assert record["parent_report_id"] == parent["report_id"]
    assert record["model_provider"] == "deepseek"


@pytest.mark.parametrize("field,value", [("inputs", []), ("analysis", None), ("area_selection", ["306021152"])])
def test_malformed_revision_snapshots_are_rejected_before_claim(revision_case, field, value):
    parent_path, child, directory = revision_case
    child[field] = value
    with pytest.raises(audit.AuditIntegrityError, match="frozen planning snapshots"):
        audit.save_revision_audit(parent_path, child)
    assert not list(directory.glob(".revision_*.json"))


def test_rejected_mutation_does_not_consume_parent_revision_slot(revision_case):
    parent_path, child, _ = revision_case
    altered = deepcopy(child)
    altered["analysis"]["data"]["community_profile"]["population"] = 999999
    with pytest.raises(audit.AuditIntegrityError, match="frozen"):
        audit.save_revision_audit(parent_path, altered)
    accepted_path = audit.save_revision_audit(parent_path, child)
    assert audit.load_and_verify_audit(accepted_path)["report_id"] == child["report_id"]
