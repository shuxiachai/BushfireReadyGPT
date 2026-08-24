import streamlit as st

from src.docx_export import create_report_docx
from src.pdf_export import create_report_pdf
from src.report_generation_quality import evaluate_governed_report
from src.ui.artifact_cache import get_report_artifact


def render_sidebar(
    clear_conversation,
    get_latest_assistant_text,
    save_latest_report,
    verify_report_record_snapshot,
):
    st.sidebar.markdown("## BushfireReady Planner")
    st.sidebar.markdown(
        "Bushfire preparedness planning assistant for Australian government pilots, schools and communities."
    )
    st.sidebar.caption("Government pilot mode: draft reports, evidence trail, data register, human review.")
    st.sidebar.markdown("### Actions")
    st.sidebar.caption(
        "Clear removes the current in-app session and optional session files. "
        "Audit records, manually saved reports and downloaded exports remain on disk."
    )
    if st.sidebar.button("Clear current conversation", width="stretch"):
        clear_conversation()
    latest_report = get_latest_assistant_text()
    if latest_report:
        report_record = st.session_state.get("latest_report") or {}
        if not verify_report_record_snapshot(report_record):
            st.sidebar.warning(
                "The restored report is unverified or not the current audit head. "
                "Regenerate it to enable governed downloads."
            )
            st.sidebar.markdown("### Safety Boundary")
            st.sidebar.caption(
                "This app does not provide live fire conditions, fire bans, evacuation orders or life-safety decisions. "
                "In a real emergency, follow official emergency services and call 000 if life is at risk."
            )
            return
        exact_quality = evaluate_governed_report(latest_report, report_record.get("analysis") or {})
        if (
            exact_quality != report_record.get("quality")
            or exact_quality.get("approval_gate", {}).get("passed") is not True
        ):
            st.sidebar.warning(
                "This report is a quality-blocked draft. Downloads remain available for human remediation, "
                "but the report cannot be approved or packaged as a governed Pilot ZIP."
            )
        st.sidebar.download_button(
            "Download latest report",
            data=latest_report,
            file_name="bushfire_ready_report.md",
            mime="text/markdown",
            width="stretch",
            on_click="ignore",
        )
        try:
            pdf_bytes = get_report_artifact(latest_report, "pdf", create_report_pdf)
            st.sidebar.download_button(
                "Download PDF report",
                data=pdf_bytes,
                file_name="bushfire_ready_report.pdf",
                mime="application/pdf",
                width="stretch",
                on_click="ignore",
            )
        except Exception as exc:
            st.sidebar.warning(f"PDF generation failed: {exc}")
        try:
            docx_bytes = get_report_artifact(latest_report, "docx", create_report_docx)
            st.sidebar.download_button(
                "Download DOCX report",
                data=docx_bytes,
                file_name="bushfire_ready_report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                on_click="ignore",
            )
        except Exception as exc:
            st.sidebar.warning(f"DOCX generation failed: {exc}")
        if st.sidebar.button("Save to chat_history", width="stretch"):
            try:
                saved_path = save_latest_report()
            except OSError as exc:
                st.sidebar.warning(f"The report could not be saved locally: {exc}")
            else:
                if saved_path:
                    st.sidebar.success(f"Saved: {saved_path}")
    st.sidebar.markdown("### Safety Boundary")
    st.sidebar.caption(
        "This app does not provide live fire conditions, fire bans, evacuation orders or life-safety decisions. "
        "In a real emergency, follow official emergency services and call 000 if life is at risk."
    )
