import json

import pytest

from src import audit
from src.export_register import REGISTER_SNAPSHOT_FILES
from src.governance import DRAFT_STATUS
from src.report_generation_quality import QUALITY_POLICY_FINGERPRINT, QUALITY_POLICY_VERSION


def _digest(character):
    return character * 64


def _audit_record(index, previous=None):
    quality = {
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "quality_policy_fingerprint": QUALITY_POLICY_FINGERPRINT,
        "approval_gate": {"passed": False},
    }
    previous_record, previous_path = previous if previous is not None else (None, None)
    record = {
        "audit_schema": audit.AUDIT_SCHEMA,
        "audit_id": f"audit-{index}",
        "event_type": "review.recorded" if previous_record is not None else "report.created",
        "recorded_at": "2026-08-24T00:00:00Z",
        "previous_audit_id": previous_record.get("audit_id") if previous_record else None,
        "previous_record_hash": previous_record.get("record_hash") if previous_record else None,
        "previous_audit_file": previous_path.name if previous_path else None,
        "report_id": "iterative-long-chain",
        "report_version": 1,
        "parent_report_id": None,
        "parent_audit_binding": None,
        "report_content": {"sha256": _digest("a")},
        "governed_body_hash": _digest("b"),
        "inputs_hash": _digest("c"),
        "area_selection_hash": _digest("d"),
        "analysis": {"analysis_hash": _digest("e")},
        "quality": quality,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "quality_policy_fingerprint": QUALITY_POLICY_FINGERPRINT,
        "generation_gate_blocked": True,
        "review_record_hash": _digest("f"),
        "package_context_hash": _digest("1"),
        "immutable_package_context_hash": _digest("2"),
        "organisation_context_hash": _digest("3"),
        "source_payload_hash": _digest("4"),
        "export_register_hashes": {path: _digest("5") for path in REGISTER_SNAPSHOT_FILES},
        "report_status": DRAFT_STATUS,
    }
    record["record_hash"] = audit.sha256_json(record)
    return record


def _write_record(path, record):
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def _rewrite_hash(record):
    record.pop("record_hash", None)
    record["record_hash"] = audit.sha256_json(record)


def test_load_and_verify_audit_handles_chain_longer_than_default_recursion_depth(tmp_path):
    previous = None
    latest_path = None
    latest_record = None

    for index in range(1_105):
        latest_path = tmp_path / f"audit_{index:04d}.json"
        latest_record = _audit_record(index, previous)
        _write_record(latest_path, latest_record)
        previous = (latest_record, latest_path)

    loaded = audit.load_and_verify_audit(latest_path)

    assert loaded["audit_id"] == latest_record["audit_id"]
    assert loaded["record_hash"] == latest_record["record_hash"]


def test_verify_chain_false_skips_path_traversal_but_default_rejects_escape(tmp_path):
    record = _audit_record(1)
    record["previous_audit_file"] = "../outside.json"
    _rewrite_hash(record)
    path = tmp_path / "audit_escape.json"
    _write_record(path, record)

    assert audit.load_and_verify_audit(path, verify_chain=False) == record
    with pytest.raises(audit.AuditIntegrityError, match="invalid previous filename"):
        audit.load_and_verify_audit(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("previous_audit_id", "wrong-audit-id", "previous ID does not match"),
        ("previous_record_hash", _digest("0"), "previous hash does not match"),
    ],
)
def test_iterative_verification_preserves_predecessor_binding_checks(tmp_path, field, value, message):
    root_path = tmp_path / "audit_root.json"
    root = _audit_record(1)
    _write_record(root_path, root)
    child_path = tmp_path / "audit_child.json"
    child = _audit_record(2, (root, root_path))
    child[field] = value
    _rewrite_hash(child)
    _write_record(child_path, child)

    with pytest.raises(audit.AuditIntegrityError, match=message):
        audit.load_and_verify_audit(child_path)


def test_iterative_verification_preserves_reassessment_predecessor_policy_check(tmp_path):
    root_path = tmp_path / "audit_root.json"
    root = _audit_record(1)
    _write_record(root_path, root)
    child_path = tmp_path / "audit_reassessment.json"
    child = _audit_record(2, (root, root_path))
    child["event_type"] = "quality.reassessed"
    child["quality_reassessment"] = {
        "previous_policy_version": "governed-report-v1",
        "previous_policy_fingerprint": None,
        "current_policy_version": QUALITY_POLICY_VERSION,
        "current_policy_fingerprint": QUALITY_POLICY_FINGERPRINT,
        "human_review_performed": False,
        "report_content_changed": False,
        "review_record_changed": False,
    }
    _rewrite_hash(child)
    _write_record(child_path, child)

    with pytest.raises(audit.AuditIntegrityError, match="does not match its predecessor policy"):
        audit.load_and_verify_audit(child_path)


def test_iterative_verification_preserves_cycle_detection(tmp_path, monkeypatch):
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    _write_record(first_path, {"previous_audit_file": second_path.name})
    _write_record(second_path, {"previous_audit_file": first_path.name})
    monkeypatch.setattr(audit, "validate_audit_record", lambda record: record)

    with pytest.raises(audit.AuditIntegrityError, match="contains a cycle"):
        audit.load_and_verify_audit(first_path)
