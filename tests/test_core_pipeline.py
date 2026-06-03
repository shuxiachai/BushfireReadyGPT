from zipfile import ZipFile
from io import BytesIO

from src.agents import run_analysis_pipeline
from src.agents.report_quality_agent import ReportQualityAgent
from src.data_status import get_community_data_status
from src.export_package import create_pilot_export_package
from src.licence_register import get_licence_register, licence_register_csv
from src.report_workflow import validate_report_inputs
from src.report_template import append_evidence_tables, append_human_signoff, apply_governance_notice


def test_analysis_pipeline_returns_expected_sections():
    analysis = run_analysis_pipeline(
        location="Cairns, Queensland",
        audience="students and teachers",
        scenario="School Preparedness",
        concerns=["evacuation", "assembly points", "first aid"],
        timeframe="One-week action plan",
        extra_context="Campus emergency planning pilot.",
    )

    expected_keys = {"profile", "data", "community", "risk_context", "plan", "prompt_context"}
    assert expected_keys.issubset(analysis)
    assert analysis["profile"]["location"] == "Cairns, Queensland"
    assert analysis["prompt_context"]


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
    assert "## Human Review Sign-off" in report
    assert "Test Reviewer" in report


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
    assert checks["Human review status"] == "pass"
