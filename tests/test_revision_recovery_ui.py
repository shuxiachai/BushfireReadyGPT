from streamlit.testing.v1 import AppTest

_APP = """
import streamlit as st
from src.revision_state import begin_pending_revision, fail_pending_revision, discard_pending_revision, get_pending_revision
from src.ui.revision_recovery import render_revision_recovery

if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.session_id = "synthetic-session"
    st.session_state.latest_report = {"id":"synthetic-report", "version":1, "text":"Original draft", "audit_path":"synthetic-audit"}
    begin_pending_revision(st.session_state, "Original revision request")
    fail_pending_revision(st.session_state, "revision_quality_gate_failed", blocking_failures=[{"name":"Sections", "detail":"Missing required section"}])
get_pending_revision(st.session_state, interrupt_running=True)

def revise(request, *, progress_callback=None):
    st.session_state.submitted_request = request
    if progress_callback:
        progress_callback({"event":"stage_started", "stage":"model_generation", "attempt":1, "request_kind":"revision"})
    discard_pending_revision(st.session_state)
    return "Revised draft", None

render_revision_recovery(revise)
"""


def _button(app, label):
    return next(button for button in app.button if button.label == label)


def test_failed_request_remains_editable_across_rerun_and_submits_edited_text():
    app = AppTest.from_string(_APP).run()
    assert not app.exception
    assert any("original report is unchanged" in warning.value for warning in app.warning)
    assert any("Missing required section" in text.value for text in app.text)
    app.run()
    editor = next(area for area in app.text_area if area.label == "Edit the revision request")
    assert editor.value == "Original revision request"
    editor.set_value("Use this edited request")
    _button(app, "Retry revision").click().run()
    assert not app.exception
    assert app.session_state["submitted_request"] == "Use this edited request"
    assert "_pending_revision" not in app.session_state
    assert len(app.text_area) == 0


def test_discard_request_does_not_call_model_or_change_original_report():
    app = AppTest.from_string(_APP).run()
    previous = dict(app.session_state["latest_report"])
    _button(app, "Discard request").click().run()
    assert not app.exception
    assert "_pending_revision" not in app.session_state
    assert "submitted_request" not in app.session_state
    assert app.session_state["latest_report"] == previous


def test_changed_report_drops_stale_editor_without_sending_request():
    app = AppTest.from_string(_APP).run()
    app.session_state["latest_report"] = {
        "id": "new-report",
        "version": 2,
        "text": "Different draft",
        "audit_path": "new-audit",
    }
    app.run()
    assert not app.exception
    assert "_pending_revision" not in app.session_state
    assert "submitted_request" not in app.session_state
    assert len(app.text_area) == 0


def test_finalization_failure_does_not_offer_automatic_model_retry():
    code = _APP.replace(
        'fail_pending_revision(st.session_state, "revision_quality_gate_failed", blocking_failures=',
        'fail_pending_revision(st.session_state, "report_finalization_error", retry_allowed=False, blocking_failures=',
    )
    app = AppTest.from_string(code).run()
    assert not app.exception
    assert _button(app, "Retry revision").disabled
    assert "submitted_request" not in app.session_state


def test_empty_retry_shows_validation_feedback_without_calling_model():
    app = AppTest.from_string(_APP).run()
    editor = next(area for area in app.text_area if area.label == "Edit the revision request")
    editor.set_value("   ")
    _button(app, "Retry revision").click().run()
    assert not app.exception
    assert any("Enter a revision request before retrying" in warning.value for warning in app.warning)
    assert "submitted_request" not in app.session_state
    assert app.session_state["_pending_revision"]["request_text"] == "Original revision request"
