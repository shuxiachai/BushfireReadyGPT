import json
from pathlib import Path

import pytest

from src import audit
from src import export_package as export_package_module
from src import report_generation_quality as quality_policy_module
from src.agents.report_quality_agent import ReportQualityAgent
from src.export_package import create_pilot_export_package
from src.governance import DRAFT_STATUS, NEEDS_REVISION_STATUS
from src.report_generation_quality import (
    CURRENT_POLICY,
    QUALITY_POLICY_FINGERPRINT,
    QUALITY_POLICY_MANIFEST,
    READABLE_QUALITY_POLICY_BINDINGS,
    SUPPORTED_HISTORICAL_POLICIES,
    quality_policy_metadata,
)
from src.report_template import append_human_signoff


def _draft_review():
    return audit.canonical_review_record({}, default_status=DRAFT_STATUS)


def _context(report_id, status=DRAFT_STATUS):
    return {
        "report_status": status,
        "report_id": report_id,
        "report_version": 1,
    }


def _create_report(tmp_path, monkeypatch, report_id="historical-policy"):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.delenv("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    review = _draft_review()
    report_text = append_human_signoff("# Historical policy report", review)
    path = Path(
        audit.save_report_audit(
            {
                "report_id": report_id,
                "report_version": 1,
                "report_text": report_text,
                "analysis": {},
                "report_status": DRAFT_STATUS,
                "human_review": review,
                "package_context": _context(report_id),
            }
        )
    )
    return path, report_text, review


def _rewrite_as_historical(path, version="governed-report-v1"):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    record["quality_policy_version"] = version
    record["quality"]["quality_policy_version"] = version
    record.pop("quality_policy_fingerprint")
    record["quality"].pop("quality_policy_fingerprint")
    record["record_hash"] = audit.sha256_json({key: value for key, value in record.items() if key != "record_hash"})
    Path(path).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def _rewrite_as_fingerprinted_historical(path, version, fingerprint):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    record["quality_policy_version"] = version
    record["quality_policy_fingerprint"] = fingerprint
    record["quality"]["quality_policy_version"] = version
    record["quality"]["quality_policy_fingerprint"] = fingerprint
    record["record_hash"] = audit.sha256_json({key: value for key, value in record.items() if key != "record_hash"})
    Path(path).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def test_policy_identity_is_stable_and_exposed_as_detached_metadata():
    metadata = quality_policy_metadata()

    assert metadata == {
        "version": CURRENT_POLICY,
        "fingerprint": QUALITY_POLICY_FINGERPRINT,
        "manifest": QUALITY_POLICY_MANIFEST,
    }
    assert len(QUALITY_POLICY_FINGERPRINT) == 64
    assert "governed-report-v1" in SUPPORTED_HISTORICAL_POLICIES
    assert READABLE_QUALITY_POLICY_BINDINGS["governed-report-v3"] == frozenset(
        {"6968d649b4ee0cc57a1365470dbdef9fa20803e778c56c1235c1053c180a74e2"}
    )
    assert READABLE_QUALITY_POLICY_BINDINGS["governed-report-v4"] == frozenset(
        {"b32323fe77b1d7f620735b1cc734152a06b37867958a86f3bf8840b304be76d7"}
    )
    assert READABLE_QUALITY_POLICY_BINDINGS["governed-report-v5"] == frozenset(
        {"0221e3725e10e6aa861f3ab4ac1387a5bf8a04722c2abb11a8600d3c0d651e06"}
    )
    assert QUALITY_POLICY_FINGERPRINT in READABLE_QUALITY_POLICY_BINDINGS[CURRENT_POLICY]
    metadata["manifest"]["policy_version"] = "tampered"
    assert QUALITY_POLICY_MANIFEST["policy_version"] == CURRENT_POLICY


def test_safety_quality_retains_only_code_count_and_claim_hash():
    secret_claim = "Smith Road is open today for PRIVATE-CODE-91827."

    quality = ReportQualityAgent().run(secret_claim)
    raw = json.dumps(quality)
    safety_check = next(item for item in quality["checks"] if item["name"] == "Safety boundary assertions")

    assert secret_claim not in raw
    assert "PRIVATE-CODE-91827" not in raw
    assert safety_check["status"] == "fail"
    assert safety_check["privacy_minimised_findings"]
    assert set(safety_check["privacy_minimised_findings"][0]) == {
        "code",
        "count",
        "claim_hash",
    }
    assert len(safety_check["privacy_minimised_findings"][0]["claim_hash"]) == 64


def test_default_audit_does_not_persist_safety_violation_excerpt(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.delenv("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    review = _draft_review()
    private_claim = "Smith Road is open today for PRIVATE-CODE-91827."
    report_text = append_human_signoff(private_claim, review)

    path = Path(
        audit.save_report_audit(
            {
                "report_id": "privacy-minimised-safety",
                "report_version": 1,
                "report_text": report_text,
                "analysis": {},
                "human_review": review,
                "package_context": _context("privacy-minimised-safety"),
            }
        )
    )
    raw = path.read_text(encoding="utf-8")
    record = audit.load_and_verify_audit(path)
    safety_check = next(item for item in record["quality"]["checks"] if item["name"] == "Safety boundary assertions")

    assert "PRIVATE-CODE-91827" not in raw
    assert private_claim not in raw
    assert safety_check["privacy_minimised_findings"][0]["code"] == "road_status_assertion"
    assert record["quality_policy_version"] == CURRENT_POLICY
    assert record["quality_policy_fingerprint"] == QUALITY_POLICY_FINGERPRINT


def test_supported_historical_policy_is_readable_but_cannot_record_review(tmp_path, monkeypatch):
    path, report_text, review = _create_report(tmp_path, monkeypatch)
    historical = _rewrite_as_historical(path)

    assert audit.validate_audit_record(historical) is historical
    with pytest.raises(audit.AuditIntegrityError, match="Historical quality-policy audits are read-only"):
        audit.append_audit_event(
            path,
            "review.recorded",
            {
                "report_id": "historical-policy",
                "report_version": 1,
                "report_text": report_text,
                "analysis": {},
                "report_status": DRAFT_STATUS,
                "human_review": review,
                "package_context": _context("historical-policy"),
            },
        )


def test_unknown_policy_binding_is_not_readable(tmp_path, monkeypatch):
    path, _report_text, _review = _create_report(tmp_path, monkeypatch, "unknown-policy")
    unknown = _rewrite_as_historical(path, version="governed-report-v999")

    with pytest.raises(audit.AuditIntegrityError, match="unknown governed-report quality policy"):
        audit.validate_audit_record(unknown)


def test_quality_reassessment_upgrades_policy_without_claiming_human_review(tmp_path, monkeypatch):
    path, report_text, review = _create_report(tmp_path, monkeypatch)
    original_bytes = path.read_bytes()
    _rewrite_as_historical(path)
    historical_bytes = path.read_bytes()

    reassessed_path = Path(
        audit.append_quality_reassessment(
            path,
            {
                "report_id": "historical-policy",
                "report_version": 1,
                "report_text": report_text,
                "analysis": {},
                "report_status": DRAFT_STATUS,
                "human_review": review,
                "package_context": _context("historical-policy"),
            },
        )
    )
    reassessed = audit.load_and_verify_audit(reassessed_path)

    assert original_bytes != historical_bytes
    assert path.read_bytes() == historical_bytes
    assert reassessed["event_type"] == "quality.reassessed"
    assert reassessed["quality_policy_version"] == CURRENT_POLICY
    assert reassessed["quality_policy_fingerprint"] == QUALITY_POLICY_FINGERPRINT
    assert reassessed["quality_reassessment"]["human_review_performed"] is False
    assert reassessed["quality_reassessment"]["report_content_changed"] is False

    needs_revision = audit.canonical_review_record(
        {"approval_status": NEEDS_REVISION_STATUS},
    )
    review_path = audit.append_audit_event(
        reassessed_path,
        "review.recorded",
        {
            "report_id": "historical-policy",
            "report_version": 1,
            "report_text": append_human_signoff("# Historical policy report", needs_revision),
            "analysis": {},
            "report_status": NEEDS_REVISION_STATUS,
            "human_review": needs_revision,
            "package_context": _context("historical-policy", NEEDS_REVISION_STATUS),
        },
    )
    assert audit.load_and_verify_audit(review_path)["event_type"] == "review.recorded"


def test_v5_reassessment_cannot_skip_v6_legacy_scenario_and_focus_gates(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.delenv("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    review = _draft_review()
    report_id = "legacy-contract-gates"
    report_text = append_human_signoff("# Generic historical report", review)
    legacy_analysis = {
        "profile": {
            "scenario": "Household bushfire preparedness",
            "concerns": ["emergency kits"],
        },
        "plan": {},
    }
    path = Path(
        audit.save_report_audit(
            {
                "report_id": report_id,
                "report_version": 1,
                "report_text": report_text,
                "analysis": legacy_analysis,
                "report_status": DRAFT_STATUS,
                "human_review": review,
                "package_context": _context(report_id),
            }
        )
    )
    _rewrite_as_fingerprinted_historical(
        path,
        "governed-report-v5",
        "0221e3725e10e6aa861f3ab4ac1387a5bf8a04722c2abb11a8600d3c0d651e06",
    )

    reassessed_path = audit.append_quality_reassessment(
        path,
        {
            "report_id": report_id,
            "report_version": 1,
            "report_text": report_text,
            "analysis": legacy_analysis,
            "report_status": DRAFT_STATUS,
            "human_review": review,
            "package_context": _context(report_id),
        },
    )
    reassessed = audit.load_and_verify_audit(reassessed_path)
    failures = {item["name"] for item in reassessed["quality"]["approval_gate"]["blocking_failures"]}

    assert reassessed["quality_policy_version"] == "governed-report-v6"
    assert reassessed["generation_gate_blocked"] is True
    assert {"Selected scenario coverage", "Selected focus-area coverage"} <= failures


def test_quality_reassessment_rejects_report_or_signoff_changes(tmp_path, monkeypatch):
    path, _report_text, review = _create_report(tmp_path, monkeypatch)
    _rewrite_as_historical(path)

    with pytest.raises(audit.AuditIntegrityError, match="may not change the governed report body"):
        audit.append_quality_reassessment(
            path,
            {
                "report_id": "historical-policy",
                "report_version": 1,
                "report_text": append_human_signoff("# Changed report", review),
                "analysis": {},
                "report_status": DRAFT_STATUS,
                "human_review": review,
                "package_context": _context("historical-policy"),
            },
        )


def test_historical_reassessment_remains_readable_after_runtime_policy_advances(tmp_path, monkeypatch):
    path, report_text, review = _create_report(tmp_path, monkeypatch, "future-readable")
    _rewrite_as_historical(path)
    reassessed_path = Path(
        audit.append_quality_reassessment(
            path,
            {
                "report_id": "future-readable",
                "report_version": 1,
                "report_text": report_text,
                "analysis": {},
                "report_status": DRAFT_STATUS,
                "human_review": review,
                "package_context": _context("future-readable"),
            },
        )
    )

    monkeypatch.setattr(audit, "CURRENT_POLICY", "governed-report-v7")
    monkeypatch.setattr(audit, "QUALITY_POLICY_FINGERPRINT", "7" * 64)
    monkeypatch.setattr(quality_policy_module, "CURRENT_POLICY", "governed-report-v7")
    monkeypatch.setattr(quality_policy_module, "QUALITY_POLICY_FINGERPRINT", "7" * 64)

    record = audit.load_and_verify_audit(reassessed_path)
    assert record["quality_policy_version"] == "governed-report-v6"
    assert record["quality_policy_fingerprint"] in READABLE_QUALITY_POLICY_BINDINGS["governed-report-v6"]


def test_fingerprinted_v3_chain_remains_readable_and_reassesses_to_current_policy(tmp_path, monkeypatch):
    path, report_text, review = _create_report(tmp_path, monkeypatch, "v3-compatible")
    v3_fingerprint = "6968d649b4ee0cc57a1365470dbdef9fa20803e778c56c1235c1053c180a74e2"
    historical = _rewrite_as_fingerprinted_historical(path, "governed-report-v3", v3_fingerprint)

    assert audit.validate_audit_record(historical) is historical
    with pytest.raises(audit.AuditIntegrityError, match="Historical quality-policy audits are read-only"):
        audit.append_audit_event(
            path,
            "review.recorded",
            {
                "report_id": "v3-compatible",
                "report_version": 1,
                "report_text": report_text,
                "analysis": {},
                "report_status": DRAFT_STATUS,
                "human_review": review,
                "package_context": _context("v3-compatible"),
            },
        )

    reassessed_path = audit.append_quality_reassessment(
        path,
        {
            "report_id": "v3-compatible",
            "report_version": 1,
            "report_text": report_text,
            "analysis": {},
            "report_status": DRAFT_STATUS,
            "human_review": review,
            "package_context": _context("v3-compatible"),
        },
    )
    reassessed = audit.load_and_verify_audit(reassessed_path)
    assert reassessed["quality_policy_version"] == CURRENT_POLICY == "governed-report-v6"
    assert reassessed["quality_policy_fingerprint"] == QUALITY_POLICY_FINGERPRINT
    assert reassessed["previous_record_hash"] == historical["record_hash"]


def test_quality_reassessment_head_cannot_be_exported_as_a_human_review(monkeypatch):
    monkeypatch.setattr(
        export_package_module,
        "capture_current_audit_chain",
        lambda _path: [
            {
                "record": {
                    "event_type": "quality.reassessed",
                    "report_status": "Approved by organisation",
                    "quality_policy_version": CURRENT_POLICY,
                    "quality_policy_fingerprint": QUALITY_POLICY_FINGERPRINT,
                }
            }
        ],
    )

    with pytest.raises(audit.AuditIntegrityError, match="not a human review"):
        create_pilot_export_package("# Reassessed report", audit_path="reassessed-audit.json")
