import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from src import audit, report_workflow
from src.agents import run_analysis_pipeline
from src.agents.profile_agent import ProfileAgent
from src.agents.risk_context_agent import RiskContextAgent
from src.export_package import create_pilot_export_package
from src.export_register import REGISTER_SNAPSHOT_FILES, export_register_snapshot_hashes
from src.governance import build_review_checklist_snapshot
from src.model_runtime import ModelServiceError
from src.report_template import append_human_signoff

_RAW_SAVE_REPORT_AUDIT = audit.save_report_audit


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        self[name] = value


def _profile(location):
    return ProfileAgent().run(
        location,
        "community residents",
        "Community bushfire preparedness",
        ["Evacuation"],
        "7-day action plan",
        "",
    )


def _draft_review_record():
    return {
        "approval_status": "Draft - human review required",
        "reviewer_name": "",
        "reviewer_role": "",
        "review_date": "",
        "organisation_name": "",
        "review_notes": "",
        "review_checklist": build_review_checklist_snapshot(),
        "review_checklist_complete": False,
    }


def _save_audit(payload):
    values = dict(payload)
    review_record = audit.canonical_review_record(
        values.get("human_review"),
        default_status="Draft - human review required",
    )
    values["human_review"] = review_record
    values["report_text"] = append_human_signoff(values.get("report_text") or "", review_record)
    return _RAW_SAVE_REPORT_AUDIT(values)


def _approved_review_record():
    return {
        "approval_status": "Approved by organisation",
        "reviewer_name": "Authorised Reviewer",
        "reviewer_role": "Preparedness lead",
        "review_date": "2026-08-21",
        "organisation_name": "Test Council",
        "review_notes": "Verified locally.",
        "review_checklist": build_review_checklist_snapshot(lambda _item_id: True),
        "review_checklist_complete": True,
    }


def _needs_revision_event(report_id, report_text="Report", report_version=1, **context):
    status = "Needs revision"
    review_record = {"approval_status": status}
    return {
        "report_id": report_id,
        "report_version": report_version,
        "report_text": append_human_signoff(report_text, review_record),
        "report_status": status,
        "human_review": review_record,
        "package_context": {
            **context,
            "report_status": status,
            "report_id": report_id,
            "report_version": report_version,
        },
    }


def _frozen_register_snapshot(label="ORIGINAL"):
    return {path: f"{label}\n{path}\n" for path in REGISTER_SNAPSHOT_FILES}


def _revision_payload(
    report_id,
    parent_report_id,
    report_text="# Revised report",
    register_snapshot=None,
):
    review_record = _draft_review_record()
    return {
        "report_id": report_id,
        "report_version": 2,
        "parent_report_id": parent_report_id,
        "report_source": "revised",
        "revision_request": "Clarify the governed action plan.",
        "report_text": append_human_signoff(report_text, review_record),
        "inputs": {},
        "analysis": {},
        "report_status": review_record["approval_status"],
        "human_review": review_record,
        "export_register_snapshot": register_snapshot or _frozen_register_snapshot(),
        "package_context": {
            "report_status": review_record["approval_status"],
            "report_id": report_id,
            "report_version": 2,
        },
    }


@pytest.mark.parametrize(
    ("location", "expected_state", "forbidden_locality"),
    [
        ("100 Brisbane Street, Sydney NSW", "New South Wales", "Brisbane"),
        ("10 Perth Street, Toowoomba", "Australia", "Perth"),
        ("10 Cairns Street, Darwin", "Northern Territory", "Cairns"),
    ],
)
def test_street_names_do_not_impersonate_configured_localities(
    location,
    expected_state,
    forbidden_locality,
):
    profile = _profile(location)

    assert profile["state"] == expected_state
    assert profile["locality"] != forbidden_locality


def test_explicit_queensland_state_prevents_perth_local_risk_match():
    profile = _profile("Perth, Queensland")
    result = RiskContextAgent().run(profile)

    assert profile["state"] == "Queensland"
    assert "queensland_general" in result["matched_rule_ids"]
    assert "perth_local" not in result["matched_rule_ids"]
    assert "western_australia_general" not in result["matched_rule_ids"]


def test_package_context_is_bound_to_latest_report_snapshot(monkeypatch):
    state = SessionState(
        {
            "form_location": "CURRENT FORM LOCATION",
            "form_audience": "CURRENT FORM AUDIENCE",
            "selected_map_area": {"state": "Victoria", "area_name": "Current map"},
            "organisation_name": "CURRENT FORM ORGANISATION",
            "latest_report": {
                "id": "snapshot-report",
                "version": 3,
                "inputs": {
                    "pilot_mode": "School preparedness",
                    "organisation_name": "Snapshot organisation",
                    "location": "Cairns, Queensland",
                    "audience": "Snapshot audience",
                    "scenario": "Snapshot scenario",
                },
                "area_selection": {
                    "state": "Queensland",
                    "level": "SA2",
                    "area_name": "Cairns City",
                },
                "review_record": {
                    "approval_status": "Reviewed draft",
                    "organisation_name": "Reviewed snapshot organisation",
                },
                "model_context": {
                    "model_provider": "ollama",
                    "model_name": "snapshot-model",
                    "model_endpoint_boundary": "local_loopback",
                },
            },
        }
    )
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))

    context = report_workflow.get_package_context()

    assert context["location"] == "Cairns, Queensland"
    assert context["audience"] == "Snapshot audience"
    assert context["selected_map_area"]["area_name"] == "Cairns City"
    assert context["organisation_name"] == "Reviewed snapshot organisation"
    assert context["model_name"] == "snapshot-model"
    assert "CURRENT FORM" not in json.dumps(context)


def test_model_failure_does_not_replace_prior_analysis_or_report(monkeypatch):
    class FailingModelClient:
        def generate(self, _prompt):
            raise ModelServiceError("simulated model outage")

    prior_analysis = {"profile": {"location": "Prior location"}}
    prior_report = {"id": "prior-report", "version": 1, "text": "# Prior report"}
    state = SessionState(
        {
            "model_client": FailingModelClient(),
            "latest_analysis": prior_analysis,
            "latest_report": prior_report,
            "messages": [{"role": "assistant", "content": "existing"}],
        }
    )
    candidate_analysis = {"profile": {"location": "Candidate location"}}
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(report_workflow, "validate_current_report_form", lambda: None)
    monkeypatch.setattr(report_workflow, "validate_model_privacy_boundary", lambda: None)
    monkeypatch.setattr(
        report_workflow,
        "run_analysis_pipeline",
        lambda *args, **kwargs: candidate_analysis,
    )
    monkeypatch.setattr(report_workflow, "build_report_prompt", lambda *args, **kwargs: "prompt")

    response, error = report_workflow.generate_current_report(lambda: None)

    assert response is None
    assert error == "simulated model outage"
    assert state["latest_analysis"] is prior_analysis
    assert state["latest_report"] is prior_report
    assert state["messages"] == [{"role": "assistant", "content": "existing"}]


def test_audit_append_rejects_changed_configured_directory(tmp_path, monkeypatch):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", first_dir)
    first_path = _save_audit({"report_id": "directory-bound", "report_version": 1, "report_text": "Report"})
    monkeypatch.setattr(audit, "AUDIT_DIR", second_dir)

    with pytest.raises(audit.AuditIntegrityError, match="directory changed"):
        audit.append_audit_event(
            first_path,
            "review.recorded",
            _needs_revision_event("directory-bound"),
        )


def test_audit_append_rejects_a_stale_parent(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    first_path = _save_audit({"report_id": "linear-chain", "report_version": 1, "report_text": "Report"})
    audit.append_audit_event(
        first_path,
        "review.recorded",
        _needs_revision_event("linear-chain"),
    )

    with pytest.raises(audit.AuditIntegrityError, match="no longer the current report head"):
        audit.append_audit_event(
            first_path,
            "review.recorded",
            _needs_revision_event("linear-chain"),
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"report_id": "different-report"}, "report ID"),
        ({"report_version": 2}, "report version"),
    ],
)
def test_audit_append_enforces_report_identity_and_version(
    tmp_path,
    monkeypatch,
    overrides,
    message,
):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    first_path = _save_audit({"report_id": "fixed-report", "report_version": 1, "report_text": "Report"})
    payload = {**_needs_revision_event("fixed-report"), **overrides}
    payload["package_context"].update(overrides)

    with pytest.raises(audit.AuditIntegrityError, match=message):
        audit.append_audit_event(first_path, "review.recorded", payload)


def test_real_pipeline_minimal_audit_omits_private_values_and_absolute_paths(
    tmp_path,
    monkeypatch,
):
    private_location = "SECRET PRIVATE LOCATION 90817, Queensland"
    private_audience = "SECRET PRIVATE AUDIENCE 41952"
    private_current_use = "SECRET CURRENT USE 62570"
    analysis = run_analysis_pipeline(
        location=private_location,
        audience=private_audience,
        scenario="Community preparedness",
        concerns=["Evacuation"],
        timeframe="7-day action plan",
        extra_context="",
    )
    for item in analysis["evidence_confidence"]:
        item["current_use"] = private_current_use

    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.delenv("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    audit_path = Path(
        _save_audit(
            {
                "report_id": "minimal-real-pipeline",
                "report_version": 1,
                "report_text": "# Governed report",
                "inputs": {
                    "location": private_location,
                    "audience": private_audience,
                    "scenario": "Community preparedness",
                },
                "analysis": analysis,
            }
        )
    )
    raw = audit_path.read_text(encoding="utf-8")
    record = json.loads(raw)
    workspace = str(Path.cwd().resolve())

    assert private_location not in raw
    assert private_audience not in raw
    assert private_current_use not in raw
    assert workspace not in raw
    assert workspace.replace("\\", "\\\\") not in raw
    assert record["inputs"]["location_present"] is True
    assert record["inputs"]["audience_present"] is True
    assert all("current_use" not in item for item in record["analysis"]["evidence_confidence"])
    assert all(not Path(str(value)).is_absolute() for value in record["analysis"]["resolved_data_paths"].values())


def test_tampered_latest_report_cannot_receive_a_review_event(tmp_path, monkeypatch):
    draft_review = _draft_review_record()
    approval_record = _approved_review_record()
    original_text = "# Original governed report"
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    audit_path = _save_audit(
        {
            "report_id": "tamper-bound-report",
            "report_version": 1,
            "report_text": original_text,
            "human_review": draft_review,
        }
    )
    state = SessionState(
        {
            "latest_report": {
                "id": "tamper-bound-report",
                "version": 1,
                "text": original_text + "\nUNTRACKED TAMPER",
                "audit_path": audit_path,
                "review_record": draft_review,
            },
            "latest_audit_path": audit_path,
            "messages": [],
        }
    )
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))

    assert report_workflow.update_latest_audit_review(approval_record) is False
    assert list(tmp_path.glob("audit_*.json")) == [Path(audit_path)]


def test_tampered_analysis_snapshot_cannot_receive_a_review_event(tmp_path, monkeypatch):
    draft_review = _draft_review_record()
    original_analysis = {
        "data_integrity": {"core_ready": True, "custom_data": False},
        "profile": {"state": "Queensland"},
    }
    report_record = {
        "id": "analysis-bound-report",
        "version": 1,
        "text": "# Original governed report",
        "inputs": {
            "location": "Cairns, Queensland",
            "report_status": "Draft - human review required",
        },
        "area_selection": None,
        "analysis": original_analysis,
        "model_context": {
            "model_provider": "ollama",
            "model_name": "local-model",
            "model_endpoint_boundary": "local_loopback",
        },
        "review_record": draft_review,
    }
    package_context = report_workflow._package_context_for_record(report_record)
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    audit_path = _save_audit(
        {
            "report_id": report_record["id"],
            "report_version": report_record["version"],
            "report_text": report_record["text"],
            "inputs": report_record["inputs"],
            "area_selection": report_record["area_selection"],
            "analysis": original_analysis,
            **report_record["model_context"],
            "human_review": draft_review,
            "report_status": draft_review["approval_status"],
            "package_context": package_context,
        }
    )
    report_record["audit_path"] = audit_path
    report_record["analysis"] = {
        **original_analysis,
        "profile": {"state": "Western Australia"},
    }
    state = SessionState(
        {
            "latest_report": report_record,
            "latest_audit_path": audit_path,
            "messages": [],
        }
    )
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))

    assert report_workflow.update_latest_audit_review(_approved_review_record()) is False
    assert list(tmp_path.glob("audit_*.json")) == [Path(audit_path)]


def test_stale_passing_quality_cannot_approve_a_blocked_report():
    review_record = _approved_review_record()
    stale_quality = {
        "summary": {"passed": 12, "warnings": 0, "failed": 0, "total": 12},
        "approval_gate": {"passed": True, "blocking_failures": []},
    }

    error = report_workflow.validate_review_record(
        review_record,
        stale_quality,
        {
            "text": "# Incomplete and blocked report",
            "analysis": {"data_integrity": {"core_ready": True, "custom_data": False}},
        },
    )

    assert "failed Structural Report Check" in error


def test_audit_approval_rejects_unverified_selected_map_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    passing_quality = {
        "summary": {"passed": 1, "warnings": 0, "failed": 0, "total": 1},
        "approval_gate": {"passed": True, "blocking_failures": []},
    }
    monkeypatch.setattr(
        audit.ReportQualityAgent,
        "run",
        lambda _self, _text: passing_quality,
    )
    selection = {
        "state": "Queensland",
        "level": "SA2",
        "area_name": "Cairns City",
    }
    root_path = _save_audit(
        {
            "report_id": "unverified-map-approval",
            "report_version": 1,
            "report_text": "# Selected map report",
            "area_selection": selection,
            "analysis": {
                "data_integrity": {
                    "core_ready": True,
                    "custom_data": False,
                    "optional_map_state": "present_unverified",
                }
            },
        }
    )
    review = _approved_review_record()

    with pytest.raises(audit.AuditIntegrityError, match="sidecar-verified"):
        audit.append_audit_event(
            root_path,
            "review.recorded",
            {
                "report_id": "unverified-map-approval",
                "report_version": 1,
                "report_text": append_human_signoff("# Selected map report", review),
                "quality": passing_quality,
                "report_status": review["approval_status"],
                "human_review": review,
                "package_context": {
                    "organisation_name": review["organisation_name"],
                    "report_status": review["approval_status"],
                    "selected_map_area": selection,
                    "report_id": "unverified-map-approval",
                    "report_version": 1,
                },
            },
        )


def test_export_rejects_malformed_audit(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{}", encoding="utf-8")

    with pytest.raises(audit.AuditIntegrityError, match="schema"):
        create_pilot_export_package("# Report", audit_path=malformed, review_record={})


def test_pilot_governance_export_requires_a_verified_audit():
    with pytest.raises(audit.AuditIntegrityError, match="requires a verified current audit"):
        create_pilot_export_package(
            "# Unverified report",
            review_record={},
            package_context={},
        )


def test_audit_creation_rejects_context_detached_from_inputs(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)

    with pytest.raises(audit.AuditIntegrityError, match="does not match the report input"):
        _save_audit(
            {
                "report_id": "detached-context",
                "report_version": 1,
                "report_text": "# Report",
                "inputs": {"location": "Cairns, Queensland"},
                "package_context": {
                    "location": "Hobart, Tasmania",
                    "report_id": "detached-context",
                    "report_version": 1,
                },
            }
        )


def test_audit_append_rejects_changed_immutable_context(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    first_path = _save_audit(
        {
            "report_id": "immutable-context",
            "report_version": 1,
            "report_text": "# Report",
            "inputs": {"location": "Cairns, Queensland"},
        }
    )

    with pytest.raises(audit.AuditIntegrityError, match="changed immutable"):
        audit.append_audit_event(
            first_path,
            "review.recorded",
            {
                "report_id": "immutable-context",
                "report_version": 1,
                "report_text": "# Report",
                "report_status": "Reviewed draft",
                "human_review": {"approval_status": "Reviewed draft"},
                "package_context": {
                    "location": "Hobart, Tasmania",
                    "report_status": "Reviewed draft",
                    "report_id": "immutable-context",
                    "report_version": 1,
                },
            },
        )


def test_v4_audit_rejects_missing_snapshot_bindings_even_with_rehashed_record(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    audit_path = Path(
        _save_audit(
            {
                "report_id": "required-bindings",
                "report_version": 1,
                "report_text": "# Report",
            }
        )
    )
    record = json.loads(audit_path.read_text(encoding="utf-8"))
    record.pop("inputs_hash")
    record["record_hash"] = audit.sha256_json({key: value for key, value in record.items() if key != "record_hash"})
    audit_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(audit.AuditIntegrityError, match="required v4 snapshot bindings"):
        audit.load_and_verify_audit(audit_path)


def test_export_rejects_report_text_that_differs_from_verified_audit(tmp_path, monkeypatch):
    review_record = _draft_review_record()
    register_snapshot = _frozen_register_snapshot()
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    audit_path = _save_audit(
        {
            "report_id": "export-hash-bound",
            "report_version": 1,
            "report_text": "# Original report",
            "human_review": review_record,
            "export_register_snapshot": register_snapshot,
        }
    )

    with pytest.raises(audit.AuditIntegrityError, match="report text does not match"):
        create_pilot_export_package(
            "# Modified report",
            audit_path=audit_path,
            review_record=review_record,
            register_snapshot=register_snapshot,
        )


def test_export_manifest_hashes_match_every_archived_artifact(tmp_path, monkeypatch):
    report_text = "# Hash-bound report\n\nPreparedness planning draft."
    review_record = _draft_review_record()
    report_text = append_human_signoff(report_text, review_record)
    register_snapshot = _frozen_register_snapshot()
    package_context = {
        "report_status": review_record["approval_status"],
        "report_id": "artifact-hash-report",
        "report_version": 1,
    }
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    audit_path = _save_audit(
        {
            "report_id": "artifact-hash-report",
            "report_version": 1,
            "report_text": report_text,
            "human_review": review_record,
            "package_context": package_context,
            "export_register_snapshot": register_snapshot,
        }
    )
    package = create_pilot_export_package(
        report_text,
        audit_path=audit_path,
        review_record=review_record,
        package_context=package_context,
        register_snapshot=register_snapshot,
    )

    with ZipFile(BytesIO(package["content"])) as archive:
        manifest = json.loads(archive.read("governance/package_manifest.json"))
        for path, expected_hash in manifest["artifact_hashes"].items():
            assert hashlib.sha256(archive.read(path)).hexdigest() == expected_hash


def test_export_rejects_context_that_differs_from_verified_snapshot(tmp_path, monkeypatch):
    report_text = "# Context-bound report"
    review_record = _draft_review_record()
    report_text = append_human_signoff(report_text, review_record)
    register_snapshot = _frozen_register_snapshot()
    package_context = {
        "location": "Cairns, Queensland",
        "report_status": review_record["approval_status"],
        "report_id": "context-bound-report",
        "report_version": 1,
    }
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    audit_path = _save_audit(
        {
            "report_id": "context-bound-report",
            "report_version": 1,
            "report_text": report_text,
            "inputs": {"location": "Cairns, Queensland"},
            "human_review": review_record,
            "package_context": package_context,
            "export_register_snapshot": register_snapshot,
        }
    )

    with pytest.raises(audit.AuditIntegrityError, match="export context"):
        create_pilot_export_package(
            report_text,
            audit_path=audit_path,
            review_record=review_record,
            package_context={**package_context, "location": "Hobart, Tasmania"},
            register_snapshot=register_snapshot,
        )


def test_export_rejects_unhashed_context_fields(tmp_path, monkeypatch):
    report_text = "# Allow-listed context report"
    review_record = _draft_review_record()
    package_context = {
        "report_status": review_record["approval_status"],
        "report_id": "allow-listed-context",
        "report_version": 1,
    }
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    audit_path = _save_audit(
        {
            "report_id": "allow-listed-context",
            "report_version": 1,
            "report_text": report_text,
            "human_review": review_record,
            "package_context": package_context,
        }
    )

    with pytest.raises(audit.AuditIntegrityError, match="unsupported fields"):
        create_pilot_export_package(
            report_text,
            audit_path=audit_path,
            review_record=review_record,
            package_context={**package_context, "approval_authority": "UNAUDITED CLAIM"},
        )


def test_export_preserves_exact_audited_markdown_without_adding_a_heading(
    tmp_path,
    monkeypatch,
):
    report_text = "Plain governed report without a Markdown heading."
    review_record = _draft_review_record()
    report_text = append_human_signoff(report_text, review_record)
    register_snapshot = _frozen_register_snapshot()
    package_context = {
        "report_status": review_record["approval_status"],
        "report_id": "exact-markdown",
        "report_version": 1,
    }
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    audit_path = _save_audit(
        {
            "report_id": "exact-markdown",
            "report_version": 1,
            "report_text": report_text,
            "human_review": review_record,
            "package_context": package_context,
            "export_register_snapshot": register_snapshot,
        }
    )
    package = create_pilot_export_package(
        report_text,
        audit_path=audit_path,
        review_record=review_record,
        package_context=package_context,
        register_snapshot=register_snapshot,
    )

    with ZipFile(BytesIO(package["content"])) as archive:
        markdown_name = next(
            name for name in archive.namelist() if name.startswith("reports/") and name.endswith(".md")
        )
        assert archive.read(markdown_name).decode("utf-8") == report_text


def test_revision_audit_rejects_parent_that_is_no_longer_current_head(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    parent_text = "# Parent report"
    parent_path = _save_audit(
        {
            "report_id": "advanced-parent",
            "report_version": 1,
            "report_text": parent_text,
        }
    )
    audit.append_audit_event(
        parent_path,
        "review.recorded",
        _needs_revision_event("advanced-parent", report_text=parent_text),
    )

    with pytest.raises(audit.AuditIntegrityError, match="no longer the current report head"):
        audit.save_revision_audit(
            parent_path,
            _revision_payload("stale-parent-child", "advanced-parent"),
        )

    assert not list(tmp_path.glob(".revision_*.json"))


def test_root_audit_api_rejects_caller_supplied_parent_lineage(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    forged_hash = "0" * 64
    with pytest.raises(audit.AuditIntegrityError, match="revision transaction"):
        _save_audit(
            {
                "report_id": "forged-child",
                "report_version": 2,
                "parent_report_id": "ghost-parent",
                "parent_audit_binding": {
                    "report_id": "ghost-parent",
                    "report_version": 1,
                    "audit_id": "ghost-audit",
                    "record_hash": forged_hash,
                    "report_content_sha256": forged_hash,
                    "governed_body_hash": forged_hash,
                },
                "report_text": "# Forged child",
            }
        )


def test_v4_root_audit_requires_exact_deterministic_signoff(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    with pytest.raises(audit.AuditIntegrityError, match="deterministic Human Review"):
        _RAW_SAVE_REPORT_AUDIT(
            {
                "report_id": "missing-root-signoff",
                "report_version": 1,
                "report_text": "# Report without a sign-off",
            }
        )


@pytest.mark.parametrize(
    "invalid_version",
    [None, 0, -1, True, False, "1", 1.0],
)
def test_v4_root_audit_requires_positive_integer_version(tmp_path, monkeypatch, invalid_version):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    with pytest.raises(audit.AuditIntegrityError, match="positive integer"):
        _save_audit(
            {
                "report_id": f"invalid-version-{invalid_version}",
                "report_version": invalid_version,
                "report_text": "# Report with an invalid version",
            }
        )


@pytest.mark.parametrize(
    "invalid_version",
    [None, 0, -1, True, False, "1", 1.0],
)
def test_v4_validator_rejects_invalid_report_version(tmp_path, monkeypatch, invalid_version):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    path = _save_audit(
        {
            "report_id": "validator-version",
            "report_version": 1,
            "report_text": "# Versioned report",
        }
    )
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    record["report_version"] = invalid_version
    record["record_hash"] = audit.sha256_json({key: value for key, value in record.items() if key != "record_hash"})

    with pytest.raises(audit.AuditIntegrityError, match="positive integer"):
        audit.validate_audit_record(record)


def test_revision_version_must_be_parent_version_plus_one(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    register_snapshot = _frozen_register_snapshot()
    parent_path = _save_audit(
        {
            "report_id": "version-parent",
            "report_version": 1,
            "report_text": "# Version parent",
            "export_register_snapshot": register_snapshot,
        }
    )
    payload = _revision_payload(
        "version-child",
        "version-parent",
        register_snapshot=register_snapshot,
    )
    payload["report_version"] = 99
    payload["package_context"]["report_version"] = 99
    with pytest.raises(audit.AuditIntegrityError, match="exactly one greater"):
        audit.save_revision_audit(parent_path, payload)


def test_parent_report_version_cannot_branch_after_later_review(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    register_snapshot = _frozen_register_snapshot()
    parent_text = "# Non-branching parent"
    parent_path = _save_audit(
        {
            "report_id": "non-branching-parent",
            "report_version": 1,
            "report_text": parent_text,
            "export_register_snapshot": register_snapshot,
        }
    )
    audit.save_revision_audit(
        parent_path,
        _revision_payload(
            "first-child",
            "non-branching-parent",
            register_snapshot=register_snapshot,
        ),
    )
    reviewed_parent_path = audit.append_audit_event(
        parent_path,
        "review.recorded",
        _needs_revision_event("non-branching-parent", report_text=parent_text),
    )
    with pytest.raises(audit.AuditIntegrityError, match="already produced"):
        audit.save_revision_audit(
            reviewed_parent_path,
            _revision_payload(
                "second-child",
                "non-branching-parent",
                register_snapshot=register_snapshot,
            ),
        )


def test_review_append_rejects_content_after_deterministic_signoff(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    parent_path = _save_audit({"report_id": "signoff-boundary", "report_version": 1, "report_text": "Report"})
    payload = _needs_revision_event("signoff-boundary")
    payload["report_text"] += "\nMALICIOUS OPERATIONAL CONTENT\n"
    with pytest.raises(audit.AuditIntegrityError, match="deterministic Human Review"):
        audit.append_audit_event(parent_path, "review.recorded", payload)


def test_v4_review_rejects_legacy_checklist_aggregate_without_items(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    parent_path = _save_audit({"report_id": "legacy-checklist", "report_version": 1, "report_text": "Report"})
    legacy_review = {
        "approval_status": "Needs revision",
        "review_checklist_complete": True,
    }
    with pytest.raises(audit.AuditIntegrityError, match="deterministic Human Review"):
        audit.append_audit_event(
            parent_path,
            "review.recorded",
            {
                "report_id": "legacy-checklist",
                "report_version": 1,
                "report_text": append_human_signoff("Report", legacy_review),
                "report_status": "Needs revision",
                "human_review": legacy_review,
                "package_context": {
                    "report_status": "Needs revision",
                    "report_id": "legacy-checklist",
                    "report_version": 1,
                },
            },
        )


def test_interrupted_revision_claim_recovers_committed_child(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    register_snapshot = _frozen_register_snapshot()
    parent_path = _save_audit(
        {
            "report_id": "recovery-parent",
            "report_version": 1,
            "report_text": "# Recovery parent",
            "export_register_snapshot": register_snapshot,
        }
    )
    payload = _revision_payload(
        "recovery-child",
        "recovery-parent",
        register_snapshot=register_snapshot,
    )
    original_commit = audit._commit_revision_claim
    monkeypatch.setattr(
        audit,
        "_commit_revision_claim",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("simulated crash")),
    )
    first_path = audit.save_revision_audit(parent_path, payload)
    claim_path = next(tmp_path.glob(".revision_*.json"))
    assert json.loads(claim_path.read_text(encoding="utf-8"))["state"] == "pending"
    monkeypatch.setattr(audit, "_commit_revision_claim", original_commit)

    recovered_path = audit.save_revision_audit(parent_path, payload)
    assert Path(recovered_path) == Path(first_path)
    assert audit.load_and_verify_audit(recovered_path)["report_id"] == "recovery-child"
    claims = list(tmp_path.glob(".revision_*.json"))
    assert len(claims) == 1
    assert json.loads(claims[0].read_text(encoding="utf-8"))["state"] == "committed"
    assert (
        len(
            [
                path
                for path in tmp_path.glob("audit_*.json")
                if audit.load_and_verify_audit(path).get("report_id") == "recovery-child"
            ]
        )
        == 1
    )


def test_interrupted_append_recovers_one_successor_without_forking(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    parent_path = _save_audit({"report_id": "append-recovery", "report_version": 1, "report_text": "Report"})
    payload = _needs_revision_event("append-recovery")
    original_write_head = audit._write_head
    monkeypatch.setattr(
        audit,
        "_write_head",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit("hard stop")),
    )
    with pytest.raises(SystemExit, match="hard stop"):
        audit.append_audit_event(parent_path, "review.recorded", payload)
    monkeypatch.setattr(audit, "_write_head", original_write_head)

    recovered_path = audit.append_audit_event(
        parent_path,
        "review.recorded",
        payload,
    )
    events = list(tmp_path.glob("audit_*.json"))
    assert len(events) == 2
    assert audit.capture_current_audit_chain(recovered_path)[-1]["record"]["event_type"] == "review.recorded"


def test_current_chain_capture_repairs_a_rolled_back_head_and_blocks_old_tip(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    parent_path = _save_audit({"report_id": "head-rollback", "report_version": 1, "report_text": "Report"})
    latest_path = audit.append_audit_event(
        parent_path,
        "review.recorded",
        _needs_revision_event("head-rollback"),
    )
    parent = audit.load_and_verify_audit(parent_path)
    audit._write_head(tmp_path, parent, Path(parent_path))

    with pytest.raises(audit.AuditIntegrityError, match="no longer the current report head"):
        audit.capture_current_audit_chain(parent_path)
    captured = audit.capture_current_audit_chain(latest_path)
    assert [item["path"] for item in captured] == [
        Path(parent_path).resolve(),
        Path(latest_path).resolve(),
    ]


def test_one_parent_audit_head_can_produce_only_one_revision_child(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    register_snapshot = _frozen_register_snapshot()
    parent_path = _save_audit(
        {
            "report_id": "single-child-parent",
            "report_version": 1,
            "report_text": "# Single-child parent",
            "export_register_snapshot": register_snapshot,
        }
    )
    child_payloads = [
        _revision_payload(
            "concurrent-child-a",
            "single-child-parent",
            register_snapshot=register_snapshot,
        ),
        _revision_payload(
            "concurrent-child-b",
            "single-child-parent",
            register_snapshot=register_snapshot,
        ),
    ]

    def create_child(payload):
        try:
            return "created", audit.save_revision_audit(parent_path, payload)
        except audit.AuditIntegrityError as error:
            return "rejected", str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(create_child, child_payloads))

    created = [value for status, value in outcomes if status == "created"]
    rejected = [value for status, value in outcomes if status == "rejected"]
    assert len(created) == 1
    assert len(rejected) == 1
    assert "already produced a governed revision" in rejected[0]
    assert len(list(tmp_path.glob("audit_*.json"))) == 2
    claims = list(tmp_path.glob(".revision_*.json"))
    assert len(claims) == 1
    claim = json.loads(claims[0].read_text(encoding="utf-8"))
    assert claim["state"] == "committed"
    assert Path(created[0]).name == claim["child"]["audit_file"]


def test_revision_export_requires_and_packages_exact_parent_lineage(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    register_snapshot = _frozen_register_snapshot()
    parent_path = _save_audit(
        {
            "report_id": "lineage-parent",
            "report_version": 1,
            "report_text": "# Lineage parent",
            "export_register_snapshot": register_snapshot,
        }
    )
    child_review = _draft_review_record()
    child_text = append_human_signoff("# Lineage child", child_review)
    child_context = {
        "report_status": child_review["approval_status"],
        "report_id": "lineage-child",
        "report_version": 2,
    }
    child_path = audit.save_revision_audit(
        parent_path,
        _revision_payload(
            "lineage-child",
            "lineage-parent",
            child_text,
            register_snapshot=register_snapshot,
        ),
    )
    parent_record = audit.load_and_verify_audit(parent_path)
    child_record = audit.load_and_verify_audit(child_path)
    expected_binding = {
        "report_id": parent_record["report_id"],
        "report_version": parent_record["report_version"],
        "audit_id": parent_record["audit_id"],
        "record_hash": parent_record["record_hash"],
        "report_content_sha256": parent_record["report_content"]["sha256"],
        "governed_body_hash": parent_record["governed_body_hash"],
    }

    assert child_record["parent_report_id"] == parent_record["report_id"]
    assert child_record["parent_audit_binding"] == expected_binding

    with pytest.raises(audit.AuditIntegrityError, match="missing its bound parent"):
        create_pilot_export_package(
            child_text,
            audit_path=child_path,
            review_record=child_review,
            package_context=child_context,
            register_snapshot=register_snapshot,
        )

    wrong_parent_path = _save_audit(
        {
            "report_id": "unrelated-parent",
            "report_version": 1,
            "report_text": "# Unrelated parent",
        }
    )
    with pytest.raises(audit.AuditIntegrityError, match="does not match its lineage binding"):
        create_pilot_export_package(
            child_text,
            audit_path=child_path,
            review_record=child_review,
            package_context=child_context,
            parent_audit_path=wrong_parent_path,
            register_snapshot=register_snapshot,
        )

    package = create_pilot_export_package(
        child_text,
        audit_path=child_path,
        review_record=child_review,
        package_context=child_context,
        parent_audit_path=parent_path,
        register_snapshot=register_snapshot,
    )
    with ZipFile(BytesIO(package["content"])) as archive:
        manifest = json.loads(archive.read("governance/package_manifest.json"))
        lineage = manifest["parent_lineage"]
        assert lineage["binding"] == expected_binding
        assert lineage["audit_chain"]
        for item in lineage["audit_chain"]:
            payload = archive.read(item["path"])
            assert hashlib.sha256(payload).hexdigest() == item["sha256"]
            assert manifest["artifact_hashes"][item["path"]] == item["sha256"]
        exported_parent = json.loads(archive.read(lineage["audit_chain"][-1]["path"]))
        assert exported_parent["record_hash"] == expected_binding["record_hash"]


def test_verified_revision_snapshot_rejects_missing_parent_path(tmp_path, monkeypatch):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    register_snapshot = _frozen_register_snapshot()
    parent_path = _save_audit(
        {
            "report_id": "snapshot-parent",
            "report_version": 1,
            "report_text": "# Snapshot parent",
            "export_register_snapshot": register_snapshot,
        }
    )
    child_text = append_human_signoff("# Snapshot child", _draft_review_record())
    child_path = audit.save_revision_audit(
        parent_path,
        _revision_payload(
            "snapshot-child",
            "snapshot-parent",
            child_text,
            register_snapshot=register_snapshot,
        ),
    )
    review_record = audit.canonical_review_record(
        _draft_review_record(),
        default_status="Draft - human review required",
    )
    report_record = {
        "id": "snapshot-child",
        "version": 2,
        "parent_report_id": "snapshot-parent",
        "parent_audit_path": parent_path,
        "inputs": {},
        "analysis": {},
        "area_selection": None,
        "model_context": {},
        "review_record": review_record,
        "export_register_snapshot": register_snapshot,
        "text": child_text,
        "audit_path": child_path,
    }
    assert report_workflow.verify_report_record_snapshot(report_record) is True
    report_record["parent_audit_path"] = str(tmp_path / "DOES-NOT-EXIST.json")
    assert report_workflow.verify_report_record_snapshot(report_record) is False


def test_third_generation_export_contains_recursive_ancestor_lineage(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    register_snapshot = _frozen_register_snapshot()
    first_path = _save_audit(
        {
            "report_id": "generation-one",
            "report_version": 1,
            "report_text": "# Generation one",
            "export_register_snapshot": register_snapshot,
        }
    )
    second_path = audit.save_revision_audit(
        first_path,
        _revision_payload(
            "generation-two",
            "generation-one",
            "# Generation two",
            register_snapshot=register_snapshot,
        ),
    )
    third_payload = _revision_payload(
        "generation-three",
        "generation-two",
        "# Generation three",
        register_snapshot=register_snapshot,
    )
    third_payload["report_version"] = 3
    third_payload["package_context"]["report_version"] = 3
    third_path = audit.save_revision_audit(second_path, third_payload)
    review_record = _draft_review_record()
    third_text = third_payload["report_text"]
    package = create_pilot_export_package(
        third_text,
        audit_path=third_path,
        review_record=review_record,
        package_context={
            "report_status": review_record["approval_status"],
            "report_id": "generation-three",
            "report_version": 3,
        },
        parent_audit_path=second_path,
        register_snapshot=register_snapshot,
    )
    with ZipFile(BytesIO(package["content"])) as archive:
        manifest = json.loads(archive.read("governance/package_manifest.json"))
        ancestors = manifest["parent_lineage"]["ancestors"]
        assert len(ancestors) == 1
        assert ancestors[0]["depth"] == 2
        assert ancestors[0]["binding"]["report_id"] == "generation-one"
        for item in ancestors[0]["audit_chain"]:
            payload = archive.read(item["path"])
            assert hashlib.sha256(payload).hexdigest() == item["sha256"]
            assert manifest["artifact_hashes"][item["path"]] == item["sha256"]


def test_generated_report_audits_and_exports_exact_frozen_register_snapshot(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("BUSHFIRE_AUDIT_DIR", raising=False)
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    original_snapshot = _frozen_register_snapshot("REPORT-TIME-SNAPSHOT")
    build_calls = []

    def build_snapshot_once():
        build_calls.append(True)
        return dict(original_snapshot)

    state = SessionState(
        {
            "latest_report": None,
            "messages": [],
            "pilot_mode": "Council Community Preparedness",
        }
    )
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(
        report_workflow,
        "build_export_register_snapshot",
        build_snapshot_once,
    )
    persisted = []

    response, error = report_workflow._finalize_report_version(
        "# Frozen register report\n\nPreparedness planning draft.",
        {},
        lambda: persisted.append(True),
        source="generated",
        request_text="Generate the governed report.",
        report_inputs={
            "pilot_mode": "Council Community Preparedness",
            "location": "Cairns, Queensland",
            "audience": "Community residents",
            "scenario": "Community preparedness",
        },
        area_selection=None,
    )

    assert error is None
    assert response == state["latest_report"]["text"]
    assert build_calls == [True]
    assert persisted == [True]
    report_record = state["latest_report"]
    assert report_record["export_register_snapshot"] == original_snapshot
    audit_record = audit.load_and_verify_audit(report_record["audit_path"])
    assert audit_record["export_register_hashes"] == export_register_snapshot_hashes(original_snapshot)

    tampered_snapshot = dict(original_snapshot)
    tampered_path = REGISTER_SNAPSHOT_FILES[0]
    tampered_snapshot[tampered_path] += "TAMPERED AFTER GENERATION\n"
    package_context = report_workflow._package_context_for_record(report_record)
    with pytest.raises(audit.AuditIntegrityError, match="registers do not match"):
        create_pilot_export_package(
            report_record["text"],
            audit_path=report_record["audit_path"],
            review_record=report_record["review_record"],
            package_context=package_context,
            register_snapshot=tampered_snapshot,
        )

    package = create_pilot_export_package(
        report_record["text"],
        audit_path=report_record["audit_path"],
        review_record=report_record["review_record"],
        package_context=package_context,
        register_snapshot=report_record["export_register_snapshot"],
    )
    with ZipFile(BytesIO(package["content"])) as archive:
        manifest = json.loads(archive.read("governance/package_manifest.json"))
        assert manifest["frozen_register_hashes"] == audit_record["export_register_hashes"]
        for path, original_text in original_snapshot.items():
            payload = archive.read(path)
            assert payload == original_text.encode("utf-8")
            expected_hash = hashlib.sha256(payload).hexdigest()
            assert manifest["frozen_register_hashes"][path] == expected_hash
            assert manifest["artifact_hashes"][path] == expected_hash
