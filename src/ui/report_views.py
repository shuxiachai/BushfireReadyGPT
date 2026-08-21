from datetime import datetime, timezone

import streamlit as st

from src.app_catalog import CONCERN_OPTIONS, EXAMPLE_CASES, SCENARIO_OPTIONS, TIMEFRAME_OPTIONS
from src.config import (
    EXTERNAL_MODEL_ALLOWED,
    LLM_PROVIDER,
    MODEL_ENDPOINT_DISPLAY,
    MODEL_ENDPOINT_IS_LOCAL,
)
from src.docx_export import create_report_docx
from src.pdf_export import create_report_pdf


def render_model_privacy_boundary():
    if MODEL_ENDPOINT_IS_LOCAL:
        st.caption(
            f"Model boundary: `{LLM_PROVIDER}` at `{MODEL_ENDPOINT_DISPLAY}` is a local loopback endpoint; "
            "external-model acknowledgement is not required."
        )
        return

    with st.container(border=True):
        st.warning("External model privacy boundary")
        st.markdown("**Configured provider and endpoint**")
        st.code(f"provider={LLM_PROVIDER}\nendpoint={MODEL_ENDPOINT_DISPLAY}", language="text")
        st.markdown(
            "**Fields sent for generation:** location, audience, scenario, focus areas, timeframe, "
            "additional context, selected geography, deterministic analysis/evidence context, and any "
            "static official passages retrieved by the local RAG index.\n\n"
            "**Fields sent for revision:** the revision request and current report body, excluding the "
            "Human Review Sign-off. Organisation and reviewer identity fields are not sent."
        )
        st.warning(
            "The provider's logging, retention, training and deletion practices depend on the configured "
            "service and account. Do not enter sensitive personal or health information, private contact "
            "details, active-incident observations, or requests for real-time evacuation/life-safety action."
        )
        if not EXTERNAL_MODEL_ALLOWED:
            st.error(
                "External requests are disabled by default. The operator must set "
                "BUSHFIRE_ALLOW_EXTERNAL_MODEL=true before acknowledgement can be recorded."
            )
        acknowledged = st.checkbox(
            "I confirm this browser session may send only non-sensitive preparedness-planning data to the "
            "external provider, and I understand its retention policy depends on the configured account.",
            key="external_model_acknowledged",
            disabled=not EXTERNAL_MODEL_ALLOWED,
        )
        if acknowledged:
            if not st.session_state.get("external_model_acknowledged_at"):
                st.session_state.external_model_acknowledged_at = (
                    datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                )
        else:
            st.session_state.external_model_acknowledged_at = None


def render_report_form(
    pilot_mode_options,
    initialize_form_defaults,
    load_example_case,
    get_active_map_selection_label,
    generate_current_report,
):
    initialize_form_defaults()
    st.markdown("### Generate Preparedness Report")
    if st.session_state.get("persistence_warning"):
        st.warning(st.session_state.persistence_warning)
    if st.session_state.get("restored_governance_warning"):
        st.warning(st.session_state.restored_governance_warning)
    render_model_privacy_boundary()

    case_col, action_col = st.columns([2, 1])
    with case_col:
        selected_case = st.selectbox("Pilot example", list(EXAMPLE_CASES.keys()), key="selected_example_case")
    with action_col:
        st.markdown("<div style='height: 1.78rem;'></div>", unsafe_allow_html=True)
        if st.button("Load example", width="stretch"):
            load_example_case(selected_case)
            st.rerun()

    with st.form("report_form"):
        st.selectbox("Government Pilot Mode", pilot_mode_options, key="pilot_mode")
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Organisation / department", key="organisation_name")
            st.text_input("Location", key="form_location")
            st.text_input("Audience", key="form_audience")
            st.selectbox(
                "Timeframe",
                TIMEFRAME_OPTIONS,
                key="form_timeframe",
            )
        with col2:
            st.selectbox(
                "Scenario",
                SCENARIO_OPTIONS,
                key="form_scenario",
            )
            st.caption(
                "Every newly generated or revised report starts as a draft. Record review status in Review & Export."
            )
            st.multiselect(
                "Focus areas",
                CONCERN_OPTIONS,
                key="form_concerns",
            )
            st.text_input("Reviewer name", key="reviewer_name")
            st.text_input("Reviewer role", key="reviewer_role")

        map_label = get_active_map_selection_label()
        if map_label:
            st.info(f"This report will prioritise the selected map area: {map_label}")
        else:
            st.info("No map area is selected yet; the report will use the best available location match.")

        st.text_area(
            "Additional context",
            placeholder="Example: no confirmed evacuation plan; assembly points still need approval; use as a government pilot draft.",
            height=90,
            key="form_extra_context",
        )
        submitted = st.form_submit_button("Generate report", width="stretch")

    if submitted:
        with st.chat_message("assistant"):
            with st.spinner("Generating report..."):
                full_response, error = generate_current_report()
                if error:
                    st.warning(error)
                    return
                st.markdown(full_response)
        st.rerun()


def render_latest_report_preview(
    get_latest_assistant_text,
    save_latest_report,
    verify_report_record_snapshot,
):
    latest_report = get_latest_assistant_text()
    if not latest_report:
        return
    st.markdown("### Latest Report Preview")
    latest_record = st.session_state.get("latest_report") or {}
    version = latest_record.get("version", 1)
    report_id = latest_record.get("id", "legacy")
    st.caption(
        f"Governed report version {version} | ID {report_id}. Downloads, quality checks and audit records use this exact content."
    )
    if not verify_report_record_snapshot(latest_record):
        st.warning(
            "This report is an unverified legacy or integrity-blocked snapshot. "
            "Regenerate it before saving, revising, reviewing or downloading governed artifacts."
        )
        with st.container(border=True):
            st.markdown(latest_report)
        return
    action_cols = st.columns(4)
    with action_cols[0]:
        st.download_button(
            "Download Markdown",
            data=latest_report,
            file_name="bushfire_ready_report.md",
            mime="text/markdown",
            width="stretch",
            on_click="ignore",
        )
    with action_cols[1]:
        try:
            pdf_bytes = create_report_pdf(latest_report)
            st.download_button(
                "Download PDF",
                data=pdf_bytes,
                file_name="bushfire_ready_report.pdf",
                mime="application/pdf",
                width="stretch",
                on_click="ignore",
            )
        except Exception as exc:
            st.warning(f"PDF generation failed: {exc}")
    with action_cols[2]:
        try:
            docx_bytes = create_report_docx(latest_report)
            st.download_button(
                "Download DOCX",
                data=docx_bytes,
                file_name="bushfire_ready_report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                on_click="ignore",
            )
        except Exception as exc:
            st.warning(f"DOCX generation failed: {exc}")
    with action_cols[3]:
        if st.button("Save to chat_history", width="stretch"):
            try:
                saved_path = save_latest_report()
            except OSError as exc:
                st.warning(f"The report could not be saved locally: {exc}")
            else:
                if saved_path:
                    st.success(f"Saved: {saved_path}")
    with st.container(border=True):
        st.markdown(latest_report)
