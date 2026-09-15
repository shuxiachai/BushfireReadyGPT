"""Session-only progress driven by actual workflow boundaries, not estimates."""

import math
import time
from contextlib import contextmanager

import streamlit as st

_STAGE_LABELS = {
    "analysis_pipeline": "Analysing the planning inputs",
    "data_integrity": "Checking local data",
    "profile_agent": "Preparing the planning profile",
    "australian_data_agent": "Loading Australian data",
    "community_vulnerability_agent": "Evaluating planning context",
    "official_knowledge_agent": "Retrieving official references",
    "risk_context_agent": "Preparing risk context",
    "planner_agent": "Building the planning outline",
    "report_agent": "Preparing the report",
    "evidence_confidence": "Checking evidence availability",
    "prompt_build": "Preparing the model request",
    "model_generation": "Generating the narrative",
    "model_repair": "Retrying the model request",
    "model_response_validation": "Checking the generated narrative",
    "grounding_evaluation": "Checking claim citations",
    "governance_finalize": "Preparing the governed report",
    "audit_write": "Saving the audit record",
    "session_persist": "Saving the session",
}
_ATTEMPT_LABELS = {
    "initial": "Generation attempt",
    "revision": "Revision attempt",
    "structural_repair": "Structure repair attempt",
    "protocol_retry": "Protocol retry attempt",
}


class WorkflowProgress:
    def __init__(self, status, label):
        self.status = status
        self.label = label
        self.started = time.perf_counter()

    def __call__(self, event):
        if not isinstance(event, dict):
            return
        stage = event.get("stage")
        label = _STAGE_LABELS.get(stage)
        if label is None:
            return
        if event.get("event") == "stage_started":
            attempt = event.get("attempt")
            if type(attempt) is int and attempt > 0 and stage in {"model_generation", "model_repair"}:
                kind = _ATTEMPT_LABELS.get(event.get("request_kind"), "Model attempt")
                label = f"{kind} {attempt}"
            elapsed = max(0.0, time.perf_counter() - self.started)
            self.status.update(label=f"{label} · {elapsed:.1f}s elapsed")
        elif event.get("event") == "stage_finished":
            duration = event.get("stage_elapsed_ms")
            if type(duration) in {int, float} and math.isfinite(duration) and duration >= 0:
                self.status.write(f"{label}: {duration / 1000:.1f}s")

    def finish(self, *, error=False):
        elapsed = max(0.0, time.perf_counter() - self.started)
        label = "Action needs attention" if error else "Action completed"
        self.status.update(label=f"{label} · {elapsed:.1f}s", state="error" if error else "complete", expanded=error)


@contextmanager
def workflow_progress(label):
    with st.status(label, expanded=False) as status:
        progress = WorkflowProgress(status, label)
        with st.spinner("Working — elapsed time is measured, not an estimate.", show_time=True):
            yield progress
