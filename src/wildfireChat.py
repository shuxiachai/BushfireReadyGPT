from datetime import datetime

import streamlit as st

from src.app_catalog import (
    EXAMPLE_CASES,
    SCENARIO_OPTIONS,
    TIMEFRAME_OPTIONS,
)
from src.app_state import (
    get_active_analysis_location,
    get_active_map_selection_label,
    get_latest_assistant_text,
    is_welcome_message,
    save_latest_report,
)
from src.coverage_map import is_area_selection_available
from src.governance import HUMAN_REVIEW_CHECKLIST
from src.report_workflow import (
    collect_review_record,
    get_package_context,
    update_latest_audit_review,
    validate_review_record,
    verify_report_record_snapshot,
)
from src.report_workflow import (
    generate_current_report as run_generate_current_report,
)
from src.report_workflow import (
    revise_current_report as run_revise_current_report,
)
from src.report_workflow import (
    update_latest_report_signoff as run_update_latest_report_signoff,
)
from src.session_store import clear_conversation, initialize_state, persist_session_state
from src.ui.data_views import (
    render_data_register,
    render_data_status,
    render_licence_register,
    render_official_sources,
    render_official_status_panel,
    render_rag_status,
)
from src.ui.demo_views import (
    render_demo_scenario_pack,
    render_government_pilot_brief,
    render_maturity_assessment,
    render_presentation_mode,
    render_usage_guide,
)
from src.ui.layout import render_header
from src.ui.map_views import render_coverage_analysis_tools
from src.ui.report_views import render_latest_report_preview, render_report_form
from src.ui.review_views import (
    render_agent_analysis_summary,
    render_human_review_checklist,
    render_pilot_export_package,
    render_report_quality_summary,
    render_reviewer_approval,
)
from src.ui.sidebar import render_sidebar
from src.ui.theme import apply_theme

PILOT_MODE_OPTIONS = [
    "School Preparedness",
    "Council Community Preparedness",
    "Community Workshop Material",
]
st.set_page_config(
    page_title="BushfireReadyGPT",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)


def initialize_form_defaults():
    defaults = {
        "form_location": "",
        "form_audience": "",
        "form_timeframe": TIMEFRAME_OPTIONS[0],
        "form_scenario": SCENARIO_OPTIONS[0],
        "form_concerns": [],
        "form_extra_context": "",
        "pilot_mode": PILOT_MODE_OPTIONS[0],
        "organisation_name": "",
        "reviewer_name": "",
        "reviewer_role": "Preparedness officer / responsible reviewer",
        "review_date": datetime.now().date(),
        "review_notes": "",
        "report_status": "Draft - human review required",
        "approval_reviewer_name": "",
        "approval_reviewer_role": "Preparedness officer / responsible reviewer",
        "approval_organisation_name": "",
        "approval_status": "Draft - human review required",
        "approval_review_date": datetime.now().date(),
        "approval_review_notes": "",
        "active_demo_scenario": "",
        "demo_generation_notice": "",
        "selected_map_area": None,
        "official_status_result": None,
        "external_model_acknowledged": False,
        "external_model_acknowledged_at": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_example_case(case_name):
    example = EXAMPLE_CASES[case_name]
    st.session_state.form_location = example["location"]
    st.session_state.form_audience = example["audience"]
    st.session_state.form_timeframe = example["timeframe"]
    st.session_state.form_scenario = example["scenario"]
    st.session_state.form_concerns = example["concerns"]
    st.session_state.form_extra_context = example["extra_context"]
    st.session_state.pilot_mode = example.get("pilot_mode", PILOT_MODE_OPTIONS[0])
    st.session_state.organisation_name = example.get("organisation_name", "")
    st.session_state.reviewer_name = example.get("reviewer_name", "")
    st.session_state.reviewer_role = example.get("reviewer_role", "Preparedness officer / responsible reviewer")
    st.session_state.approval_organisation_name = st.session_state.organisation_name
    st.session_state.approval_reviewer_name = st.session_state.reviewer_name
    st.session_state.approval_reviewer_role = st.session_state.reviewer_role
    map_selection = example.get("map_selection")
    if map_selection and is_area_selection_available(map_selection):
        apply_map_selection(map_selection)
    else:
        clear_map_selection()


def apply_map_selection(map_selection):
    st.session_state.selected_map_area = dict(map_selection)
    st.session_state.map_state = map_selection.get("state", "")
    st.session_state.map_level = map_selection.get("level", "SA4")
    st.session_state.map_area = map_selection.get("area_name", "")
    st.session_state.map_search = ""
    st.session_state.official_status_result = None


def clear_map_selection():
    st.session_state.selected_map_area = None
    st.session_state.map_state = ""
    st.session_state.map_level = "SA4"
    st.session_state.map_area = ""
    st.session_state.map_search = ""
    st.session_state.official_status_result = None


def load_demo_scenario(demo):
    load_example_case(demo["example_case"])
    st.session_state.active_demo_scenario = demo["title"]


def update_latest_report_signoff(review_record):
    return run_update_latest_report_signoff(review_record, is_welcome_message)


def generate_current_report():
    return run_generate_current_report(persist_session_state)


def revise_current_report(edit_request):
    return run_revise_current_report(edit_request, persist_session_state)


def display_feedback(message, index):
    increment = 0
    if message["role"] == "assistant":
        with st.expander("Copy response", expanded=False):
            st.caption("Use the browser-side copy button in the code block; nothing is copied to the server clipboard.")
            st.code(message["content"], language="markdown", wrap_lines=True)
        with st.expander("Response note", expanded=False):
            note = st.text_area(
                "Optional: record an issue or requested edit for this response", key=f"response_note_{index}", height=80
            )
            if note:
                message["note"] = note
        increment = 1
    return increment


def display_response(message, index=0):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        return display_feedback(message, index)


def render_conversation_history():
    index = 0
    with st.expander("Conversation History", expanded=False):
        for message in st.session_state.messages:
            index += display_response(message, index)


def render_workspace_tabs():
    st.markdown("### Mission Workspace")
    create_tab, review_tab, data_tab, demo_tab, readiness_tab = st.tabs(
        [
            "Create Report",
            "Review & Export",
            "Data & Map",
            "Demo Guide",
            "Readiness",
        ]
    )

    with create_tab:
        render_report_form(
            PILOT_MODE_OPTIONS,
            initialize_form_defaults,
            load_example_case,
            get_active_map_selection_label,
            generate_current_report,
        )
        render_latest_report_preview(
            get_latest_assistant_text,
            save_latest_report,
            verify_report_record_snapshot,
        )

    with review_tab:
        render_agent_analysis_summary(get_active_map_selection_label)
        render_report_quality_summary()
        render_human_review_checklist(
            HUMAN_REVIEW_CHECKLIST,
            verify_report_record_snapshot,
        )
        render_reviewer_approval(
            collect_review_record,
            update_latest_report_signoff,
            update_latest_audit_review,
            validate_review_record,
            persist_session_state,
        )
        render_pilot_export_package(get_latest_assistant_text, collect_review_record, get_package_context)
        render_conversation_history()

    with data_tab:
        render_coverage_analysis_tools(get_active_analysis_location())
        render_official_status_panel()
        render_official_sources()
        render_data_status()
        render_rag_status()
        render_data_register()
        render_licence_register()

    with demo_tab:
        render_demo_scenario_pack(load_demo_scenario, generate_current_report)
        render_presentation_mode()
        render_government_pilot_brief()
        render_usage_guide()

    with readiness_tab:
        render_maturity_assessment()


apply_theme()
initialize_state()
if st.session_state.get("pending_approval_reset"):
    st.session_state.approval_status = "Draft - human review required"
    st.session_state.approval_reviewer_name = ""
    st.session_state.approval_reviewer_role = ""
    st.session_state.approval_organisation_name = ""
    st.session_state.approval_review_date = datetime.now().date()
    st.session_state.approval_review_notes = ""
    for key in list(st.session_state.keys()):
        if str(key).startswith("review_check_"):
            st.session_state[key] = False
    st.session_state.pending_approval_reset = False
render_sidebar(
    clear_conversation,
    get_latest_assistant_text,
    save_latest_report,
    verify_report_record_snapshot,
)
render_header()
render_workspace_tabs()

if user_prompt := st.chat_input("Request a wording or content revision; change geography in the form"):
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Revising the governed report..."):
            full_response, error = revise_current_report(user_prompt)
        if error:
            st.warning(error)
            st.caption("No report version was created. Restore the model service or generate a report first.")
        else:
            st.markdown(full_response)
    if full_response:
        st.rerun()
