"""Content-free response admission diagnostics, separate from historical report policy."""

import logging
import re

from src.report_template import extract_narrative_body
from src.runtime_trace import trace_stage
from src.safety_boundary import evaluate_admission_safety
from src.source_attribution import extract_markdown_section, plain_markdown_claim_text, visible_markdown_text

_LOGGER = logging.getLogger(__name__)
_FAILURES = {
    "length": "The model reached its output limit before completing the report.",
    "content_filter": "The provider declined or filtered the response; no report was accepted.",
    "tool_calls": "The provider returned a tool call; this report workflow does not permit tools.",
    "function_call": "The provider returned a function call; this report workflow does not permit tools.",
    "missing": "The model response has no confirmed completion marker; no report was accepted.",
    "invalid": "The model response ended with an unsupported or inconsistent completion protocol.",
    "incomplete_narrative": "The Safety Disclaimer appears unfinished; no report was accepted.",
    "unsafe_operational_direction": (
        "The response contains an operational safety assertion or direction. No new report was accepted; "
        "any existing report is unchanged. Use the app for preparedness planning, not live emergency directions."
    ),
}


class ModelServiceError(RuntimeError):
    """A model-provider failure that is safe to display in the UI."""


class ModelResponseError(ModelServiceError):
    """Reject an incomplete response without retaining its prompt or returned content."""

    def __init__(self, reason):
        self.reason = reason if isinstance(reason, str) and reason in _FAILURES else "invalid"
        self.code = f"model_response_{self.reason}"
        self.retryable = self.reason in {"length", "incomplete_narrative"}
        super().__init__(_FAILURES[self.reason])


def record_response_admission(reason):
    """Record an allowlisted reason; reject everything except an explicit normal stop."""
    reason = reason if isinstance(reason, str) and reason in {"stop", *_FAILURES} else "invalid"
    if reason != "stop":
        _LOGGER.warning("Model response rejected (%s).", reason)
    with trace_stage("model_response_validation", model_finish_reason=reason):
        if reason != "stop":
            raise ModelResponseError(reason)


def validate_narrative_ending(narrative):
    """Catch obvious unfinished final prose, not prove linguistic completeness.

    This applies to newly generated/revised text only. Historical quality-policy
    fingerprints and archive verification deliberately keep their original meaning.
    Missing/empty sections remain the responsibility of the governed structure gate.
    """
    visible = visible_markdown_text(extract_narrative_body(narrative))
    disclaimer = extract_markdown_section(visible, "Safety Disclaimer").strip()
    if disclaimer and not re.search(r"[.!?][\s\"'\u2019\u201d)\]*_`]*\Z", disclaimer):
        record_response_admission("incomplete_narrative")


def validate_operational_directions(narrative):
    """New-response/new-approval admission only; never reinterprets archived policy."""
    visible = plain_markdown_claim_text(visible_markdown_text(extract_narrative_body(narrative)))
    if not evaluate_admission_safety(visible)["passed"]:
        record_response_admission("unsafe_operational_direction")
