import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from src.agents.pipeline import run_analysis_pipeline
from src.audit import get_audit_chain_paths, load_and_verify_audit
from src.focus_coverage import canonical_coverage_declarations
from src.report_basis import build_community_p2_basis
from src.report_generation_quality import assess_generated_narrative
from src.report_owned_fields import assemble_owned_fields, project_owned_fields_for_prompt
from src.source_attribution import (
    canonicalise_model_source_section,
    expand_known_attribution_tokens,
    fold_known_attribution_labels,
    strip_application_source_bindings,
)
from tests.support.report_fixtures import _valid_report

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "src" / "wildfireChat.py"
POSITIVE_SCENARIO = "School bushfire preparedness"
POSITIVE_TIMEFRAME = "7-day action plan"
POSITIVE_CONCERNS = ["Evacuation", "Candidate assembly points", "Official information sources"]

MOCK_REPORT = """# Hobart School Bushfire Preparedness Draft

## Executive Summary
This draft supports school preparedness planning and requires human review.

## 4. Selected Geography and Key Assumptions
[APP_P2_FIELDS]

## Evacuation and Candidate Assembly Points
Confirm routes and candidate assembly points with the responsible organisation and emergency services.

## 10. Roles and Responsibilities
[APP_ROLE_FIELDS]

## Communication and Training
Assign evacuation wardens, maintain contact lists and schedule first aid training.

## 13. Action Plan
[APP_ACTION_FIELDS]

## 14. Human Review and Approval Checklist
[APP_REVIEW_FIELDS]

## Safety Boundary
This is not live emergency advice. Follow official emergency services and call 000 if life is at risk.
"""


def _quality_passing_report(audience):
    """Use real offline form analysis; never stub the gate or erase P2 facts."""
    analysis = run_analysis_pipeline(
        "Hobart, Tasmania", audience, POSITIVE_SCENARIO, POSITIVE_CONCERNS, POSITIVE_TIMEFRAME, ""
    )
    assert analysis["knowledge"]["status"] == "disabled"
    basis = build_community_p2_basis(analysis)
    # This exact location currently has no matched community profile. If that
    # changes, the fixture must narrate those real facts instead of hiding them.
    assert basis["matched_location"] is None
    assert all(value is None for value in basis["indicators"].values())
    assembled_fixture, synthetic_analysis = _valid_report()
    narrative = assemble_owned_fields(project_owned_fields_for_prompt(assembled_fixture, synthetic_analysis), analysis)
    narrative = strip_application_source_bindings(
        narrative, official_sources=synthetic_analysis["data"]["sources"], rag_sources=[]
    )
    narrative = narrative.replace(
        "## 3. Purpose and Scope", "## 3. Purpose and Scope\n" + "\n".join(canonical_coverage_declarations(analysis))
    )
    narrative = narrative.replace(
        "## 4. Selected Geography and Key Assumptions",
        "## 4. Selected Geography and Key Assumptions\n"
        "Population and older-people measurements are unknown; transport and language measurements remain unknown.",
    )
    sources = analysis["data"]["sources"]
    narrative = canonicalise_model_source_section(narrative, official_sources=sources, rag_sources=[])
    narrative = expand_known_attribution_tokens(narrative, official_sources=sources, rag_sources=[])
    raw_narrative = project_owned_fields_for_prompt(narrative, analysis)
    raw_narrative = fold_known_attribution_labels(raw_narrative, official_sources=sources, rag_sources=[])
    quality = assess_generated_narrative(narrative, analysis)
    assert quality["approval_gate"]["passed"] is True, quality["approval_gate"]["blocking_failures"]
    return raw_narrative


def _write_verified_map_fixture(directory):
    profile_path = directory / "sa2_profiles_all.csv"
    profile_path.write_text(
        "sa2_code,state_name,sa4_name,sa3_name,sa2_name,population,older_people_count,"
        "language_other_than_english_count,language_support_needed\n"
        "306041173,Queensland,Cairns,Cairns - North,Cairns City,171000,25650,34200,high\n"
        "305031136,Queensland,Brisbane - East,Brisbane East,Bayside,205000,28700,41000,high\n",
        encoding="utf-8",
    )
    boundary_path = directory / "sa2_boundaries_all.geojson"
    features = [
        {
            "type": "Feature",
            "properties": {
                "sa2_code_2021": "306041173",
                "state_name_2021": "Queensland",
                "sa4_name_2021": "Cairns",
                "sa3_name_2021": "Cairns - North",
                "sa2_name_2021": "Cairns City",
                "population": "171000",
                "language_support_needed": "high",
                "fill_color": [31, 157, 138, 150],
                "line_color": [12, 74, 110, 220],
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [145.7, -17.0],
                        [145.9, -17.0],
                        [145.9, -16.8],
                        [145.7, -16.8],
                        [145.7, -17.0],
                    ]
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {
                "sa2_code_2021": "305031136",
                "state_name_2021": "Queensland",
                "sa4_name_2021": "Brisbane - East",
                "sa3_name_2021": "Brisbane East",
                "sa2_name_2021": "Bayside",
                "population": "205000",
                "language_support_needed": "high",
                "fill_color": [255, 127, 14, 150],
                "line_color": [12, 74, 110, 220],
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [153.0, -27.6],
                        [153.2, -27.6],
                        [153.2, -27.4],
                        [153.0, -27.4],
                        [153.0, -27.6],
                    ]
                ],
            },
        },
    ]
    boundary_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )
    (directory / "sa2_map_bundle.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_rows": 2,
                "boundary_features": 2,
                "shared_sa2_codes": 2,
                "artifacts": {
                    "profile": {
                        "size_bytes": profile_path.stat().st_size,
                        "sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                    },
                    "boundary": {
                        "size_bytes": boundary_path.stat().st_size,
                        "sha256": hashlib.sha256(boundary_path.read_bytes()).hexdigest(),
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return profile_path, boundary_path


@pytest.fixture
def isolated_app_storage(tmp_path):
    session_path = tmp_path / "session_state.json"
    interaction_path = tmp_path / "interaction.jsonl"
    audit_dir = tmp_path / "audit"
    with (
        patch("src.session_store.SESSION_STATE_PATH", str(session_path)),
        patch("src.session_store.INTERACTION_LOG_PATH", str(interaction_path)),
        patch("src.audit.AUDIT_DIR", audit_dir),
        patch("src.coverage_map.is_area_selection_available", return_value=False),
    ):
        yield {
            "session_path": session_path,
            "interaction_path": interaction_path,
            "audit_dir": audit_dir,
        }


def _run_app():
    app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
    assert not app.exception, [str(exception) for exception in app.exception]
    return app


def _button(app, label):
    matches = [button for button in app.button if button.label == label]
    assert len(matches) == 1, f"Expected one button labelled {label!r}, found {len(matches)}"
    return matches[0]


def test_report_form_rejects_empty_required_fields(isolated_app_storage):
    app = _run_app()

    assert app.session_state["selected_map_area"] is None

    _button(app, "Generate report").click().run(timeout=30)

    assert not app.exception
    assert any("Please enter a location and audience" in warning.value for warning in app.warning)
    assert app.session_state["latest_analysis"] is None


def test_verified_optional_map_supports_preview_apply_clear_and_search(
    isolated_app_storage,
    tmp_path,
    monkeypatch,
):
    profile_path, boundary_path = _write_verified_map_fixture(tmp_path)
    monkeypatch.setenv("BUSHFIRE_ALL_SA2_PROFILE_PATH", str(profile_path))
    monkeypatch.setenv("BUSHFIRE_ALL_SA2_BOUNDARY_PATH", str(boundary_path))
    monkeypatch.setenv(
        "BUSHFIRE_ALL_SA2_BOUNDARY_BY_STATE_DIR",
        str(tmp_path / "boundaries_by_state"),
    )

    app = _run_app()

    assert app.selectbox(key="map_state").value == "Queensland"
    assert app.selectbox(key="map_level").value == "SA4"
    app.text_input(key="map_search").set_value("Cairns").run(timeout=30)
    assert not app.exception
    assert app.selectbox(key="map_area").value == "Cairns"
    assert any("Map preview: Queensland / SA4 / Cairns" in item.value for item in app.caption)

    _button(app, "Use previewed area for report").click().run(timeout=30)
    assert not app.exception
    assert app.session_state["selected_map_area"] == {
        "state": "Queensland",
        "level": "SA4",
        "area_name": "Cairns",
    }
    assert any("Active report geography: Queensland / SA4 / Cairns" in item.value for item in app.caption)

    _button(app, "Clear active report geography").click().run(timeout=30)
    assert not app.exception
    assert app.session_state["selected_map_area"] is None

    app.text_input(key="map_search").set_value("No such area").run(timeout=30)
    assert not app.exception
    assert any("No matching area was found" in item.value for item in app.info)


def test_load_example_populates_report_form(isolated_app_storage):
    app = _run_app()
    app.selectbox(key="selected_example_case").set_value("Cairns school pilot").run(timeout=30)

    _button(app, "Load example").click().run(timeout=30)

    assert not app.exception
    assert app.text_input(key="form_location").value == "Cairns, Queensland"
    assert app.text_input(key="form_audience").value == "Students, teachers, school administrators and parents"
    assert app.selectbox(key="form_scenario").value == "School bushfire preparedness"
    assert "Candidate assembly points" in app.multiselect(key="form_concerns").value
    assert app.session_state["selected_map_area"] is None


def test_generate_button_creates_report_preview_with_mocked_model(isolated_app_storage):
    with patch(
        "src.model_runtime.GovernedModelClient.generate",
        autospec=True,
        return_value=MOCK_REPORT,
    ) as model_call:
        app = _run_app()
        app.text_input(key="form_location").set_value("Hobart, Tasmania")
        app.text_input(key="form_audience").set_value("Students, teachers and school administrators")
        app.multiselect(key="form_concerns").set_value(
            ["Evacuation", "Candidate assembly points", "Official information sources"]
        )

        _button(app, "Generate report").click().run(timeout=30)

    assert not app.exception
    assert model_call.call_count == 3
    assert app.session_state["latest_analysis"]["profile"]["location"] == "Hobart, Tasmania"
    quality = app.session_state["latest_quality"]
    assert quality["summary"]["total"] == 24
    checks = {item["name"]: item for item in quality["checks"]}
    assert {
        "Narrative word budget",
        "Processed community provenance",
        "Local proposal attribution",
        "Rule-derived causal qualification",
        "Submitted passage scope and conflicts",
        "Application-owned report fields",
    } <= checks.keys()
    assert checks["Narrative word budget"]["status"] == "fail"
    assert checks["Application-owned report fields"]["status"] == "pass"
    assert quality["approval_gate"]["passed"] is False
    assert app.session_state["latest_report"]["generation_gate_blocked"] is True
    assert app.session_state["report_status"] == "Draft - human review required"
    assert load_and_verify_audit(app.session_state["latest_audit_path"])["generation_gate_blocked"] is True
    assert not any(item.proto.label == "Download pilot export package" for item in app.get("download_button"))
    assert app.session_state["latest_audit_path"].startswith(str(isolated_app_storage["audit_dir"]))
    assert app.session_state["latest_report"]["version"] == 1
    assert app.session_state["latest_report"]["audit_path"] == app.session_state["latest_audit_path"]
    assert any("Latest Report Preview" in markdown.value for markdown in app.markdown)
    assert any("Hobart School Bushfire Preparedness Draft" in markdown.value for markdown in app.markdown)


def test_revision_creates_a_new_governed_report_version(isolated_app_storage):
    passing_report = _quality_passing_report("Students and teachers")
    revised_report = passing_report.replace(
        "assisted transport and participant accountability",
        "accessible transport requests and participant accountability",
    )
    assert revised_report != passing_report
    with patch(
        "src.model_runtime.GovernedModelClient.generate",
        autospec=True,
        side_effect=[passing_report, revised_report],
    ) as model_call:
        app = _run_app()
        app.text_input(key="form_location").set_value("Hobart, Tasmania")
        app.text_input(key="form_audience").set_value("Students and teachers")
        app.selectbox(key="form_scenario").set_value(POSITIVE_SCENARIO)
        app.selectbox(key="form_timeframe").set_value(POSITIVE_TIMEFRAME)
        app.multiselect(key="form_concerns").set_value(
            ["Evacuation", "Candidate assembly points", "Official information sources"]
        )
        _button(app, "Generate report").click().run(timeout=30)
        first_report = dict(app.session_state["latest_report"])
        review_checkbox_keys = [
            checkbox.key for checkbox in app.checkbox if str(checkbox.key).startswith("review_check_")
        ]
        for key in review_checkbox_keys:
            next(checkbox for checkbox in app.checkbox if checkbox.key == key).check().run(timeout=30)
        assert all(checkbox.value for checkbox in app.checkbox if str(checkbox.key).startswith("review_check_"))

        app.chat_input[0].set_value("Add accessibility detail to the evacuation section.").run(timeout=30)

    second_report = app.session_state["latest_report"]
    assert not app.exception
    assert model_call.call_count == 2
    assert second_report["version"] == 2
    assert second_report["parent_report_id"] == first_report["id"]
    assert second_report["id"] != first_report["id"]
    assert second_report["audit_path"] != first_report["audit_path"]
    assert "accessible transport requests and participant accountability" in second_report["text"]
    assert second_report["quality"]["approval_gate"]["passed"] is True
    assert "## Evidence Tables" in second_report["text"]
    assert "## Human Review Sign-off" in second_report["text"]
    assert second_report["quality"] == app.session_state["latest_quality"]
    assert app.session_state["report_status"] == "Draft - human review required"
    checkbox_state = [
        (checkbox.key, checkbox.value) for checkbox in app.checkbox if str(checkbox.key).startswith("review_check_")
    ]
    assert not any(value for _, value in checkbox_state), checkbox_state
    second_audit = json.loads(Path(second_report["audit_path"]).read_text(encoding="utf-8"))
    assert second_audit["human_review"]["review_checklist_complete"] is False


def test_failed_revision_retains_report_and_shows_actionable_error(isolated_app_storage):
    passing_report = _quality_passing_report("Students and teachers")
    with patch(
        "src.model_runtime.GovernedModelClient.generate",
        autospec=True,
        side_effect=[passing_report, MOCK_REPORT],
    ) as model_call:
        app = _run_app()
        app.text_input(key="form_location").set_value("Hobart, Tasmania")
        app.text_input(key="form_audience").set_value("Students and teachers")
        app.selectbox(key="form_scenario").set_value(POSITIVE_SCENARIO)
        app.selectbox(key="form_timeframe").set_value(POSITIVE_TIMEFRAME)
        app.multiselect(key="form_concerns").set_value(
            ["Evacuation", "Candidate assembly points", "Official information sources"]
        )
        _button(app, "Generate report").click().run(timeout=30)
        previous = dict(app.session_state["latest_report"])
        audit_bytes = Path(previous["audit_path"]).read_bytes()
        app.chat_input[0].set_value("Add accessibility detail to the evacuation section.").run(timeout=30)

    assert not app.exception
    assert model_call.call_count == 2
    assert app.session_state["latest_report"] == previous
    assert Path(previous["audit_path"]).read_bytes() == audit_bytes
    assert any("original report is unchanged" in item.value for item in app.warning)


def test_approval_creates_append_only_audit_event_and_updates_signoff(isolated_app_storage):
    passing_report = _quality_passing_report("Council preparedness reviewers")
    with patch(
        "src.model_runtime.GovernedModelClient.generate",
        autospec=True,
        return_value=passing_report,
    ):
        app = _run_app()
        app.text_input(key="form_location").set_value("Hobart, Tasmania")
        app.text_input(key="form_audience").set_value("Council preparedness reviewers")
        app.selectbox(key="form_scenario").set_value(POSITIVE_SCENARIO)
        app.selectbox(key="form_timeframe").set_value(POSITIVE_TIMEFRAME)
        app.multiselect(key="form_concerns").set_value(
            ["Evacuation", "Candidate assembly points", "Official information sources"]
        )
        _button(app, "Generate report").click().run(timeout=30)
        creation_path = Path(app.session_state["latest_audit_path"])
        creation_bytes = creation_path.read_bytes()
        original_report = app.session_state["latest_report"]["text"]
        report_download_labels = ("Download latest report", "Download Markdown", "Download PDF", "Download DOCX")
        original_download_urls = {
            label: next(item.proto.url for item in app.get("download_button") if item.proto.label == label)
            for label in report_download_labels
        }
        assert app.session_state["latest_quality"]["approval_gate"]["passed"] is True

        for checkbox in [item for item in app.checkbox if str(item.key).startswith("review_check_")]:
            checkbox.check().run(timeout=30)
        app.text_input(key="approval_reviewer_name").set_value("Authorised Reviewer").run(timeout=30)
        app.text_input(key="approval_reviewer_role").set_value("Preparedness lead").run(timeout=30)
        app.text_input(key="approval_organisation_name").set_value("Test Council").run(timeout=30)
        app.selectbox(key="approval_status").set_value("Approved by organisation").run(timeout=30)
        _button(app, "Update sign-off record").click().run(timeout=30)

    latest_path = Path(app.session_state["latest_audit_path"])
    assert not app.exception
    assert latest_path != creation_path
    assert creation_path.read_bytes() == creation_bytes
    assert get_audit_chain_paths(latest_path) == [creation_path.resolve(), latest_path.resolve()]
    assert load_and_verify_audit(latest_path)["event_type"] == "review.recorded"
    assert app.session_state["report_status"] == "Approved by organisation"
    assert app.session_state["latest_report"]["text"].count("- [x]") == 5
    assert any("append-only audit event" in success.value for success in app.success)
    assert original_report.strip() not in [item.value.strip() for item in app.markdown]
    current_download_urls = {
        label: next(item.proto.url for item in app.get("download_button") if item.proto.label == label)
        for label in report_download_labels
    }
    for label in report_download_labels:
        assert current_download_urls[label] != original_download_urls[label], label


def test_blocked_approval_does_not_mutate_authoritative_review_state(isolated_app_storage):
    with patch(
        "src.model_runtime.GovernedModelClient.generate",
        autospec=True,
        return_value=MOCK_REPORT,
    ):
        app = _run_app()
        app.text_input(key="form_location").set_value("Hobart, Tasmania")
        app.text_input(key="form_audience").set_value("Council preparedness reviewers")
        app.multiselect(key="form_concerns").set_value(["Evacuation"])
        _button(app, "Generate report").click().run(timeout=30)
        original_report = dict(app.session_state["latest_report"])

        for checkbox in [item for item in app.checkbox if str(item.key).startswith("review_check_")]:
            checkbox.check().run(timeout=30)
        app.text_input(key="approval_reviewer_name").set_value("Uncommitted Reviewer").run(timeout=30)
        app.text_input(key="approval_reviewer_role").set_value("Preparedness lead").run(timeout=30)
        app.text_input(key="approval_organisation_name").set_value("Test Council").run(timeout=30)
        app.selectbox(key="approval_status").set_value("Approved by organisation").run(timeout=30)
        _button(app, "Update sign-off record").click().run(timeout=30)

    assert not app.exception
    assert app.session_state["report_status"] == "Draft - human review required"
    assert app.session_state["reviewer_name"] == ""
    assert app.session_state["latest_report"]["audit_path"] == original_report["audit_path"]
    assert app.session_state["latest_report"]["review_record"] == original_report["review_record"]
    assert any("failed Governed Report Check" in warning.value for warning in app.warning)


def test_external_model_disclosure_is_visible_and_unconfirmed_request_is_blocked(isolated_app_storage):
    remote_endpoint = "https://remote-ollama.example/v1"
    with (
        patch("src.report_workflow.MODEL_ENDPOINT_IS_LOCAL", False),
        patch("src.report_workflow.EXTERNAL_MODEL_ALLOWED", True),
        patch("src.ui.report_views.MODEL_ENDPOINT_IS_LOCAL", False),
        patch("src.ui.report_views.EXTERNAL_MODEL_ALLOWED", True),
        patch("src.ui.report_views.MODEL_ENDPOINT_DISPLAY", remote_endpoint),
        patch("src.ui.report_views.LLM_PROVIDER", "ollama"),
        patch(
            "src.model_runtime.GovernedModelClient.generate",
            autospec=True,
            return_value=MOCK_REPORT,
        ) as model_call,
    ):
        app = _run_app()
        app.text_input(key="form_location").set_value("Hobart, Tasmania")
        app.text_input(key="form_audience").set_value("Community residents")
        app.multiselect(key="form_concerns").set_value(["Evacuation"])

        _button(app, "Generate report").click().run(timeout=30)

    assert not app.exception
    model_call.assert_not_called()
    assert any(
        "Fields sent for generation" in markdown.value
        and "Organisation and reviewer identity fields are not sent" in markdown.value
        for markdown in app.markdown
    )
    assert any("retention" in warning.value.lower() for warning in app.warning)
    assert any("browser session" in warning.value for warning in app.warning)
    assert app.session_state["latest_report"] is None
