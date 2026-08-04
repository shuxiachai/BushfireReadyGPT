import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from src.assistants.assistant import THREAD_MESSAGES


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "src" / "wildfireChat.py"
TEST_SESSION_PATH = PROJECT_ROOT / "chat_history" / "test_session_state.pkl"
TEST_INTERACTION_PATH = PROJECT_ROOT / "chat_history" / "test_interaction.jsonl"
TEST_AUDIT_DIR = PROJECT_ROOT / "chat_history" / "test_audit"

MOCK_REPORT = """# Hobart School Bushfire Preparedness Draft

## Executive Summary
This draft supports school preparedness planning and requires human review.

## Evacuation and Candidate Assembly Points
Confirm routes and candidate assembly points with the responsible organisation and emergency services.

## Roles, Communication and Training
Assign evacuation wardens, maintain contact lists and schedule first aid training.

## Action Plan
- [ ] Confirm official information sources.
- [ ] Review evacuation arrangements.
- [ ] Record the responsible reviewer.

## Safety Boundary
This is not live emergency advice. Follow official emergency services and call 000 if life is at risk.
"""


def _remove_test_files():
    for path in (TEST_SESSION_PATH, TEST_INTERACTION_PATH):
        path.unlink(missing_ok=True)
    shutil.rmtree(TEST_AUDIT_DIR, ignore_errors=True)


@pytest.fixture
def isolated_app_storage():
    _remove_test_files()
    THREAD_MESSAGES.clear()
    with (
        patch("src.session_store.SESSION_STATE_PATH", str(TEST_SESSION_PATH)),
        patch("src.session_store.INTERACTION_LOG_PATH", str(TEST_INTERACTION_PATH)),
        patch("src.audit.AUDIT_DIR", TEST_AUDIT_DIR),
    ):
        yield
    THREAD_MESSAGES.clear()
    _remove_test_files()


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

    _button(app, "Generate report").click().run(timeout=30)

    assert not app.exception
    assert any(
        "Please enter a location and audience" in warning.value
        for warning in app.warning
    )
    assert app.session_state["latest_analysis"] is None


def test_load_example_populates_report_form(isolated_app_storage):
    app = _run_app()
    app.selectbox(key="selected_example_case").set_value("Cairns school pilot").run(timeout=30)

    _button(app, "Load example").click().run(timeout=30)

    assert not app.exception
    assert app.text_input(key="form_location").value == "Cairns, Queensland"
    assert app.text_input(key="form_audience").value == "Students, teachers, school administrators and parents"
    assert app.selectbox(key="form_scenario").value == "School bushfire preparedness"
    assert "Candidate assembly points" in app.multiselect(key="form_concerns").value
    assert app.session_state["selected_map_area"] == {
        "state": "Queensland",
        "level": "SA4",
        "area_name": "Cairns",
    }


def test_generate_button_creates_report_preview_with_mocked_model(isolated_app_storage):
    with patch(
        "src.assistants.assistant_router.AssistantRouter.get_assistant_response",
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
    model_call.assert_called_once()
    assert app.session_state["latest_analysis"]["profile"]["location"] == "Hobart, Tasmania"
    assert app.session_state["latest_quality"]["summary"]["total"] == 11
    assert app.session_state["latest_audit_path"].startswith(str(TEST_AUDIT_DIR))
    assert any("Latest Report Preview" in markdown.value for markdown in app.markdown)
    assert any("Hobart School Bushfire Preparedness Draft" in markdown.value for markdown in app.markdown)
