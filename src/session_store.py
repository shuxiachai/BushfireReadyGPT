import json
import logging
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import streamlit as st

from src.app_state import WELCOME_MESSAGE, normalise_loaded_messages
from src.assistants.assistant import clear_thread_messages, replace_thread_messages
from src.assistants.assistant_router import AssistantRouter
from src.data_artifacts import atomic_write_json
from src.governance import DRAFT_STATUS, HUMAN_REVIEW_CHECKLIST

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


def initialize_state():
    if "messages" not in st.session_state:
        data = _load_persisted_state()
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
        st.session_state.assistant = AssistantRouter("ChecklistAssistant")
        sync_thread_messages()
        st.rerun()

    if "assistant" not in st.session_state:
        st.session_state.assistant = AssistantRouter("ChecklistAssistant")

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


def sync_thread_messages():
    if "assistant" not in st.session_state or "messages" not in st.session_state:
        return
    thread_id = st.session_state.assistant.current_thread.id
    # Persisted UI messages may contain reviewer identity in governed sign-off
    # sections. A restored model thread always starts clean; report revision adds
    # a separately sanitised current report to its prompt.
    replace_thread_messages(thread_id, [])


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
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return date.today()


def persist_session_state():
    if not SESSION_STATE_PATH:
        return True

    try:
        target = Path(SESSION_STATE_PATH)
        payload = {key: st.session_state.get(key) for key in PERSISTED_STATE_KEYS}
        atomic_write_json(target, payload)
        target.chmod(0o600)
    except (OSError, TypeError, ValueError) as error:
        logger.warning("Optional session persistence failed: %s", error)
        st.session_state["persistence_warning"] = (
            "The report and audit were kept in this browser session, but optional session-file "
            "persistence failed. Check BUSHFIRE_SESSION_STATE_PATH permissions and free disk space."
        )
        return False
    st.session_state["persistence_warning"] = None
    return True


def clear_conversation():
    assistant = st.session_state.get("assistant")
    current_thread = getattr(assistant, "current_thread", None)
    current_thread_id = getattr(current_thread, "id", None)
    if current_thread_id:
        clear_thread_messages(current_thread_id)
    for path in [
        SESSION_STATE_PATH,
        INTERACTION_LOG_PATH,
    ]:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


def _load_persisted_state():
    if not SESSION_STATE_PATH:
        return None
    try:
        with open(SESSION_STATE_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
