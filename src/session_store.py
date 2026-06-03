import os
import pickle

import streamlit as st

from src.app_state import WELCOME_MESSAGE, normalise_loaded_messages
from src.assistants.assistant import THREAD_MESSAGES
from src.assistants.assistant_router import AssistantRouter


SESSION_STATE_PATH = "chat_history/session_state.pkl"
INTERACTION_LOG_PATH = "chat_history/interaction.jsonl"


def initialize_state():
    if "messages" not in st.session_state:
        try:
            with open(SESSION_STATE_PATH, "rb") as file:
                data = pickle.load(file)
            st.session_state.messages = normalise_loaded_messages(data.get("messages", []))
            st.session_state.copied = data.get("copied", [])
            st.session_state.latest_analysis = data.get("latest_analysis")
            st.session_state.latest_quality = data.get("latest_quality")
            st.session_state.latest_audit_path = data.get("latest_audit_path")
            st.session_state.latest_review_record = data.get("latest_review_record")
        except Exception:
            st.session_state.messages = [
                {
                    "role": "assistant",
                    "content": WELCOME_MESSAGE,
                }
            ]
            st.session_state.copied = []

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


def sync_thread_messages():
    if "assistant" not in st.session_state or "messages" not in st.session_state:
        return
    thread_id = st.session_state.assistant.current_thread.id
    THREAD_MESSAGES[thread_id] = normalise_loaded_messages(st.session_state.messages)


def persist_session_state():
    try:
        os.makedirs("chat_history", exist_ok=True)
        with open(SESSION_STATE_PATH, "wb") as file:
            pickle.dump(
                {
                    "messages": st.session_state.get("messages", []),
                    "copied": st.session_state.get("copied", []),
                    "latest_analysis": st.session_state.get("latest_analysis"),
                    "latest_quality": st.session_state.get("latest_quality"),
                    "latest_audit_path": st.session_state.get("latest_audit_path"),
                    "latest_review_record": st.session_state.get("latest_review_record"),
                },
                file,
            )
    except Exception:
        pass


def clear_conversation():
    for path in [
        SESSION_STATE_PATH,
        INTERACTION_LOG_PATH,
        "chat_history/tools.txt",
        "chat_history/user_profile.txt",
        "chat_history/plan.txt",
    ]:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()
