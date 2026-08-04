import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import httpx
from openai import APIConnectionError, APIStatusError

from src.agents import run_analysis_pipeline
from src.agents.profile_agent import ProfileAgent
from src.assistants.assistant import model_service_error_message
from src.audit import save_report_audit
from src.docx_export import create_report_docx
from src.agents.report_quality_agent import ReportQualityAgent
from src.data_status import get_community_data_status
from src.export_package import create_pilot_export_package
from src.licence_register import get_licence_register, licence_register_csv
from src.pdf_export import create_report_pdf
from src.report_workflow import (
    validate_geography_consistency,
    validate_report_inputs,
    validate_review_record,
)
from src.report_template import append_evidence_tables, append_human_signoff, apply_governance_notice
from src import session_store


SAMPLE_REPORT = """# Cairns Campus Preparedness Report

Location: Cairns, Queensland
Audience: students and teachers

## Executive Summary
Preparedness planning draft.

| Field | Value |
| --- | --- |
| Scenario | School preparedness |

## Evidence Confidence and Provenance

| Code | Evidence class | Confidence / use boundary | Required review |
| --- | --- | --- | --- |
| O1 | Official-source reference | Current information not confirmed | Check the official source |
| P2 | Processed official-origin data | Transformation limitations apply | Check source year and method |
| R3 | Deterministic rule inference | Indicative planning logic | Validate locally |
| A4 | AI-generated draft synthesis | Not an evidence source | Human verification required |
| U0 | User-provided context | Unverified | Confirm organisational records |

- [ ] Confirm official sources.
"""


def test_analysis_pipeline_returns_expected_sections():
    analysis = run_analysis_pipeline(
        location="Cairns, Queensland",
        audience="students and teachers",
        scenario="School Preparedness",
        concerns=["evacuation", "assembly points", "first aid"],
        timeframe="One-week action plan",
        extra_context="Campus emergency planning pilot.",
    )

    expected_keys = {
        "profile",
        "data",
        "community",
        "risk_context",
        "plan",
        "prompt_context",
        "evidence_confidence",
    }
    assert expected_keys.issubset(analysis)
    assert analysis["profile"]["location"] == "Cairns, Queensland"
    assert analysis["prompt_context"]
    assert {row["code"] for row in analysis["evidence_confidence"]} == {
        "O1",
        "P2",
        "R3",
        "A4",
        "U0",
    }


def test_report_appendices_are_idempotent():
    analysis = run_analysis_pipeline(
        location="Cairns, Queensland",
        audience="students and teachers",
        scenario="School Preparedness",
        concerns=["official sources"],
        timeframe="One-week action plan",
        extra_context="",
    )

    report = apply_governance_notice("# Test Report")
    report = append_evidence_tables(report, analysis)
    report = append_evidence_tables(report, analysis)
    report = append_human_signoff(report, {"reviewer_name": "Test Reviewer"})

    assert report.count("DRAFT STATUS NOTICE") == 1
    assert report.count("## Evidence Tables") == 1
    assert report.count("### Evidence Confidence and Provenance") == 1
    assert "[O1]" in report
    assert "[P2]" in report
    assert "[R3]" in report
    assert "[A4]" in report
    assert "[U0]" in report
    assert "## Human Review Sign-off" in report
    assert "Test Reviewer" in report


def test_deterministic_evidence_tables_replace_model_modified_tables():
    analysis = run_analysis_pipeline(
        location="Cairns, Queensland",
        audience="students and teachers",
        scenario="School Preparedness",
        concerns=["official sources"],
        timeframe="One-week action plan",
        extra_context="",
    )
    model_modified = """# Draft

## Evidence Tables

MODEL MODIFIED EVIDENCE THAT MUST NOT SURVIVE

## Human Review Sign-off

Old sign-off.
"""

    report = append_evidence_tables(model_modified, analysis)
    report = append_human_signoff(report, {"reviewer_name": "Test Reviewer"})

    assert "MODEL MODIFIED EVIDENCE" not in report
    assert report.count("## Evidence Tables") == 1
    assert report.index("## Evidence Tables") < report.index("## Human Review Sign-off")


def test_governance_notice_replaces_modified_notice_without_losing_report_body():
    modified = """**DRAFT STATUS NOTICE**

Modified model wording that must not survive.

# Preparedness Report

## Executive Summary
Keep this report body.
"""

    report = apply_governance_notice(modified)

    assert report.count("DRAFT STATUS NOTICE") == 1
    assert "Modified model wording" not in report
    assert "# Preparedness Report" in report
    assert "Keep this report body" in report


def test_session_state_persistence_uses_json_and_round_trips(monkeypatch):
    with TemporaryDirectory() as directory:
        target = Path(directory) / "session.json"
        state = {
            "messages": [{"role": "assistant", "content": "Draft", "kind": "report"}],
            "latest_report": {"id": "report-1", "version": 2, "text": "Draft"},
        }
        monkeypatch.setattr(session_store, "SESSION_STATE_PATH", str(target))
        monkeypatch.setattr(session_store, "st", SimpleNamespace(session_state=state))

        session_store.persist_session_state()
        saved = json.loads(target.read_text(encoding="utf-8"))

        assert saved["latest_report"]["version"] == 2
        assert session_store._load_persisted_state() == saved


def test_data_and_licence_registers_load():
    status = get_community_data_status()
    licences = get_licence_register()
    licence_csv = licence_register_csv()

    assert status["active_exists"] is True
    assert status["row_count"] >= 1
    assert licences["licence_register"]
    assert "source_name" in licence_csv


def test_pilot_export_package_contains_governance_files():
    package = create_pilot_export_package(
        "# Test Report\n\nPreparedness draft.",
        review_record={"reviewer_name": "Test Reviewer"},
        package_context={"location": "Cairns"},
    )

    assert package["filename"].endswith("_pilot_export_package.zip")
    with ZipFile(BytesIO(package["content"])) as archive:
        names = set(archive.namelist())

    assert "governance/package_manifest.json" in names
    assert "governance/reviewer_signoff.json" in names
    assert "governance/data_register.csv" in names
    assert any(name.startswith("reports/cairns_") and name.endswith(".md") for name in names)


def test_report_exporters_create_valid_pdf_and_docx_files():
    pdf_content = create_report_pdf(SAMPLE_REPORT)
    docx_content = create_report_docx(SAMPLE_REPORT)

    assert pdf_content.startswith(b"%PDF")
    assert len(pdf_content) > 1000
    assert docx_content.startswith(b"PK")

    with ZipFile(BytesIO(docx_content)) as document:
        names = set(document.namelist())

    assert "word/document.xml" in names
    assert "docProps/core.xml" in names


def test_pilot_export_package_includes_report_formats_and_manifest_boundary():
    package = create_pilot_export_package(
        SAMPLE_REPORT,
        review_record={"reviewer_name": "Test Reviewer"},
        package_context={"location": "Cairns, Queensland"},
    )

    assert package["manifest"]["package_schema"] == "pilot-export-v1"
    assert "Not live emergency advice" in package["manifest"]["safety_boundary"]

    with ZipFile(BytesIO(package["content"])) as archive:
        names = set(archive.namelist())

    assert any(name.endswith(".pdf") for name in names)
    assert any(name.endswith(".docx") for name in names)
    assert "governance/package_manifest.json" in names


def test_pilot_export_package_writes_one_complete_manifest_with_audit():
    audit_path = Path(__file__).parent / "fixtures" / "sample_audit.json"

    package = create_pilot_export_package(
        SAMPLE_REPORT,
        audit_path=audit_path,
        review_record={"reviewer_name": "Test Reviewer"},
        package_context={"location": "Cairns, Queensland"},
    )

    with ZipFile(BytesIO(package["content"])) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("governance/package_manifest.json"))

    assert names.count("governance/package_manifest.json") == 1
    assert names.count("governance/audit_record.json") == 1
    assert manifest["included_files"].count("governance/audit_record.json") == 1
    assert manifest == package["manifest"]


def test_ollama_connection_error_has_safe_recovery_guidance():
    error = APIConnectionError(request=httpx.Request("POST", "http://localhost:11434/v1/chat/completions"))

    message = model_service_error_message(error, provider="ollama", model_name="qwen2.5:7b")

    assert "Cannot reach the local Ollama service" in message
    assert "ollama serve" in message
    assert "Traceback" not in message


def test_ollama_missing_model_error_has_pull_command():
    request = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")
    response = httpx.Response(404, request=request)
    error = APIStatusError("model not found", response=response, body={"error": "model not found"})

    message = model_service_error_message(error, provider="ollama", model_name="qwen2.5:7b")

    assert "configured model `qwen2.5:7b` is unavailable" in message
    assert "ollama pull qwen2.5:7b" in message
    assert "model not found" not in message


def test_report_validation_requires_human_review_details_for_approved_outputs():
    base_inputs = {
        "location": "Cairns, Queensland",
        "audience": "students and teachers",
        "concerns": ["Evacuation"],
        "report_status": "Draft - human review required",
        "organisation_name": "",
        "reviewer_name": "",
        "reviewer_role": "",
    }

    assert validate_report_inputs(base_inputs) is None

    approved_inputs = dict(base_inputs)
    approved_inputs["report_status"] = "Approved by organisation"
    assert "reviewer name" in validate_report_inputs(approved_inputs)

    approved_inputs.update(
        {
            "organisation_name": "Cairns Council",
            "reviewer_name": "Test Reviewer",
            "reviewer_role": "Preparedness officer",
        }
    )
    assert validate_report_inputs(approved_inputs) is None


def test_report_validation_rejects_missing_required_form_fields():
    base_inputs = {
        "location": "",
        "audience": "students and teachers",
        "concerns": ["Evacuation"],
        "report_status": "Draft - human review required",
    }

    assert "location and audience" in validate_report_inputs(base_inputs)

    base_inputs["location"] = "Cairns, Queensland"
    base_inputs["audience"] = ""
    assert "location and audience" in validate_report_inputs(base_inputs)

    base_inputs["audience"] = "students and teachers"
    base_inputs["concerns"] = []
    assert "at least one focus area" in validate_report_inputs(base_inputs)


def test_quality_agent_accepts_markdown_checkboxes_and_human_review_boundary():
    report = """
    # Cairns Preparedness Report

    ## Executive Summary
    ## Purpose and Scope
    ## Selected Geography
    ## Data Sources
    ## Local Risk Context
    ## Evacuation
    ## Candidate Assembly Point Criteria
    ## Roles and Responsibilities
    ## Communication
    ## First Aid
    ## Action Plan
    Day 1 actions are listed below.
    ## Human Review and Approval Checklist
    - [ ] Confirm official source checks.
    ## Evidence Tables
    Selected geography, community indicators, ASGS and official source register are included.
    ### Evidence Confidence and Provenance
    O1 official reference, P2 processed data, R3 rule inference, A4 AI draft and U0 unverified input.
    ## Safety Disclaimer
    This is not live emergency advice. Official evacuation order information must come from
    Queensland Fire Department, QFES, Queensland Disaster, Cairns Regional Council,
    Bureau of Meteorology / BoM and 000.
    ## Human Review Sign-off
    This report remains a draft until approved by a responsible organisation.
    """

    quality = ReportQualityAgent().run(report)
    checks = {item["name"]: item["status"] for item in quality["checks"]}

    assert checks["Checklist"] == "pass"
    assert checks["Evidence confidence"] == "pass"
    assert checks["Human review status"] == "pass"


def test_governance_notice_satisfies_safety_quality_check():
    report = apply_governance_notice(
        """
        ## Executive Summary
        ## Purpose and Scope
        ## Selected Geography
        ## Data Sources
        ## Local Risk Context
        ## Evacuation
        ## Candidate Assembly Point Criteria
        ## Roles and Responsibilities
        Teacher, student, first aid and communication roles are included.
        ## Communication
        ## First Aid
        ## Action Plan
        Day 1 actions are included.
        ## Human Review and Approval Checklist
        - [ ] Confirm official sources.
        ## Evidence Tables
        Selected geography, community indicators, ASGS and official source register are included.
        ## Human Review Sign-off
        This remains a draft.
        State fire service, local council, Bureau of Meteorology BoM, official emergency services and 000.
        """
    )

    quality = ReportQualityAgent().run(report)
    checks = {item["name"]: item["status"] for item in quality["checks"]}

    assert checks["Safety disclaimer"] == "pass"


def test_official_sources_are_state_specific_for_non_queensland_locations():
    cases = [
        ("Sydney, NSW", "New South Wales", "NSW Rural Fire Service"),
        ("Melbourne, Victoria", "Victoria", "VicEmergency"),
        ("Perth Hills, WA", "Western Australia", "Emergency WA"),
    ]

    for location, expected_state, expected_source_name in cases:
        analysis = run_analysis_pipeline(
            location=location,
            audience="community residents",
            scenario="Community workshop material",
            concerns=["Official information sources", "Evacuation"],
            timeframe="7-day action plan",
            extra_context="Cross-state official source selection test.",
        )

        source_names = [source.get("name", "") for source in analysis["data"].get("sources", [])]
        source_text = " | ".join(source_names)

        assert analysis["profile"]["state"] == expected_state
        assert expected_source_name in source_text
        assert "Triple Zero" in source_text
        assert "Queensland Fire" not in source_text
        assert "Cairns Regional Council" not in source_text


def test_cairns_still_receives_queensland_and_local_sources():
    analysis = run_analysis_pipeline(
        location="Cairns, Queensland",
        audience="council officers",
        scenario="Council community preparedness",
        concerns=["Official information sources", "Evacuation"],
        timeframe="7-day action plan",
        extra_context="Queensland source selection test.",
    )

    source_names = [source.get("name", "") for source in analysis["data"].get("sources", [])]
    source_text = " | ".join(source_names)

    assert analysis["profile"]["state"] == "Queensland"
    assert "Queensland Fire" in source_text
    assert "Cairns Regional Council" in source_text
    assert "Triple Zero" in source_text


def test_state_abbreviations_require_word_boundaries():
    profile = ProfileAgent().run(
        "Wagga Wagga",
        "community residents",
        "Community preparedness",
        ["Evacuation"],
        "7-day action plan",
        "",
    )

    assert profile["state"] == "New South Wales"


def test_exact_cairns_location_keeps_local_official_source():
    analysis = run_analysis_pipeline(
        location="Cairns",
        audience="school staff",
        scenario="School bushfire preparedness",
        concerns=["Official information sources"],
        timeframe="7-day action plan",
        extra_context="",
    )

    source_names = [source.get("name", "") for source in analysis["data"].get("sources", [])]
    assert any("Cairns Regional Council" in name for name in source_names)


def test_geography_validation_rejects_cross_state_map_selection():
    inputs = {
        "location": "Hobart, Tasmania",
        "audience": "community residents",
        "scenario": "Community preparedness",
        "concerns": ["Evacuation"],
        "timeframe": "7-day action plan",
        "extra_context": "",
    }

    error = validate_geography_consistency(
        inputs,
        {"state": "Queensland", "level": "SA4", "area_name": "Cairns"},
    )

    assert "Tasmania" in error
    assert "Queensland" in error
    assert validate_geography_consistency(
        inputs,
        {"state": "Tasmania", "level": "SA4", "area_name": "Hobart"},
    ) is None


def test_approved_review_requires_identity_fields_and_completed_checklist():
    record = {
        "approval_status": "Approved by organisation",
        "organisation_name": "Cairns Council",
        "reviewer_name": "Test Reviewer",
        "reviewer_role": "Preparedness officer",
        "review_checklist_complete": False,
    }

    assert "Complete every Human Review Checklist" in validate_review_record(record)
    record["review_checklist_complete"] = True
    assert validate_review_record(record) is None


def test_audit_paths_are_unique_for_rapid_successive_reports(monkeypatch):
    with TemporaryDirectory() as directory:
        monkeypatch.setattr("src.audit.AUDIT_DIR", Path(directory))
        payload = {"inputs": {"location": "Cairns"}, "report_text": "Draft"}

        first = save_report_audit(payload)
        second = save_report_audit(payload)

        assert first != second
        assert len(list(Path(directory).glob("audit_*.json"))) == 2
