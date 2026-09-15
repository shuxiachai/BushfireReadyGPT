"""Bounded application-session revision recovery; never a persisted report artifact."""

from __future__ import annotations

from copy import deepcopy

from src.input_validation import validate_revision_request_budget
from src.model_evidence import text_sha256

_KEY = "_pending_revision"
_CLEANUP = "_pending_revision_cleanup"
_EDITOR = "_pending_revision_editor"
_ERROR_CODES = {
    "revision_failed",
    "revision_interrupted",
    "revision_quality_gate_failed",
    "model_service_error",
    "source_contract_unready",
    "report_finalization_error",
    "revision_unexpected_error",
}


def _binding(state):
    report = state.get("latest_report")
    if not isinstance(report, dict) or not isinstance(report.get("text"), str) or not report["text"].strip():
        return None
    return {
        "session_id": str(state.get("session_id") or ""),
        "report_id": str(report.get("id") or ""),
        "version": report.get("version"),
        "text_sha256": text_sha256(report["text"]),
        "audit_path": str(report.get("audit_path") or ""),
    }


def discard_pending_revision(state):
    """Discard recovery state; defer widget cleanup until the next render boundary."""
    state.pop(_KEY, None)
    state[_CLEANUP] = True


def get_pending_revision(state, *, interrupt_running=False):
    """Return a defensive copy, dropping stale report/session bindings.

    The UI calls with ``interrupt_running=True`` once, before creating widgets on
    each rerun. A running call left by an interrupted run becomes an explicit
    interrupted state; this helper never invokes a model or automatic retry.
    """
    pending = state.get(_KEY)
    valid = (
        isinstance(pending, dict)
        and set(pending)
        == {"request_text", "binding", "status", "error_code", "message", "blocking_failures", "retry_allowed"}
        and pending.get("binding") == _binding(state)
        and pending.get("binding") is not None
        and isinstance(pending.get("request_text"), str)
        and not validate_revision_request_budget(pending["request_text"])
        and isinstance(pending.get("status"), str)
        and pending["status"] in {"running", "failed", "interrupted"}
        and isinstance(pending.get("message"), str)
        and isinstance(pending.get("blocking_failures"), list)
        and type(pending.get("retry_allowed")) is bool
    )
    if pending is not None and not valid:
        discard_pending_revision(state)
        pending = None
    if interrupt_running:
        if state.pop(_CLEANUP, False):
            for key in list(state):
                if isinstance(key, str) and (key == _EDITOR or key.startswith(_EDITOR + "_")):
                    state.pop(key, None)
        if pending is not None and pending["status"] == "running":
            pending = {
                **pending,
                "status": "interrupted",
                "error_code": "revision_interrupted",
                "message": "The previous revision was interrupted; it was not restarted automatically.",
            }
            state[_KEY] = pending
    return deepcopy(pending) if pending is not None else None


def begin_pending_revision(state, request_text):
    error = validate_revision_request_budget(request_text)
    if error or not isinstance(request_text, str) or not request_text.strip():
        raise ValueError(error or "Enter a revision request.")
    binding = _binding(state)
    if binding is None:
        raise ValueError("Generate a report before requesting a governed revision.")
    pending = get_pending_revision(state)
    if pending is not None and pending["status"] == "running":
        raise ValueError("A revision is already running for this report.")
    if pending is not None and pending["retry_allowed"] is False:
        raise ValueError(
            "The previous revision reached report finalization. Resolve its audit or storage issue and "
            "review the current report before discarding this request and starting another revision."
        )
    state[_KEY] = {
        "request_text": request_text.strip(),
        "binding": binding,
        "status": "running",
        "error_code": None,
        "message": "",
        "blocking_failures": [],
        "retry_allowed": True,
    }
    state[_CLEANUP] = True
    return deepcopy(state[_KEY])


def fail_pending_revision(state, error_code, *, blocking_failures=(), retry_allowed=None, message=None):
    """Keep only bounded application-generated check names/details, never drafts."""
    if error_code not in _ERROR_CODES:
        raise ValueError("Unsupported revision recovery error code.")
    pending = get_pending_revision(state)
    if pending is None:
        return
    checks = [
        {"name": str(item.get("name") or "Quality check")[:160], "detail": str(item.get("detail") or "")[:500]}
        for item in list(blocking_failures or ())[:20]
        if isinstance(item, dict)
    ]
    pending.update(status="failed", error_code=error_code, blocking_failures=checks)
    if message is not None:
        pending["message"] = str(message)[:1000]
    if retry_allowed is not None:
        pending["retry_allowed"] = bool(retry_allowed)
    state[_KEY] = pending


def mark_revision_finalizing(state):
    """An interrupted audit/finalization must not automatically repeat a model call."""
    pending = get_pending_revision(state)
    if pending is not None:
        pending["retry_allowed"] = False
        state[_KEY] = pending
