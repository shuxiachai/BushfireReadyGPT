from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date
from statistics import median

PILOT_EVALUATION_SCHEMA_VERSION = 1

PERSPECTIVES = {
    "council",
    "school",
    "community",
    "public_health",
    "software_governance",
    "other",
}
EDIT_EXTENTS = {"none", "light", "partial_rewrite", "major_rewrite"}
ISSUE_SEVERITIES = {"Critical", "High", "Medium", "Low"}
ISSUE_STATUSES = {"Open", "Fixed", "Accepted"}
FINDING_CATEGORIES = {
    "safety_boundary",
    "evidence_comprehension",
    "report_content",
    "workflow",
    "export",
    "accessibility",
    "privacy",
    "other",
}
DISPOSITIONS = {"pending", "fix_planned", "fixed", "accepted_risk", "duplicate"}
OWNER_ROLES = {"maintainer", "product_reviewer", "data_reviewer", "safety_reviewer", "unassigned"}

_PARTICIPANT_CODE = re.compile(r"P\d{2}\Z")
_ISSUE_ID = re.compile(r"BC-\d{3}\Z")
_TEST_PATH = re.compile(r"tests/[A-Za-z0-9_./-]+\.py(?:::[A-Za-z0-9_\[\]-]+)?\Z")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?61|0)[ -]?(?:\d[ -]?){8,9}(?!\d)")

_SESSION_FIELDS = {
    "participant_code",
    "perspective",
    "scenario",
    "session_date",
    "tasks_completed",
    "workflow_minutes",
    "export_opened",
    "facilitator_help_count",
    "report_usefulness",
    "evidence_classes_correct",
    "safety_boundary_understood",
    "edit_extent",
    "citations_checked",
    "citations_supported",
    "citation_trust",
    "issue_ids",
}
_BAD_CASE_FIELDS = {
    "id",
    "title",
    "severity",
    "status",
    "finding_category",
    "participant_codes",
    "regression_test",
    "owner_role",
    "disposition",
}


class PilotEvaluationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise PilotEvaluationError(code, message)


def _require_exact_fields(value, expected, label):
    if not isinstance(value, dict):
        _fail("invalid_record", f"{label} must be an object.")
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        _fail("missing_field", f"{label} is missing: {', '.join(missing)}.")
    if unknown:
        _fail("privacy_field_rejected", f"{label} contains unsupported field(s): {', '.join(unknown)}.")


def _bounded_int(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail("invalid_measure", f"{label} must be an integer from {minimum} to {maximum}.")
    return value


def _bounded_number(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("invalid_measure", f"{label} must be a number from {minimum} to {maximum}.")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        _fail("invalid_measure", f"{label} must be a finite number from {minimum} to {maximum}.")
    return number


def _choice(value, options, label):
    if value not in options:
        _fail("invalid_choice", f"{label} must be one of: {', '.join(sorted(options))}.")
    return value


def _safe_short_text(value, label, *, maximum=100):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        _fail("invalid_text", f"{label} must contain 1-{maximum} characters.")
    text = value.strip()
    if _EMAIL.search(text) or _PHONE.search(text):
        _fail("personal_data_rejected", f"{label} appears to contain contact details.")
    return text


def validate_pilot_payload(payload):
    """Validate the repository-safe, anonymous controlled-pilot data contract."""

    if not isinstance(payload, dict):
        _fail("invalid_payload", "Pilot evaluation data must be an object.")
    expected_top_level = {"schema_version", "sessions", "bad_cases"}
    if set(payload) != expected_top_level:
        missing = sorted(expected_top_level - set(payload))
        unknown = sorted(set(payload) - expected_top_level)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unsupported " + ", ".join(unknown))
        _fail("invalid_payload_fields", "Pilot evaluation fields are invalid: " + "; ".join(details) + ".")
    if payload["schema_version"] != PILOT_EVALUATION_SCHEMA_VERSION:
        _fail("unsupported_schema", f"schema_version must be {PILOT_EVALUATION_SCHEMA_VERSION}.")
    if not isinstance(payload["sessions"], list) or not isinstance(payload["bad_cases"], list):
        _fail("invalid_collection", "sessions and bad_cases must be arrays.")

    sessions = [_validate_session(item, index) for index, item in enumerate(payload["sessions"], start=1)]
    participant_codes = [item["participant_code"] for item in sessions]
    if len(participant_codes) != len(set(participant_codes)):
        _fail("duplicate_participant", "Each participant code may appear only once.")

    bad_cases = [_validate_bad_case(item, index) for index, item in enumerate(payload["bad_cases"], start=1)]
    issue_ids = [item["id"] for item in bad_cases]
    if len(issue_ids) != len(set(issue_ids)):
        _fail("duplicate_bad_case", "Each Bad Case ID may appear only once.")
    known_participants = set(participant_codes)
    known_issues = set(issue_ids)
    for session in sessions:
        unknown_issues = sorted(set(session["issue_ids"]) - known_issues)
        if unknown_issues:
            _fail(
                "unknown_bad_case",
                f"{session['participant_code']} references unknown Bad Case IDs: {', '.join(unknown_issues)}.",
            )
    for bad_case in bad_cases:
        unknown_participants = sorted(set(bad_case["participant_codes"]) - known_participants)
        if unknown_participants:
            _fail(
                "unknown_participant",
                f"{bad_case['id']} references unknown participant codes: {', '.join(unknown_participants)}.",
            )

    return {
        "schema_version": PILOT_EVALUATION_SCHEMA_VERSION,
        "sessions": sessions,
        "bad_cases": bad_cases,
    }


def _validate_session(item, index):
    label = f"session {index}"
    _require_exact_fields(item, _SESSION_FIELDS, label)
    participant_code = str(item["participant_code"] or "")
    if not _PARTICIPANT_CODE.fullmatch(participant_code):
        _fail("invalid_participant_code", f"{label} participant_code must match P01-style anonymous codes.")
    scenario = _safe_short_text(item["scenario"], f"{label} scenario", maximum=80)
    try:
        session_date = date.fromisoformat(str(item["session_date"]))
    except ValueError:
        _fail("invalid_date", f"{label} session_date must use YYYY-MM-DD.")
    if session_date > date.today():
        _fail("future_date", f"{label} session_date cannot be in the future.")
    if not isinstance(item["export_opened"], bool) or not isinstance(item["safety_boundary_understood"], bool):
        _fail("invalid_boolean", f"{label} export_opened and safety_boundary_understood must be booleans.")
    citations_checked = _bounded_int(item["citations_checked"], 0, 20, f"{label} citations_checked")
    citations_supported = _bounded_int(item["citations_supported"], 0, 20, f"{label} citations_supported")
    if citations_supported > citations_checked:
        _fail("invalid_citation_measure", f"{label} citations_supported cannot exceed citations_checked.")
    issue_ids = item["issue_ids"]
    if not isinstance(issue_ids, list) or any(not _ISSUE_ID.fullmatch(str(value)) for value in issue_ids):
        _fail("invalid_issue_reference", f"{label} issue_ids must contain BC-001-style IDs.")
    if len(issue_ids) != len(set(issue_ids)):
        _fail("duplicate_issue_reference", f"{label} contains duplicate issue IDs.")
    return {
        "participant_code": participant_code,
        "perspective": _choice(item["perspective"], PERSPECTIVES, f"{label} perspective"),
        "scenario": scenario,
        "session_date": session_date.isoformat(),
        "tasks_completed": _bounded_int(item["tasks_completed"], 0, 8, f"{label} tasks_completed"),
        "workflow_minutes": _bounded_number(item["workflow_minutes"], 0.1, 120, f"{label} workflow_minutes"),
        "export_opened": item["export_opened"],
        "facilitator_help_count": _bounded_int(
            item["facilitator_help_count"], 0, 20, f"{label} facilitator_help_count"
        ),
        "report_usefulness": _bounded_int(item["report_usefulness"], 1, 5, f"{label} report_usefulness"),
        "evidence_classes_correct": _bounded_int(
            item["evidence_classes_correct"], 0, 5, f"{label} evidence_classes_correct"
        ),
        "safety_boundary_understood": item["safety_boundary_understood"],
        "edit_extent": _choice(item["edit_extent"], EDIT_EXTENTS, f"{label} edit_extent"),
        "citations_checked": citations_checked,
        "citations_supported": citations_supported,
        "citation_trust": _bounded_int(item["citation_trust"], 1, 5, f"{label} citation_trust"),
        "issue_ids": list(issue_ids),
    }


def _validate_bad_case(item, index):
    label = f"bad case {index}"
    _require_exact_fields(item, _BAD_CASE_FIELDS, label)
    issue_id = str(item["id"] or "")
    if not _ISSUE_ID.fullmatch(issue_id):
        _fail("invalid_bad_case_id", f"{label} id must match BC-001-style IDs.")
    participants = item["participant_codes"]
    if not isinstance(participants, list) or any(not _PARTICIPANT_CODE.fullmatch(str(value)) for value in participants):
        _fail("invalid_participant_reference", f"{label} participant_codes must use anonymous P01-style codes.")
    regression_test = str(item["regression_test"] or "")
    if regression_test and not _TEST_PATH.fullmatch(regression_test):
        _fail("invalid_regression_test", f"{label} regression_test must be empty or a tests/...py path.")
    return {
        "id": issue_id,
        "title": _safe_short_text(item["title"], f"{label} title", maximum=120),
        "severity": _choice(item["severity"], ISSUE_SEVERITIES, f"{label} severity"),
        "status": _choice(item["status"], ISSUE_STATUSES, f"{label} status"),
        "finding_category": _choice(item["finding_category"], FINDING_CATEGORIES, f"{label} finding_category"),
        "participant_codes": list(participants),
        "regression_test": regression_test,
        "owner_role": _choice(item["owner_role"], OWNER_ROLES, f"{label} owner_role"),
        "disposition": _choice(item["disposition"], DISPOSITIONS, f"{label} disposition"),
    }


def summarise_pilot_payload(payload):
    validated = validate_pilot_payload(payload)
    sessions = validated["sessions"]
    bad_cases = validated["bad_cases"]
    if not sessions:
        return {
            "status": "awaiting_participants",
            "participants": 0,
            "completion_gate_passed": False,
            "metrics": {},
            "bad_cases": {
                "total": len(bad_cases),
                "open_critical_or_high": sum(
                    1 for item in bad_cases if item["status"] == "Open" and item["severity"] in {"Critical", "High"}
                ),
            },
            "target_results": {},
        }

    participant_count = len(sessions)
    citations_checked = sum(item["citations_checked"] for item in sessions)
    citations_supported = sum(item["citations_supported"] for item in sessions)
    open_critical_or_high = sum(
        1 for item in bad_cases if item["status"] == "Open" and item["severity"] in {"Critical", "High"}
    )
    metrics = {
        "task_completion_at_least_7_rate": _rate(sessions, lambda item: item["tasks_completed"] >= 7),
        "median_workflow_minutes": round(float(median(item["workflow_minutes"] for item in sessions)), 2),
        "median_report_usefulness": round(float(median(item["report_usefulness"] for item in sessions)), 2),
        "median_evidence_classes_correct": round(
            float(median(item["evidence_classes_correct"] for item in sessions)), 2
        ),
        "safety_boundary_understanding_rate": _rate(sessions, lambda item: item["safety_boundary_understood"]),
        "export_success_rate": _rate(sessions, lambda item: item["export_opened"]),
        "facilitator_help_total": sum(item["facilitator_help_count"] for item in sessions),
        "citation_support_rate": round(citations_supported / citations_checked, 4) if citations_checked else None,
        "median_citation_trust": round(float(median(item["citation_trust"] for item in sessions)), 2),
        "edit_extent_counts": dict(sorted(Counter(item["edit_extent"] for item in sessions).items())),
    }
    targets = {
        "minimum_participants": participant_count >= 3,
        "task_completion": metrics["task_completion_at_least_7_rate"] >= 0.8,
        "workflow_time": metrics["median_workflow_minutes"] <= 10,
        "report_usefulness": metrics["median_report_usefulness"] >= 4,
        "evidence_understanding": metrics["median_evidence_classes_correct"] >= 4,
        "safety_boundary": metrics["safety_boundary_understanding_rate"] == 1.0,
        "export_success": metrics["export_success_rate"] == 1.0,
        "critical_or_high_disposition": open_critical_or_high == 0,
    }
    return {
        "status": "complete" if all(targets.values()) else "measured_below_gate",
        "participants": participant_count,
        "completion_gate_passed": all(targets.values()),
        "metrics": metrics,
        "bad_cases": {
            "total": len(bad_cases),
            "open_critical_or_high": open_critical_or_high,
            "with_regression_test": sum(1 for item in bad_cases if item["regression_test"]),
        },
        "target_results": targets,
    }


def _rate(rows, predicate):
    return round(sum(1 for row in rows if predicate(row)) / len(rows), 4)
