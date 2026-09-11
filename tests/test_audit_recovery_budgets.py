"""Audit commits remain safely replayable and storage reads have explicit budgets."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import audit, report_workflow
from src.export_register import build_export_register_snapshot
from src.governance import DRAFT_STATUS, NEEDS_REVISION_STATUS
from src.report_template import append_human_signoff


@pytest.fixture
def audit_case(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.delenv("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    analysis = {"profile": {"state": "Queensland"}}
    inputs = {"location": "Synthetic community", "extra_context": "Synthetic private context"}
    initial_review = {"approval_status": DRAFT_STATUS}
    root_path = Path(
        audit.save_report_audit(
            {
                "report_id": "recovery-budget-test",
                "report_version": 1,
                "inputs": inputs,
                "analysis": analysis,
                "report_text": append_human_signoff("# Synthetic report", initial_review),
                "human_review": initial_review,
            }
        )
    )
    review = {"approval_status": NEEDS_REVISION_STATUS, "review_notes": "Synthetic review"}
    payload = {
        "report_id": "recovery-budget-test",
        "report_version": 1,
        "inputs": inputs,
        "area_selection": None,
        "analysis": analysis,
        "report_text": append_human_signoff("# Synthetic report", review),
        "human_review": review,
        "report_status": NEEDS_REVISION_STATUS,
        "package_context": {
            "location": inputs["location"],
            "report_id": "recovery-budget-test",
            "report_version": 1,
            "report_status": NEEDS_REVISION_STATUS,
        },
    }
    return root_path, payload


def test_committed_event_is_idempotent_after_real_lock_cleanup_failure(audit_case, monkeypatch):
    root_path, payload = audit_case
    original_unlink = Path.unlink
    lock_path = root_path.parent / ".lock_recovery_budget_test.lock"

    def held_by_scanner(path, *args, **kwargs):
        if path == lock_path:
            raise PermissionError("synthetic file scanner hold")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", held_by_scanner)
    with pytest.raises(audit.AuditIntegrityError, match="could not be released"):
        audit.append_audit_event(root_path, "review.recorded", payload)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    events = {path.name: path.read_bytes() for path in root_path.parent.glob("audit_*.json")}
    assert len(events) == 2
    head_path = audit._head_path(root_path.parent, payload["report_id"])
    head_bytes = head_path.read_bytes()
    committed = root_path.parent / json.loads(head_bytes)["audit_file"]

    assert Path(audit.append_audit_event(root_path, "review.recorded", payload)) == committed
    assert Path(audit.append_audit_event(root_path, "review.recorded", deepcopy(payload))) == committed
    assert head_path.read_bytes() == head_bytes
    assert {path.name: path.read_bytes() for path in root_path.parent.glob("audit_*.json")} == events


def test_workflow_retry_recovers_commit_without_mutating_old_session_tip_on_failure(audit_case, monkeypatch):
    root_path, payload = audit_case
    root = audit.load_and_verify_audit(root_path)
    initial_review = {"approval_status": DRAFT_STATUS}
    report = {
        "id": payload["report_id"],
        "version": 1,
        "text": append_human_signoff("# Synthetic report", initial_review),
        "inputs": deepcopy(payload["inputs"]),
        "area_selection": None,
        "analysis": deepcopy(payload["analysis"]),
        "review_record": initial_review,
        "quality": root["quality"],
        "generation_gate_blocked": root["generation_gate_blocked"],
        "export_register_snapshot": build_export_register_snapshot(),
        "audit_path": str(root_path),
    }
    assert report_workflow._report_matches_audit_snapshot(report, root)

    class SessionState(dict):
        def __setattr__(self, name, value):
            self[name] = value

    state = SessionState(latest_report=report, latest_audit_path=str(root_path), messages=[])
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))
    original_unlink = Path.unlink
    lock_path = root_path.parent / ".lock_recovery_budget_test.lock"

    def held_by_scanner(path, *args, **kwargs):
        if path == lock_path:
            raise PermissionError("synthetic file scanner hold")
        return original_unlink(path, *args, **kwargs)

    review = {**payload["human_review"], "updated_at": "2026-09-10T01:00:00"}
    monkeypatch.setattr(Path, "unlink", held_by_scanner)
    assert report_workflow.update_latest_audit_review(review) is False
    assert state["latest_report"]["audit_path"] == str(root_path)
    assert state["latest_report"]["review_record"] == initial_review
    assert state["latest_audit_path"] == str(root_path)
    committed_bytes = {path.name: path.read_bytes() for path in root_path.parent.glob("audit_*.json")}
    assert len(committed_bytes) == 2

    monkeypatch.setattr(Path, "unlink", original_unlink)
    retry_review = {**review, "updated_at": "2026-09-10T01:01:00"}
    result = report_workflow.update_latest_audit_review(retry_review)
    assert result and result != str(root_path)
    assert state["latest_audit_path"] == result
    assert state["latest_report"]["audit_paths"] == [str(root_path), result]
    assert state["latest_report"]["review_record"] == retry_review
    assert {path.name: path.read_bytes() for path in root_path.parent.glob("audit_*.json")} == committed_bytes


def test_recovery_rejects_same_visible_result_with_different_full_payload(audit_case):
    root_path, payload = audit_case
    audit.append_audit_event(root_path, "review.recorded", payload)
    # Roll the head back to exercise the old recovery-only shortcut as well.
    audit._write_head(root_path.parent, audit.load_and_verify_audit(root_path), root_path)
    changed = deepcopy(payload)
    changed["inputs"]["extra_context"] = "Different private input with the same visible report"
    with pytest.raises(audit.AuditIntegrityError):
        audit.append_audit_event(root_path, "review.recorded", changed)
    assert len(list(root_path.parent.glob("audit_*.json"))) == 2


def test_unrelated_looking_malformed_event_cannot_be_silently_omitted(audit_case):
    root_path, payload = audit_case
    (root_path.parent / "audit_unrelated_name.json").write_text("{}", encoding="utf-8")
    with pytest.raises(audit.AuditIntegrityError):
        audit.append_audit_event(root_path, "review.recorded", payload)


def test_deeply_nested_event_fails_with_a_controlled_integrity_error(tmp_path):
    path = tmp_path / "audit_deep.json"
    path.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
    with pytest.raises(audit.AuditIntegrityError):
        audit.load_and_verify_audit(path)


@pytest.mark.parametrize(
    "field",
    [
        "inputs",
        "area_selection",
        "analysis",
        "report_source",
        "grounding_evaluation",
        "model_name",
        "quality",
        "package_context",
        "human_review",
        "report_text",
        "export_register_snapshot",
    ],
)
@pytest.mark.parametrize("roll_back_head", [False, True])
def test_retry_requires_every_original_payload_field(audit_case, field, roll_back_head):
    root_path, payload = audit_case
    audit.append_audit_event(root_path, "review.recorded", payload)
    if roll_back_head:
        audit._write_head(root_path.parent, audit.load_and_verify_audit(root_path), root_path)
    before = {path.name: path.read_bytes() for path in root_path.parent.glob("audit_*.json")}
    changed = deepcopy(payload)
    if field in {"inputs", "analysis", "package_context"}:
        changed[field]["extra_context"] = "Different synthetic binding"
    elif field == "human_review":
        changed[field]["review_notes"] = "Different synthetic review"
    elif field == "report_text":
        changed[field] = changed[field].replace("Synthetic report", "Different report")
    else:
        changed[field] = {"synthetic_changed": True}
    with pytest.raises(audit.AuditIntegrityError):
        audit.append_audit_event(root_path, "review.recorded", changed)
    assert {path.name: path.read_bytes() for path in root_path.parent.glob("audit_*.json")} == before


def test_identical_concurrent_replays_share_one_direct_successor(audit_case):
    root_path, payload = audit_case
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(audit.append_audit_event, root_path, "review.recorded", deepcopy(payload)) for _ in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
    assert len(list(root_path.parent.glob("audit_*.json"))) == 2


@pytest.mark.parametrize("omitted", [("report_id",), ("report_version",), ("report_id", "report_version")])
def test_retry_preserves_supported_identity_defaults(audit_case, omitted):
    root_path, payload = audit_case
    for field in omitted:
        payload.pop(field)
    committed = audit.append_audit_event(root_path, "review.recorded", payload)
    assert audit.append_audit_event(root_path, "review.recorded", payload) == committed
    assert len(list(root_path.parent.glob("audit_*.json"))) == 2


def test_replay_never_skips_a_later_event_even_if_tip_payload_matches(audit_case):
    root_path, payload = audit_case
    first = audit.append_audit_event(root_path, "review.recorded", payload)
    second = audit.append_audit_event(first, "review.recorded", payload)
    with pytest.raises(audit.AuditIntegrityError, match="no longer the current"):
        audit.append_audit_event(root_path, "review.recorded", payload)
    assert len(list(root_path.parent.glob("audit_*.json"))) == 3
    assert Path(audit.append_audit_event(first, "review.recorded", payload)) == Path(second)


def test_renamed_valid_fork_remains_visible_to_recovery(audit_case):
    root_path, payload = audit_case
    first = Path(audit.append_audit_event(root_path, "review.recorded", payload))
    fork = json.loads(first.read_bytes())
    fork["audit_id"] = "distinct-fork"
    fork["record_hash"] = audit.sha256_json({key: value for key, value in fork.items() if key != "record_hash"})
    # Deliberately no report ID in the filename; content remains authoritative.
    (root_path.parent / "audit_unrelated_name.json").write_text(json.dumps(fork), encoding="utf-8")
    with pytest.raises(audit.AuditIntegrityError, match="multiple successors"):
        audit.append_audit_event(root_path, "review.recorded", payload)


def test_single_file_byte_budget_accepts_boundary_then_rejects_larger_file(audit_case, monkeypatch):
    root_path, _payload = audit_case
    size = root_path.stat().st_size
    monkeypatch.setattr(audit, "MAX_AUDIT_FILE_BYTES", size)
    assert audit.load_and_verify_audit(root_path)["report_id"] == "recovery-budget-test"
    monkeypatch.setattr(audit, "MAX_AUDIT_FILE_BYTES", size - 1)
    with pytest.raises(audit.AuditIntegrityError, match="single-file safety limit"):
        audit.load_and_verify_audit(root_path)


def test_file_growth_after_stat_still_uses_a_bounded_read(audit_case, monkeypatch):
    root_path, _payload = audit_case
    initial_bytes = root_path.read_bytes()
    read_sizes = []

    class GrowingFile(BytesIO):
        def read(self, size=-1):
            read_sizes.append(size)
            return super().read(size)

    original_open = Path.open

    def substitute_growing_file(path, *args, **kwargs):
        if path == root_path and args == ("rb",):
            return GrowingFile(initial_bytes + b" " * 100)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(audit, "MAX_AUDIT_FILE_BYTES", len(initial_bytes))
    monkeypatch.setattr(Path, "open", substitute_growing_file)
    with pytest.raises(audit.AuditIntegrityError, match="growth exceeds"):
        audit.load_and_verify_audit(root_path)
    assert read_sizes == [len(initial_bytes) + 1]


def test_metadata_byte_budget_accepts_boundary_then_rejects_larger_head(audit_case, monkeypatch):
    root_path, payload = audit_case
    head_path = audit._head_path(root_path.parent, payload["report_id"])
    size = head_path.stat().st_size
    monkeypatch.setattr(audit, "MAX_AUDIT_METADATA_BYTES", size)
    assert audit._read_audit_head(head_path)["report_id"] == payload["report_id"]
    monkeypatch.setattr(audit, "MAX_AUDIT_METADATA_BYTES", size - 1)
    with pytest.raises(audit.AuditIntegrityError, match="single-file safety limit"):
        audit._read_audit_head(head_path)


def test_revision_claim_read_obeys_metadata_budget_without_deleting_claim(audit_case, monkeypatch):
    root_path, _payload = audit_case
    root = audit.load_and_verify_audit(root_path)
    binding = audit._parent_binding_for_record(root)
    claim_path = audit._revision_claim_path(root_path.parent, root)
    claim = {"parent": binding, "state": "pending"}
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
    original = claim_path.read_bytes()
    monkeypatch.setattr(audit, "MAX_AUDIT_METADATA_BYTES", len(original))
    with pytest.raises(audit.AuditIntegrityError, match="still pending"):
        audit._recover_revision_claim(claim_path, root_path.parent, binding)
    monkeypatch.setattr(audit, "MAX_AUDIT_METADATA_BYTES", len(original) - 1)
    with pytest.raises(audit.AuditIntegrityError, match="single-file safety limit"):
        audit._recover_revision_claim(claim_path, root_path.parent, binding)
    assert claim_path.read_bytes() == original


@pytest.mark.parametrize("malformed_head", [None, [], {}, {"report_id": []}])
def test_malformed_head_is_not_silently_replaced(audit_case, malformed_head):
    root_path, payload = audit_case
    head_path = audit._head_path(root_path.parent, payload["report_id"])
    head_path.write_text(json.dumps(malformed_head), encoding="utf-8")
    original = head_path.read_bytes()
    with pytest.raises(audit.AuditIntegrityError, match="malformed fields"):
        audit._recover_unique_report_head(root_path.parent, payload["report_id"])
    assert head_path.read_bytes() == original


def test_missing_head_remains_recoverable_from_the_complete_unique_graph(audit_case):
    root_path, payload = audit_case
    head_path = audit._head_path(root_path.parent, payload["report_id"])
    original = head_path.read_bytes()
    head_path.unlink()
    assert audit._recover_unique_report_head(root_path.parent, payload["report_id"])[1] == root_path
    assert head_path.read_bytes() == original


def test_supported_historical_other_report_is_validated_and_read_bytes_are_budgeted(audit_case, monkeypatch):
    root_path, payload = audit_case
    other = json.loads(root_path.read_bytes())
    other["report_id"] = "synthetic-other-historical-report"
    other["audit_id"] = "synthetic-other-historical-event"
    other["quality_policy_version"] = "governed-report-v1"
    other["quality"]["quality_policy_version"] = "governed-report-v1"
    other.pop("quality_policy_fingerprint")
    other["quality"].pop("quality_policy_fingerprint")
    other["record_hash"] = audit.sha256_json({key: val for key, val in other.items() if key != "record_hash"})
    other_path = root_path.parent / "audit_other_historical.json"
    other_path.write_text(json.dumps(other), encoding="utf-8")
    original = other_path.read_bytes()
    assert audit._recover_unique_report_head(root_path.parent, payload["report_id"])[1] == root_path
    assert audit.load_and_verify_audit(other_path)["quality_policy_version"] == "governed-report-v1"
    assert Path(audit.append_audit_event(root_path, "review.recorded", payload)).exists()
    assert other_path.read_bytes() == original

    total = sum(path.stat().st_size for path in root_path.parent.glob("audit_*.json"))
    monkeypatch.setattr(audit, "MAX_AUDIT_OPERATION_BYTES", total)
    assert len(audit._load_report_audit_events(root_path.parent, payload["report_id"])) == 2
    monkeypatch.setattr(audit, "MAX_AUDIT_OPERATION_BYTES", total - 1)
    with pytest.raises(audit.AuditIntegrityError, match="cumulative read safety limit"):
        audit._load_report_audit_events(root_path.parent, payload["report_id"])


def test_cumulative_read_budget_applies_across_all_chain_files(audit_case, monkeypatch):
    root_path, payload = audit_case
    tip = Path(audit.append_audit_event(root_path, "review.recorded", payload))
    total_bytes = root_path.stat().st_size + tip.stat().st_size
    monkeypatch.setattr(audit, "MAX_AUDIT_OPERATION_BYTES", total_bytes)
    assert audit.load_and_verify_audit(tip)["previous_audit_id"]
    monkeypatch.setattr(audit, "MAX_AUDIT_OPERATION_BYTES", total_bytes - 1)
    with pytest.raises(audit.AuditIntegrityError, match="cumulative read safety limit"):
        audit.load_and_verify_audit(tip)
    # Failed scopes do not poison the independent operation's counter.
    assert audit.load_and_verify_audit(root_path)["event_type"] == "report.created"


def test_directory_budget_accepts_boundary_and_never_returns_partial_graph(audit_case, monkeypatch):
    root_path, payload = audit_case
    count = len(list(root_path.parent.iterdir()))
    monkeypatch.setattr(audit, "MAX_AUDIT_SCAN_ENTRIES", count)
    assert audit._recover_unique_report_head(root_path.parent, payload["report_id"])[1] == root_path
    monkeypatch.setattr(audit, "MAX_AUDIT_SCAN_ENTRIES", count - 1)
    with pytest.raises(audit.AuditIntegrityError, match="directory-entry safety limit"):
        audit._recover_unique_report_head(root_path.parent, payload["report_id"])


def test_chain_event_budget_accepts_boundary_then_rejects_overflow(audit_case, monkeypatch):
    root_path, payload = audit_case
    first = audit.append_audit_event(root_path, "review.recorded", payload)
    tip = audit.append_audit_event(first, "review.recorded", payload)
    monkeypatch.setattr(audit, "MAX_AUDIT_CHAIN_EVENTS", 3)
    assert len(audit.capture_current_audit_chain(tip)) == 3
    monkeypatch.setattr(audit, "MAX_AUDIT_CHAIN_EVENTS", 2)
    for operation in (
        lambda: audit.load_and_verify_audit(tip),
        lambda: audit._recover_unique_report_head(root_path.parent, payload["report_id"]),
        lambda: audit.capture_audit_chain_at_event(tip),
    ):
        with pytest.raises(audit.AuditIntegrityError, match="event-count safety limit"):
            operation()


def _revision(parent, payload, version):
    return audit.save_revision_audit(
        parent,
        {
            "report_id": f"synthetic-revision-{version}",
            "report_version": version,
            "inputs": deepcopy(payload["inputs"]),
            "area_selection": payload["area_selection"],
            "analysis": deepcopy(payload["analysis"]),
            "report_text": append_human_signoff("# Synthetic revision", {"approval_status": DRAFT_STATUS}),
            "human_review": {"approval_status": DRAFT_STATUS},
            "export_register_snapshot": build_export_register_snapshot(),
        },
    )


def test_lineage_depth_budget_accepts_boundary_then_rejects_overflow(audit_case, monkeypatch):
    root_path, payload = audit_case
    parent = _revision(root_path, payload, 2)
    child_path = _revision(parent, payload, 3)
    child = audit.load_and_verify_audit(child_path)
    monkeypatch.setattr(audit, "MAX_AUDIT_LINEAGE_DEPTH", 2)
    assert len(audit.capture_parent_lineage(child, parent)) == 2
    monkeypatch.setattr(audit, "MAX_AUDIT_LINEAGE_DEPTH", 1)
    with pytest.raises(audit.AuditIntegrityError, match="ancestor-count safety limit"):
        audit.capture_parent_lineage(child, parent)


@pytest.mark.parametrize(
    ("limit_name", "at_limit", "over_limit"),
    [
        ("MAX_AUDIT_JSON_DEPTH", {"child": 0}, {"child": {"nested": 0}}),
        ("MAX_AUDIT_JSON_NODES", {"child": 0}, {"child": 0, "another": 0}),
    ],
)
def test_json_structure_boundaries_are_explicit(limit_name, at_limit, over_limit, monkeypatch):
    monkeypatch.setattr(audit, limit_name, 1 if limit_name.endswith("DEPTH") else 2)
    audit._validate_json_shape(at_limit)
    with pytest.raises(audit.AuditIntegrityError, match="structure safety limit"):
        audit._validate_json_shape(over_limit)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("report_id", []),
        ("audit_id", {}),
        ("report_status", []),
        ("previous_audit_file", {}),
        ("analysis", None),
        ("quality", None),
        ("event_type", {}),
        ("parent_audit_binding", []),
    ],
)
def test_rehashed_malformed_record_shape_is_rejected_without_raw_exceptions(audit_case, field, value):
    root_path, _payload = audit_case
    record = json.loads(root_path.read_bytes())
    record[field] = value
    record["record_hash"] = audit.sha256_json({key: val for key, val in record.items() if key != "record_hash"})
    with pytest.raises(audit.AuditIntegrityError):
        audit.validate_audit_record(record)


def test_bad_nested_quality_gate_is_rejected_without_attribute_error(audit_case):
    root_path, _payload = audit_case
    record = json.loads(root_path.read_bytes())
    record["quality"]["approval_gate"] = None
    record["record_hash"] = audit.sha256_json({key: val for key, val in record.items() if key != "record_hash"})
    with pytest.raises(audit.AuditIntegrityError, match="malformed quality"):
        audit.validate_audit_record(record)


def test_recursion_error_from_decoder_is_always_a_controlled_failure(tmp_path):
    path = tmp_path / "audit_recursion.json"
    path.write_text("[" * 1500 + "0" + "]" * 1500, encoding="utf-8")
    old_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(1000)
        with pytest.raises(audit.AuditIntegrityError):
            audit.load_and_verify_audit(path)
    finally:
        sys.setrecursionlimit(old_limit)
