from datetime import datetime
from pathlib import Path
from uuid import uuid4

import streamlit as st

from src.data_artifacts import atomic_write_text

PROJECT_ROOT = Path(__file__).resolve().parents[1]

WELCOME_MESSAGE = (
    "Complete the form above to generate a formal Australian bushfire preparedness report. "
    "You can then request edits, export the report and review the evidence trail."
)
OLD_WELCOME_MARKERS = [
    "\u8bf7\u5148\u586b\u5199\u4e0a\u65b9\u8868\u5355",
    "\u751f\u6210\u4e00\u4efd\u6b63\u5f0f\u7684\u6fb3\u6d32\u5c71\u706b\u5e94\u6025\u51c6\u5907\u62a5\u544a",
    "Complete the form above to generate a formal Australian bushfire preparedness report",
]


def is_welcome_message(text):
    content = str(text or "")
    return any(marker in content for marker in OLD_WELCOME_MARKERS)


def normalise_loaded_messages(messages):
    normalised = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content", "")
        if message.get("role") == "assistant" and is_welcome_message(content):
            normalised.append({"role": "assistant", "content": WELCOME_MESSAGE})
        else:
            normalised.append(message)
    return normalised


def get_active_analysis_location():
    form_location = st.session_state.get("form_location", "")
    if form_location:
        return form_location
    analysis = st.session_state.get("latest_analysis") or {}
    profile = analysis.get("profile") or {}
    if profile.get("location"):
        return profile["location"]
    return ""


def get_active_map_selection_label():
    selected = st.session_state.get("selected_map_area")
    if not selected:
        return None
    return f"{selected.get('state')} / {selected.get('level')} / {selected.get('area_name')}"


def get_latest_assistant_text():
    latest_report = st.session_state.get("latest_report") or {}
    report_text = latest_report.get("text") if isinstance(latest_report, dict) else ""
    if report_text:
        return report_text

    for message in reversed(st.session_state.get("messages", [])):
        if message.get("role") == "assistant" and message.get("kind") == "report":
            content = message.get("content", "")
            if isinstance(content, list):
                content = content[0] if content else ""
            if is_welcome_message(content):
                continue
            return content
    return ""


def save_latest_report():
    report = get_latest_assistant_text()
    if not report:
        return None
    output_dir = PROJECT_ROOT / "chat_history"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = output_dir / f"bushfire_report_{timestamp}_{uuid4().hex[:8]}.md"
    atomic_write_text(path, report)
    path.chmod(0o600)
    return str(path)
