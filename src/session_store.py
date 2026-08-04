import json
import os
from pathlib import Path
from uuid import uuid4

import streamlit as st

from src.app_state import WELCOME_MESSAGE, normalise_loaded_messages
from src.assistants.assistant import THREAD_MESSAGES
from src.assistants.assistant_router import AssistantRouter


SESSION_STATE_PATH = os.environ.get("BUSHFIRE_SESSION_STATE_PATH", "").strip() or None
INTERACTION_LOG_PATH = os.environ.get("BUSHFIRE_INTERACTION_LOG_PATH", "").strip() or None

PERSISTED_STATE_KEYS = [
    "messages",
    "copied",
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
            st.session_state.copied = data.get("copied", [])
            st.session_state.latest_analysis = data.get("latest_analysis")
            st.session_state.latest_quality = data.get("latest_quality")
            st.session_state.latest_audit_path = data.get("latest_audit_path")
            st.session_state.latest_review_record = data.get("latest_review_record")
            st.session_state.latest_report = data.get("latest_report")
        else:
            st.session_state.messages = [
                {
                    "role": "assistant",
                    "content": WELCOME_MESSAGE,
                }
            ]
            st.session_state.copied = []

        st.session_state.session_id = uuid4().hex
        st.session_state.assistant = AssistantRouter("ChecklistAssistant")
        sync_thread_messages()
        st.rerun()

    if "assistant" not in st.session_state:
        st.session_state.assistant = AssistantRouter("ChecklistAssistant")

    if "copied" not in st.session_state:
        st.session_state.copied = []

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
    THREAD_MESSAGES[thread_id] = normalise_loaded_messages(st.session_state.messages)


def persist_session_state():
    if not SESSION_STATE_PATH:
        return

    try:
        target = Path(SESSION_STATE_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        payload = {key: st.session_state.get(key) for key in PERSISTED_STATE_KEYS}
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except (OSError, TypeError, ValueError):
        return


def clear_conversation():
    for path in [
        SESSION_STATE_PATH,
        INTERACTION_LOG_PATH,
        "chat_history/tools.txt",
        "chat_history/user_profile.txt",
        "chat_history/plan.txt",
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
