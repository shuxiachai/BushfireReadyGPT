"""Session-only failed revision recovery and non-content progress observation."""

import copy
import itertools
import json
from types import SimpleNamespace

import pytest

from src import report_workflow as workflow
from src import revision_state as recovery
from src import runtime_trace
from src.model_runtime import ModelServiceError
from src.session_store import PERSISTED_STATE_KEYS
from tests.test_model_evidence import _claim, _runtime
from tests.test_model_evidence import export_case as export_case


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def _state():
    return State(
        session_id="session-a",
        latest_report={"id": "report-a", "version": 1, "text": "Original governed report.", "audit_path": "audit-a"},
    )


def test_failed_request_and_application_checks_are_bounded_and_not_persisted():
    state = _state()
    original = copy.deepcopy(state["latest_report"])
    recovery.begin_pending_revision(state, "Clarify this private user request.")
    recovery.fail_pending_revision(
        state,
        "revision_quality_gate_failed",
        message="The original report is unchanged.",
        blocking_failures=[
            {
                "name": "Missing section",
                "detail": "Include the Action Plan.",
                "rejected_response": "DO NOT STORE THIS DRAFT",
            }
        ]
        * 30,
    )
    pending = recovery.get_pending_revision(state)
    assert pending["request_text"] == "Clarify this private user request."
    assert len(pending["blocking_failures"]) == 20
    assert pending["blocking_failures"][0] == {"name": "Missing section", "detail": "Include the Action Plan."}
    assert pending["status"] == "failed" and pending["retry_allowed"] is True
    assert "DO NOT STORE THIS DRAFT" not in json.dumps(state)
    assert state["latest_report"] == original
    assert not any(key.startswith("_pending_revision") for key in PERSISTED_STATE_KEYS)
    pending["request_text"] = "External mutation"
    assert recovery.get_pending_revision(state)["request_text"] != "External mutation"


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", "session-b"),
        ("id", "report-b"),
        ("version", 2),
        ("text", "Different report."),
        ("audit_path", "audit-b"),
    ],
)
def test_session_or_report_binding_change_discards_pending_before_widgets(field, value):
    state = _state()
    recovery.begin_pending_revision(state, "Clarify wording.")
    state["_pending_revision_editor_old"] = "Old private request"
    state["_pending_revision_editor"] = "Legacy editor"
    if field == "session_id":
        state[field] = value
    else:
        state["latest_report"][field] = value
    assert recovery.get_pending_revision(state, interrupt_running=True) is None
    assert not any(key.startswith("_pending_revision_editor") for key in state)


def test_interrupted_running_request_is_not_replayed_and_audit_phase_stays_nonretryable():
    state = _state()
    recovery.begin_pending_revision(state, "Clarify wording.")
    with pytest.raises(ValueError, match="already running"):
        recovery.begin_pending_revision(state, "Second request.")
    pending = recovery.get_pending_revision(state, interrupt_running=True)
    assert pending["status"] == "interrupted" and pending["error_code"] == "revision_interrupted"
    recovery.begin_pending_revision(state, "Retry explicitly.")
    recovery.mark_revision_finalizing(state)
    pending = recovery.get_pending_revision(state, interrupt_running=True)
    assert pending["status"] == "interrupted" and pending["retry_allowed"] is False
    with pytest.raises(ValueError, match="finalization"):
        recovery.begin_pending_revision(state, "Must not automatically call model again.")


def test_discard_defers_widget_key_cleanup_until_next_render_boundary():
    state = _state()
    recovery.begin_pending_revision(state, "Clarify wording.")
    state["_pending_revision_editor_hash"] = "Currently instantiated widget"
    recovery.discard_pending_revision(state)
    assert "_pending_revision_editor_hash" in state
    assert recovery.get_pending_revision(state, interrupt_running=True) is None
    assert "_pending_revision_editor_hash" not in state


@pytest.mark.parametrize("request_text", ["a" * 4001, 123, ""])
def test_invalid_revision_request_is_not_retained(request_text):
    state = _state()
    with pytest.raises(ValueError):
        recovery.begin_pending_revision(state, request_text)
    assert recovery.get_pending_revision(state) is None


@pytest.fixture
def revision_workflow(export_case, monkeypatch):
    parent = {
        "id": "parent",
        "version": 1,
        "text": export_case["report_text"],
        "analysis": copy.deepcopy(export_case["analysis"]),
        "inputs": {},
        "area_selection": None,
        "export_register_snapshot": export_case["register_snapshot"],
        "audit_path": export_case["audit_path"],
    }
    state = State(
        session_id="session-a", latest_report=parent, latest_quality={"approval_gate": {"passed": True}}, messages=[]
    )
    monkeypatch.setattr(workflow, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(workflow, "validate_model_privacy_boundary", lambda: None)
    monkeypatch.setattr(workflow, "_cloud_rag_availability_error", lambda _: None)
    monkeypatch.setattr(workflow, "_report_matches_audit_snapshot", lambda *_: True)
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "false")
    return state


def test_failed_quality_preserves_original_report_and_latest_quality_but_retains_request(
    revision_workflow, monkeypatch
):
    state = revision_workflow
    original = copy.deepcopy(dict(state))
    failure = {"name": "Required sections", "detail": "Missing Action Plan."}
    monkeypatch.setattr(
        workflow,
        "generate_narrative_with_repairs",
        lambda *_a, **_k: (
            "REJECTED MODEL PROSE MUST NOT BE RETAINED",
            {"approval_gate": {"passed": False, "blocking_failures": [failure]}},
            1,
        ),
    )
    monkeypatch.setattr(
        workflow, "_finalize_report_version", lambda *_a, **_k: pytest.fail("Do not finalize failed quality")
    )
    response, error = workflow.revise_current_report(
        "Clarify private wording.", lambda: pytest.fail("Do not persist failure")
    )
    assert response is None and "original report is unchanged" in error
    assert state["latest_report"] == original["latest_report"] and state["latest_quality"] == original["latest_quality"]
    assert state["messages"] == original["messages"]
    pending = recovery.get_pending_revision(state)
    assert pending["request_text"] == "Clarify private wording."
    assert pending["blocking_failures"] == [failure] and pending["message"] == error
    assert "REJECTED MODEL PROSE" not in json.dumps(state)


def test_model_failure_is_recoverable_without_discarding_the_request(revision_workflow, monkeypatch):
    def fail(*_args, **_kwargs):
        raise ModelServiceError("The model service is unavailable.")

    monkeypatch.setattr(workflow, "generate_narrative_with_repairs", fail)
    response, error = workflow.revise_current_report("Retain this request.", lambda: None)
    pending = recovery.get_pending_revision(revision_workflow)
    assert response is None and error == "The model service is unavailable."
    assert pending["error_code"] == "model_service_error" and pending["retry_allowed"]


def test_finalization_failure_is_not_automatically_resubmitted_to_model(revision_workflow, monkeypatch):
    calls = []

    def generate(*_args, **_kwargs):
        calls.append("model")
        return "Accepted draft wording.", {"approval_gate": {"passed": True}}, 1

    monkeypatch.setattr(workflow, "generate_narrative_with_repairs", generate)
    monkeypatch.setattr(workflow, "_finalize_report_version", lambda *_a, **_k: (None, "Audit write failed."))
    original = copy.deepcopy(revision_workflow["latest_report"])
    assert workflow.revise_current_report("Revise wording.", lambda: None) == (None, "Audit write failed.")
    pending = recovery.get_pending_revision(revision_workflow)
    assert pending["error_code"] == "report_finalization_error" and pending["retry_allowed"] is False
    response, error = workflow.revise_current_report("Retry wording.", lambda: None)
    assert response is None and "finalization" in error and calls == ["model"]
    assert revision_workflow["latest_report"] == original


def test_success_clears_pending_and_revision_emits_actual_progress_events(revision_workflow, monkeypatch):
    from src import report_generation_quality

    calls, events = [], []
    revision_workflow["model_client"] = _runtime(_claim(), calls)
    monkeypatch.setattr(
        report_generation_quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": True}}
    )
    monkeypatch.setattr(workflow, "_finalize_report_version", lambda text, *_a, **_k: (text, None))
    response, error = workflow.revise_current_report("Clarify wording.", lambda: None, progress_callback=events.append)
    assert response and error is None and len(calls) == 1
    assert recovery.get_pending_revision(revision_workflow) is None
    model_events = [event for event in events if event["stage"] == "model_generation"]
    assert [event["event"] for event in model_events] == ["stage_started", "stage_finished"]
    assert all(event["attempt"] == 1 and event["request_kind"] == "revision" for event in model_events)
    assert "Clarify wording" not in json.dumps(events) and "Preparedness guide" not in json.dumps(events)


@pytest.mark.parametrize("enabled", [True, False])
def test_progress_observer_uses_actual_stage_times_and_is_not_serialized(tmp_path, monkeypatch, enabled):
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", str(enabled))
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path))
    counter = itertools.count()
    monkeypatch.setattr(runtime_trace.time, "perf_counter", lambda: next(counter) * 0.005)
    events = []
    with runtime_trace.RuntimeTrace("report.generate", progress_callback=events.append) as trace:
        with trace.stage("model_generation", attempt=2, request_kind="protocol_retry"):
            pass
    assert [event["event"] for event in events] == ["stage_started", "stage_finished"]
    assert events[0]["elapsed_ms"] < events[1]["elapsed_ms"]
    assert events[0]["stage_elapsed_ms"] == 0 and events[1]["stage_elapsed_ms"] > 0
    assert events[1]["attempt"] == 2 and events[1]["request_kind"] == "protocol_retry"
    assert all(
        set(event) == {"event", "operation", "stage", "elapsed_ms", "stage_elapsed_ms", "attempt", "request_kind"}
        for event in events
    )
    files = list(tmp_path.glob("trace_*.json"))
    assert bool(files) is enabled
    if enabled:
        payload = files[0].read_text(encoding="utf-8")
        assert "progress_callback" not in payload and "stage_started" not in payload
        assert runtime_trace.load_trace_summary(trace_dir=tmp_path)["traces"] == 1


def test_display_callback_failures_do_not_change_workflow_but_control_flow_escapes(monkeypatch):
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "false")

    def display_error(_event):
        raise RuntimeError("Display failure with private detail.")

    executed = []
    with runtime_trace.RuntimeTrace("report.revise", progress_callback=display_error) as trace:
        with trace.stage("prompt_build"):
            executed.append(True)
    assert executed == [True]

    class ControlFlow(BaseException):
        pass

    def stop(_event):
        raise ControlFlow()

    with pytest.raises(ControlFlow):
        with runtime_trace.RuntimeTrace("report.revise", progress_callback=stop) as trace:
            with trace.stage("prompt_build"):
                pytest.fail("Control flow must not be swallowed")
    assert runtime_trace.get_active_trace() is None
