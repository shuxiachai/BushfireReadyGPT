import streamlit as st

from src.app_catalog import CONCERN_OPTIONS, EXAMPLE_CASES, SCENARIO_OPTIONS, TIMEFRAME_OPTIONS
from src.docx_export import create_report_docx
from src.export_package import create_pilot_export_package
from src.pdf_export import create_report_pdf


def render_report_form(
    pilot_mode_options,
    initialize_form_defaults,
    load_example_case,
    get_active_map_selection_label,
    generate_current_report,
):
    initialize_form_defaults()
    st.markdown("### Generate Preparedness Report")

    case_col, action_col = st.columns([2, 1])
    with case_col:
        selected_case = st.selectbox("Pilot example", list(EXAMPLE_CASES.keys()), key="selected_example_case")
    with action_col:
        st.markdown("<div style='height: 1.78rem;'></div>", unsafe_allow_html=True)
        if st.button("Load example", use_container_width=True):
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
            st.selectbox(
                "Report status",
                ["Draft - human review required", "Reviewed draft", "Approved by organisation"],
                key="report_status",
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
        submitted = st.form_submit_button("Generate report", use_container_width=True)

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
    collect_review_record,
    get_package_context,
):
    latest_report = get_latest_assistant_text()
    if not latest_report:
        return
    st.markdown("### Latest Report Preview")
    st.caption("This shows the most recent generated or edited report. Downloads and save actions use this content.")
    action_cols = st.columns(5)
    with action_cols[0]:
        st.download_button(
            "Download Markdown",
            data="# BushfireReadyGPT Report\n\n" + latest_report,
            file_name="bushfire_ready_report.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with action_cols[1]:
        try:
            pdf_bytes = create_report_pdf(latest_report)
            st.download_button(
                "Download PDF",
                data=pdf_bytes,
                file_name="bushfire_ready_report.pdf",
                mime="application/pdf",
                use_container_width=True,
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
                use_container_width=True,
            )
        except Exception as exc:
            st.warning(f"DOCX generation failed: {exc}")
    with action_cols[3]:
        if st.button("Save to chat_history", use_container_width=True):
            saved_path = save_latest_report()
            if saved_path:
                st.success(f"Saved: {saved_path}")
    with action_cols[4]:
        try:
            package = create_pilot_export_package(
                latest_report,
                audit_path=st.session_state.get("latest_audit_path"),
                review_record=st.session_state.get("latest_review_record") or collect_review_record(),
                package_context=get_package_context(),
            )
            st.download_button(
                "Download Pilot Package",
                data=package["content"],
                file_name=package["filename"],
                mime="application/zip",
                use_container_width=True,
            )
        except Exception as exc:
            st.warning(f"Pilot package generation failed: {exc}")
    with st.container(border=True):
        st.markdown(latest_report)
