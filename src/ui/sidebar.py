import streamlit as st

from src.docx_export import create_report_docx
from src.export_package import create_pilot_export_package
from src.pdf_export import create_report_pdf


def render_sidebar(
    clear_conversation,
    get_latest_assistant_text,
    collect_review_record,
    get_package_context,
    save_latest_report,
):
    st.sidebar.markdown("## BushfireReady Planner")
    st.sidebar.markdown("Bushfire preparedness planning assistant for Australian government pilots, schools and communities.")
    st.sidebar.caption("Government pilot mode: draft reports, evidence trail, data register, human review.")
    st.sidebar.markdown("### Actions")
    if st.sidebar.button("Clear current conversation", use_container_width=True):
        clear_conversation()
    latest_report = get_latest_assistant_text()
    if latest_report:
        st.sidebar.download_button(
            "Download latest report",
            data="# BushfireReadyGPT Report\n\n" + latest_report,
            file_name="bushfire_ready_report.md",
            mime="text/markdown",
            use_container_width=True,
        )
        try:
            pdf_bytes = create_report_pdf(latest_report)
            st.sidebar.download_button(
                "Download PDF report",
                data=pdf_bytes,
                file_name="bushfire_ready_report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as exc:
            st.sidebar.warning(f"PDF generation failed: {exc}")
        try:
            docx_bytes = create_report_docx(latest_report)
            st.sidebar.download_button(
                "Download DOCX report",
                data=docx_bytes,
                file_name="bushfire_ready_report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        except Exception as exc:
            st.sidebar.warning(f"DOCX generation failed: {exc}")
        try:
            package = create_pilot_export_package(
                latest_report,
                audit_path=st.session_state.get("latest_audit_path"),
                review_record=st.session_state.get("latest_review_record") or collect_review_record(),
                package_context=get_package_context(),
            )
            st.sidebar.download_button(
                "Download pilot package",
                data=package["content"],
                file_name=package["filename"],
                mime="application/zip",
                use_container_width=True,
            )
        except Exception as exc:
            st.sidebar.warning(f"Pilot package generation failed: {exc}")
        if st.sidebar.button("Save to chat_history", use_container_width=True):
            saved_path = save_latest_report()
            if saved_path:
                st.sidebar.success(f"Saved: {saved_path}")
    st.sidebar.markdown("### Safety Boundary")
    st.sidebar.caption(
        "This app does not provide live fire conditions, fire bans, evacuation orders or life-safety decisions. "
        "In a real emergency, follow official emergency services and call 000 if life is at risk."
    )
