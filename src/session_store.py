import json
import logging
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import streamlit as st

from src.app_state import WELCOME_MESSAGE, normalise_loaded_messages
from src.data_artifacts import atomic_write_json
from src.governance import DRAFT_STATUS, HUMAN_REVIEW_CHECKLIST
from src.model_runtime import GovernedModelClient

logger = logging.getLogger(__name__)

SESSION_STATE_PATH = os.environ.get("BUSHFIRE_SESSION_STATE_PATH", "").strip() or None
INTERACTION_LOG_PATH = os.environ.get("BUSHFIRE_INTERACTION_LOG_PATH", "").strip() or None

PERSISTED_STATE_KEYS = [
    "messages",
    "latest_analysis",
    "latest_quality",
    "latest_audit_path",
    "latest_review_record",
    "latest_report",
]
SESSION_STATE_SCHEMA_VERSION = 1
MAX_PERSISTED_STATE_BYTES = 5 * 1024 * 1024
MAX_PERSISTED_STATE_NESTING = 100
_BLOCKED_RESTORE_PATHS = set()


def initialize_state():
    if "messages" not in st.session_state:
        skip_restore = st.session_state.pop("_skip_persisted_restore_once", False)
        data = None if skip_restore else _load_persisted_state()
        if data:
            st.session_state.messages = normalise_loaded_messages(data.get("messages", []))
            st.session_state.latest_analysis = data.get("latest_analysis")
            st.session_state.latest_quality = data.get("latest_quality")
            st.session_state.latest_audit_path = data.get("latest_audit_path")
            st.session_state.latest_review_record = data.get("latest_review_record")
            st.session_state.latest_report = data.get("latest_report")
            _hydrate_restored_review_widgets(st.session_state.latest_report)
        else:
            st.session_state.messages = [
                {
                    "role": "assistant",
                    "content": WELCOME_MESSAGE,
                }
            ]

        st.session_state.session_id = uuid4().hex
        st.session_state.model_client = GovernedModelClient()
        st.rerun()

    if "model_client" not in st.session_state:
        st.session_state.model_client = GovernedModelClient()

    if "latest_analysis" not in st.session_state:
        st.session_state.latest_analysis = None

    if "latest_quality" not in st.session_state:
        st.session_state.latest_quality = None

    if "latest_audit_path" not in st.session_state:
        st.session_state.latest_audit_path = None

    if "latest_review_record" not in st.session_state:
        st.session_state.latest_review_record = None

    if "latest_report" not in st.session_state:
        st.session_state.latest_report = None

    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid4().hex


def _hydrate_restored_review_widgets(report_record):
    from src.report_workflow import verify_report_record_snapshot

    verified = verify_report_record_snapshot(report_record)
    review = (
        report_record.get("review_record")
        if verified and isinstance(report_record, dict) and isinstance(report_record.get("review_record"), dict)
        else {}
    )
    status = review.get("approval_status") or DRAFT_STATUS
    st.session_state.report_status = status
    st.session_state.approval_status = status
    st.session_state.approval_reviewer_name = review.get("reviewer_name", "")
    st.session_state.approval_reviewer_role = review.get("reviewer_role", "")
    st.session_state.approval_organisation_name = review.get("organisation_name", "")
    st.session_state.approval_review_notes = review.get("review_notes", "")
    st.session_state.approval_review_date = _parse_review_date(review.get("review_date"))
    checked = {
        item.get("id"): item.get("checked") is True
        for item in review.get("review_checklist", [])
        if isinstance(item, dict)
    }
    for item in HUMAN_REVIEW_CHECKLIST:
        st.session_state[f"review_check_{item['id']}"] = checked.get(item["id"], False)
    if verified:
        st.session_state.latest_review_record = review
        st.session_state.restored_governance_warning = None
    elif isinstance(report_record, dict) and report_record.get("text"):
        st.session_state.latest_review_record = None
        st.session_state.restored_governance_warning = (
            "The restored report is legacy, incomplete or no longer matches the authoritative audit head. "
            "It is read-only and cannot be reviewed, revised or exported as a governance package; regenerate it."
        )


def _parse_review_date(value):
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
    return parsed if parsed <= date.today() else None


def persist_session_state():
    if not SESSION_STATE_PATH:
        return True

    try:
        target = Path(SESSION_STATE_PATH)
        payload = {
            "schema_version": SESSION_STATE_SCHEMA_VERSION,
            **{key: st.session_state.get(key) for key in PERSISTED_STATE_KEYS},
        }
        if not _is_valid_persisted_state(payload):
            raise ValueError("Optional session state does not match the persisted-state schema.")
        encoded_payload = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(encoded_payload) > MAX_PERSISTED_STATE_BYTES:
            raise ValueError("Optional session state exceeds the configured size limit.")
        atomic_write_json(target, payload)
        target.chmod(0o600)
    except (OSError, RecursionError, TypeError, ValueError) as error:
        logger.warning("Optional session persistence failed: %s", error)
        if isinstance(error, ValueError) and "size limit" in str(error):
            st.session_state["persistence_warning"] = (
                "The report and audit were kept in this browser session, but the optional session state "
                "exceeded the configured size limit. The previous session file was left unchanged."
            )
        else:
            st.session_state["persistence_warning"] = (
                "The report and audit were kept in this browser session, but optional session-file "
                "persistence failed. Check BUSHFIRE_SESSION_STATE_PATH permissions and free disk space."
            )
        return False
    _BLOCKED_RESTORE_PATHS.discard(str(target.resolve()))
    st.session_state["persistence_warning"] = None
    return True


def clear_conversation():
    failed_paths = []
    for path in [
        SESSION_STATE_PATH,
        INTERACTION_LOG_PATH,
    ]:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError as error:
            failed_paths.append((path, error))
            if path == SESSION_STATE_PATH:
                _BLOCKED_RESTORE_PATHS.add(str(Path(path).resolve()))
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    if failed_paths:
        st.session_state["_skip_persisted_restore_once"] = True
        st.session_state["persistence_warning"] = (
            "The in-app conversation was cleared, but one or more optional session files could not be deleted. "
            "They will not be restored in this running application. Check file permissions before closing the app."
        )
    st.rerun()


def _load_persisted_state():
    if not SESSION_STATE_PATH:
        return None
    try:
        target = Path(SESSION_STATE_PATH)
        if str(target.resolve()) in _BLOCKED_RESTORE_PATHS:
            return None
        if target.stat().st_size > MAX_PERSISTED_STATE_BYTES:
            logger.warning("Optional session state exceeds the configured size limit.")
            return None
        with target.open("rb") as file:
            raw_payload = file.read(MAX_PERSISTED_STATE_BYTES + 1)
        if len(raw_payload) > MAX_PERSISTED_STATE_BYTES:
            logger.warning("Optional session state exceeds the configured size limit.")
            return None
        text_payload = raw_payload.decode("utf-8")
        if not _json_nesting_within_limit(text_payload):
            logger.warning("Optional session state exceeds the configured nesting limit.")
            return None
        data = json.loads(text_payload)
        return data if _is_valid_persisted_state(data) else None
    except (OSError, RecursionError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _json_nesting_within_limit(text, limit=MAX_PERSISTED_STATE_NESTING):
    """Bound JSON container depth in one pass while ignoring brackets inside strings."""

    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > limit:
                return False
        elif character in "]}":
            depth -= 1
    return True


def _is_valid_persisted_state(data):
    """Validate untrusted optional session JSON before hydrating Streamlit state."""

    if not isinstance(data, dict):
        return False
    schema_version = data.get("schema_version")
    if schema_version is not None and (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != SESSION_STATE_SCHEMA_VERSION
    ):
        return False

    messages = data.get("messages", [])
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
            return False
        content = message.get("content")
        if not isinstance(content, str) and not (
            isinstance(content, list) and all(isinstance(item, str) for item in content)
        ):
            return False

    for key in ("latest_analysis", "latest_quality", "latest_review_record", "latest_report"):
        if data.get(key) is not None and not isinstance(data.get(key), dict):
            return False
    if data.get("latest_audit_path") is not None and not isinstance(data.get("latest_audit_path"), str):
        return False
    return (
        _is_valid_analysis_shape(data.get("latest_analysis"))
        and _is_valid_quality_shape(data.get("latest_quality"))
        and _is_valid_review_shape(data.get("latest_review_record"))
        and _is_valid_report_shape(data.get("latest_report"))
    )


def _mapping_fields_are_mappings(value, fields, *, nullable_fields=()):
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    nullable = set(nullable_fields)
    return all(
        field not in value or isinstance(value[field], dict) or (field in nullable and value[field] is None)
        for field in fields
    )


def _list_field_has_shape(mapping, field, item_type):
    if field not in mapping:
        return True
    value = mapping[field]
    return isinstance(value, list) and all(isinstance(item, item_type) for item in value)


def _is_valid_analysis_shape(analysis):
    if analysis is None:
        return True
    if not _mapping_fields_are_mappings(
        analysis,
        (
            "profile",
            "data",
            "community",
            "knowledge",
            "risk_context",
            "plan",
            "report",
            "data_integrity",
            "area_selection",
        ),
        nullable_fields=("area_selection",),
    ):
        return False
    community = analysis.get("community") or {}
    if not _mapping_fields_are_mappings(
        community,
        ("indicators", "data_quality", "geography_reference"),
    ) or not _list_field_has_shape(community, "vulnerability_notes", str):
        return False
    data_quality = community.get("data_quality") or {}
    if not _list_field_has_shape(data_quality, "warnings", str):
        return False
    geography_reference = community.get("geography_reference") or {}
    if not _mapping_fields_are_mappings(
        geography_reference,
        ("selected_asgs_area",),
        nullable_fields=("selected_asgs_area",),
    ):
        return False
    if not _list_field_has_shape(geography_reference, "lga_candidates", dict) or not _list_field_has_shape(
        geography_reference, "limitations", str
    ):
        return False
    data_result = analysis.get("data") or {}
    if not _list_field_has_shape(data_result, "sources", dict) or not _list_field_has_shape(
        data_result, "data_limitations", str
    ):
        return False
    knowledge = analysis.get("knowledge") or {}
    if not _list_field_has_shape(knowledge, "retrieved_chunks", dict) or not _list_field_has_shape(
        knowledge, "limitations", str
    ):
        return False
    if not all(_list_field_has_shape(chunk, "rerank_reasons", str) for chunk in knowledge.get("retrieved_chunks", [])):
        return False
    risk_context = analysis.get("risk_context") or {}
    if not all(
        _list_field_has_shape(risk_context, field, str) for field in ("risk_points", "assumptions", "matched_rule_ids")
    ):
        return False
    plan = analysis.get("plan") or {}
    if not all(_list_field_has_shape(plan, field, str) for field in ("planning_priorities", "one_week_focus")):
        return False
    rows = analysis.get("evidence_confidence")
    return rows is None or (isinstance(rows, list) and all(isinstance(row, dict) for row in rows))


def _is_valid_quality_shape(quality):
    if quality is None:
        return True
    if not _mapping_fields_are_mappings(quality, ("summary", "approval_gate")):
        return False
    return _list_field_has_shape(quality, "checks", dict)


def _is_valid_review_shape(review):
    if review is None:
        return True
    if not _list_field_has_shape(review, "review_checklist", dict):
        return False
    return all(
        field not in review or isinstance(review[field], str)
        for field in (
            "approval_status",
            "reviewer_name",
            "reviewer_role",
            "review_date",
            "organisation_name",
            "review_notes",
        )
    )


def _is_valid_report_shape(report):
    if report is None:
        return True
    if "text" in report and not isinstance(report["text"], str):
        return False
    if "audit_path" in report and report["audit_path"] is not None and not isinstance(report["audit_path"], str):
        return False
    if (
        "parent_audit_path" in report
        and report["parent_audit_path"] is not None
        and not isinstance(report["parent_audit_path"], str)
    ):
        return False
    if not _mapping_fields_are_mappings(
        report,
        ("analysis", "quality", "review_record", "inputs", "area_selection", "export_register_snapshot"),
        nullable_fields=("area_selection",),
    ):
        return False
    return (
        _is_valid_analysis_shape(report.get("analysis"))
        and _is_valid_quality_shape(report.get("quality"))
        and _is_valid_review_shape(report.get("review_record"))
    )
