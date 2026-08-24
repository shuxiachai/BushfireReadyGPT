import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import audit, session_store
from src.report_template import append_human_signoff


def _sensitive_payload():
    review_record = {
        "approval_status": "Draft - human review required",
        "reviewer_name": "Sensitive Reviewer Name",
        "review_notes": "Sensitive free-text note",
    }
    return {
        "report_id": "report-privacy-test",
        "report_version": 1,
        "report_source": "generated",
        "inputs": {
            "location": "Private Farm Address",
            "audience": "Named household",
            "scenario": "Household preparedness",
            "concerns": ["Evacuation"],
            "timeframe": "7-day action plan",
            "extra_context": "Resident has a private health condition.",
            "reviewer_name": "Sensitive Reviewer Name",
            "review_notes": "Sensitive free-text note",
        },
        "analysis": {
            "profile": {"state": "Queensland", "location": "Private Farm Address"},
            "evidence_confidence": [{"code": "O1"}],
        },
        "report_status": "Draft - human review required",
        "human_review": review_record,
        "report_text": append_human_signoff("Sensitive complete report body", review_record),
    }


def test_default_audit_is_minimal_atomic_and_hash_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.delenv("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", raising=False)

    audit_path = Path(audit.save_report_audit(_sensitive_payload()))
    raw = audit_path.read_text(encoding="utf-8")
    record = audit.load_and_verify_audit(audit_path)

    assert "Sensitive Reviewer Name" not in raw
    assert "Sensitive free-text note" not in raw
    assert "Sensitive complete report body" not in raw
    assert "Resident has a private health condition" not in raw
    assert record["privacy"]["contains_full_report_text"] is False
    assert record["report_content"]["character_count"] > 0
    assert not list(tmp_path.glob("*.tmp"))


def test_audit_records_only_non_secret_model_boundary_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.delenv("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", raising=False)
    payload = _sensitive_payload()
    payload.update(
        {
            "model_provider": "ollama",
            "model_name": "remote-model",
            "model_endpoint_boundary": "external",
            "external_model_acknowledged_at": "2026-08-21T01:02:03Z",
            "api_key": "MUST-NOT-APPEAR-IN-AUDIT",
        }
    )

    audit_path = Path(audit.save_report_audit(payload))
    raw = audit_path.read_text(encoding="utf-8")
    record = audit.load_and_verify_audit(audit_path)

    assert record["model_provider"] == "ollama"
    assert record["model_name"] == "remote-model"
    assert record["model_endpoint_boundary"] == "external"
    assert record["external_model_acknowledged_at"] == "2026-08-21T01:02:03Z"
    assert "api_key" not in record
    assert "MUST-NOT-APPEAR-IN-AUDIT" not in raw


def test_review_event_appends_a_verified_chain_without_rewriting_creation_event(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    first_path = Path(audit.save_report_audit(_sensitive_payload()))
    original_bytes = first_path.read_bytes()
    review_record = {
        "approval_status": "Reviewed draft",
        "reviewer_name": "Reviewer",
        "reviewer_role": "Preparedness lead",
        "organisation_name": "Test organisation",
    }
    updated_report = append_human_signoff(
        "Sensitive complete report body",
        review_record,
    )

    second_path = Path(
        audit.append_audit_event(
            first_path,
            "review.recorded",
            {
                "report_id": "report-privacy-test",
                "report_version": 1,
                "report_text": updated_report,
                "analysis": _sensitive_payload()["analysis"],
                "report_status": "Reviewed draft",
                "human_review": review_record,
                "package_context": {
                    "organisation_name": "Test organisation",
                    "location": "Private Farm Address",
                    "audience": "Named household",
                    "scenario": "Household preparedness",
                    "report_status": "Reviewed draft",
                    "report_id": "report-privacy-test",
                    "report_version": 1,
                },
            },
        )
    )

    assert second_path != first_path
    assert first_path.read_bytes() == original_bytes
    assert audit.get_audit_chain_paths(second_path) == [first_path.resolve(), second_path.resolve()]
    second = audit.load_and_verify_audit(second_path)
    assert second["previous_record_hash"] == audit.load_and_verify_audit(first_path)["record_hash"]


def test_tampered_audit_cannot_receive_a_new_event(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    first_path = Path(audit.save_report_audit(_sensitive_payload()))
    record = json.loads(first_path.read_text(encoding="utf-8"))
    record["report_status"] = "Approved by organisation"
    first_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(audit.AuditIntegrityError, match="hash verification failed"):
        audit.append_audit_event(
            first_path,
            "review.recorded",
            {
                "report_id": "report-privacy-test",
                "report_version": 1,
                "report_text": "Sensitive complete report body",
                "report_status": "Needs revision",
                "human_review": {"approval_status": "Needs revision"},
                "package_context": {
                    "location": "Private Farm Address",
                    "audience": "Named household",
                    "scenario": "Household preparedness",
                    "report_status": "Needs revision",
                    "report_id": "report-privacy-test",
                    "report_version": 1,
                },
            },
        )


def test_clear_conversation_removes_session_but_preserves_governed_artifacts(tmp_path, monkeypatch):
    session_path = tmp_path / "session.json"
    interaction_path = tmp_path / "interaction.jsonl"
    audit_path = tmp_path / "audit.json"
    saved_report_path = tmp_path / "saved_report.md"
    for path in (session_path, interaction_path, audit_path, saved_report_path):
        path.write_text("retained test content", encoding="utf-8")

    state = {
        "model_client": SimpleNamespace(),
        "messages": [{"role": "user", "content": "private"}],
    }
    rerun_calls = []
    monkeypatch.setattr(session_store, "SESSION_STATE_PATH", str(session_path))
    monkeypatch.setattr(session_store, "INTERACTION_LOG_PATH", str(interaction_path))
    monkeypatch.setattr(
        session_store,
        "st",
        SimpleNamespace(session_state=state, rerun=lambda: rerun_calls.append(True)),
    )

    session_store.clear_conversation()

    assert state == {}
    assert not session_path.exists()
    assert not interaction_path.exists()
    assert audit_path.exists()
    assert saved_report_path.exists()
    assert rerun_calls == [True]
