from pathlib import Path

import streamlit as st

from src.deployment_access import is_cloud_deployment
from src.report_generation_quality import evaluate_governed_report
from src.ui.artifact_cache import get_governed_report_artifacts
from src.ui.components import safe_diagnostic_detail
from src.ui.downloads import download_button


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
        grounding = report_record.get("grounding_evaluation") or {}
        visible_grounding = grounding.get("model_visible_rag") if isinstance(grounding, dict) else None
        model_evidence = visible_grounding.get("snapshot") if isinstance(visible_grounding, dict) else None
        exact_quality = evaluate_governed_report(
            latest_report, report_record.get("analysis") or {}, model_evidence=model_evidence
        )
        if (
            exact_quality != report_record.get("quality")
            or exact_quality.get("approval_gate", {}).get("passed") is not True
        ):
            st.sidebar.warning(
                "This report is a quality-blocked draft. Downloads remain available for human remediation, "
                "but the report cannot be approved or packaged as a governed Pilot ZIP."
            )
        download_button(
            "Download latest report",
            data=latest_report,
            file_name="bushfire_ready_report.md",
            mime="text/markdown",
            width="stretch",
            on_click="ignore",
            target=st.sidebar,
        )
        try:
            pdf_bytes = get_governed_report_artifacts(latest_report, audit_path=report_record.get("audit_path"))["pdf"]
            download_button(
                "Download PDF report",
                data=pdf_bytes,
                file_name="bushfire_ready_report.pdf",
                mime="application/pdf",
                width="stretch",
                on_click="ignore",
                target=st.sidebar,
            )
        except Exception as exc:
            st.sidebar.warning(f"PDF generation failed: {safe_diagnostic_detail(exc)}")
        try:
            docx_bytes = get_governed_report_artifacts(latest_report, audit_path=report_record.get("audit_path"))[
                "docx"
            ]
            download_button(
                "Download DOCX report",
                data=docx_bytes,
                file_name="bushfire_ready_report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
                on_click="ignore",
                target=st.sidebar,
            )
        except Exception as exc:
            st.sidebar.warning(f"DOCX generation failed: {safe_diagnostic_detail(exc)}")
        save_label = "Save report on server" if is_cloud_deployment() else "Save to chat_history"
        if st.sidebar.button(save_label, width="stretch"):
            try:
                saved_path = save_latest_report()
            except OSError as exc:
                st.sidebar.warning(f"The report could not be saved: {safe_diagnostic_detail(exc)}")
            else:
                if saved_path:
                    display_path = Path(saved_path).name if is_cloud_deployment() else saved_path
                    if is_cloud_deployment():
                        st.sidebar.success(
                            f"Saved Markdown on server: {display_path}. "
                            "This does not restore your browser session or review/sign-off workspace. "
                            "Audit records are retained separately. Download your exports before closing this session."
                        )
                    else:
                        st.sidebar.success(f"Saved: {display_path}")
    st.sidebar.markdown("### Safety Boundary")
    st.sidebar.caption(
        "This app does not provide live fire conditions, fire bans, evacuation orders or life-safety decisions. "
        "In a real emergency, follow official emergency services and call 000 if life is at risk."
    )
