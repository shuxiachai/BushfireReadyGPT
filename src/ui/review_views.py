from html import escape
import os

import streamlit as st

from src.export_package import create_pilot_export_package
from src.ui.components import render_path_line, safe_display_text


def render_agent_analysis_summary(get_active_map_selection_label):
    analysis = st.session_state.get("latest_analysis")
    if not analysis:
        return

    profile = analysis.get("profile", {})
    data_result = analysis.get("data", {})
    community_result = analysis.get("community", {})
    risk_context = analysis.get("risk_context", {})
    plan_result = analysis.get("plan", {})

    with st.expander("Evidence Trail", expanded=False):
        overview_cols = st.columns(4)
        community_indicators = community_result.get("indicators", {})
        data_source_note = safe_display_text(community_result.get("data_source_note"), "")
        overview_items = [
            ("Matched area", safe_display_text(community_result.get("matched_location"), "Not matched")),
            ("Population", safe_display_text(community_indicators.get("population"))),
            ("Matched SA2 count", safe_display_text(community_indicators.get("matched_sa2_count"))),
            ("Data source", "ABS processed" if "processed" in data_source_note else "sample/other"),
        ]
        for col, (label, value) in zip(overview_cols, overview_items):
            col.markdown(
                f"""
                <div class="status-card">
                    <div class="status-label">{escape(safe_display_text(label))}</div>
                    <div class="status-value">{escape(safe_display_text(value))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        map_selection_label = get_active_map_selection_label()
        if map_selection_label:
            st.caption(f"Map selection used for this report: {map_selection_label}")

        st.markdown("#### User Inputs / Location Profile")
        st.markdown(
            f"""
            - **Location:** {profile.get("location", "Not identified")}
            - **State / territory inference:** {profile.get("state", "Not identified")}
            - **Scenario type:** {profile.get("setting_type", "Not identified")}
            - **Audience:** {profile.get("audience", "Not provided")}
            - **Timeframe:** {profile.get("timeframe", "Not provided")}
            """
        )

        st.markdown("#### Official Source Selection")
        for source in data_result.get("sources", []):
            st.markdown(f"- **{source.get('name')}**: {source.get('purpose')}")
        if not data_result.get("sources"):
            st.markdown("- No specific official sources were matched.")

        st.markdown("#### Community Data Evidence")
        matched_location = community_result.get("matched_location")
        if matched_location:
            indicators = community_result.get("indicators", {})
            st.markdown(f"- **Matched community:** {matched_location}")
            st.markdown(f"- **Population:** {indicators.get('population')}")
            st.markdown(f"- **Older people percentage:** {indicators.get('older_people_pct')}%")
            st.markdown(f"- **No-car household percentage:** {indicators.get('no_car_households_pct')}%")
            st.markdown(f"- **Language support need:** {indicators.get('language_support_needed')}")
            if indicators.get("language_other_than_english_pct"):
                st.markdown(f"- **Language other than English at home:** {indicators.get('language_other_than_english_pct')}%")
            if indicators.get("geography_type"):
                st.markdown(f"- **Geography mapping type:** {indicators.get('geography_type')}")
            if indicators.get("matched_sa2_count"):
                st.markdown(f"- **Matched SA2 count:** {indicators.get('matched_sa2_count')}")
        else:
            st.markdown("- No local community profile data was matched.")
        for note in community_result.get("vulnerability_notes", []):
            st.markdown(f"- {note}")

        geography_reference = community_result.get("geography_reference", {})
        if geography_reference:
            st.markdown("#### ABS ASGS Geography Reference")
            selected_area = geography_reference.get("selected_asgs_area")
            if selected_area:
                st.markdown(
                    f"""
                    - **Selected ASGS area:** {selected_area.get("selected_level")} {selected_area.get("selected_area")}
                    - **State / territory:** {selected_area.get("state_name")}
                    - **SA2 rows in selected area:** {selected_area.get("sa2_count")}
                    - **SA3 reference:** {selected_area.get("sa3_names")}
                    - **SA4 reference:** {selected_area.get("sa4_names")}
                    - **GCCSA reference:** {selected_area.get("gccsa_names")}
                    - **Albers area:** {selected_area.get("area_albers_sqkm")} sq km
                    - **Source file:** {selected_area.get("source_file")}
                    """
                )
            lga_candidates = geography_reference.get("lga_candidates", [])
            if lga_candidates:
                st.markdown("**LGA 2025 candidate reference areas**")
                st.table(
                    [
                        {
                            "lga_code_2025": item.get("lga_code_2025", ""),
                            "lga_name_2025": item.get("lga_name_2025", ""),
                            "state": item.get("state_name_2021", ""),
                            "mesh_blocks": item.get("mesh_block_count", ""),
                            "area_sqkm": item.get("area_albers_sqkm", ""),
                        }
                        for item in lga_candidates
                    ]
                )
            if geography_reference.get("source_note"):
                st.markdown(f"- {geography_reference['source_note']}")
            for limitation in geography_reference.get("limitations", []):
                st.markdown(f"- {limitation}")

        st.markdown("#### Risk Factors")
        matched_rule_ids = risk_context.get("matched_rule_ids", [])
        st.markdown(f"- **Matched rules:** {', '.join(matched_rule_ids) if matched_rule_ids else 'No local rules matched'}")
        for point in risk_context.get("risk_points", []):
            st.markdown(f"- {point}")

        st.markdown("#### Planning Priorities")
        for priority in plan_result.get("planning_priorities", []):
            st.markdown(f"- {priority}")

        st.markdown("#### Data Limitations and Assumptions")
        for limitation in data_result.get("data_limitations", []):
            st.markdown(f"- {limitation}")
        if community_result.get("data_source_note"):
            st.markdown(f"- {community_result['data_source_note']}")
        for assumption in risk_context.get("assumptions", []):
            st.markdown(f"- {assumption}")


def render_report_quality_summary():
    quality = st.session_state.get("latest_quality")
    if not quality:
        return

    summary = quality.get("summary", {})
    with st.expander("Report Quality Check", expanded=False):
        st.markdown(
            f"**Passed:** {summary.get('passed', 0)} / {summary.get('total', 0)}  "
            f"**Warnings:** {summary.get('warnings', 0)}  "
            f"**Needs fix:** {summary.get('failed', 0)}"
        )
        for check in quality.get("checks", []):
            status = check.get("status")
            marker = "OK" if status == "pass" else "Warning" if status == "warning" else "Fix"
            st.markdown(f"{marker}: **{check.get('name')}**: {check.get('detail')}")


def render_human_review_checklist(review_checklist):
    st.markdown("### Human Review Checklist")
    st.markdown(
        """
        <div class="source-note">
            In a government or organisational pilot, AI output should be treated as a draft.
            This checklist helps reviewers confirm data, official sources, safety boundaries
            and approval status before any formal use.
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("View human review checklist", expanded=False):
        st.markdown(f"**Current report status:** {st.session_state.get('report_status', 'Draft - human review required')}")
        st.markdown(f"**Reviewer name:** {st.session_state.get('reviewer_name') or 'Not specified'}")
        st.markdown(f"**Reviewer role:** {st.session_state.get('reviewer_role', 'Not specified')}")
        st.markdown(f"**Review date:** {st.session_state.get('review_date', 'Not specified')}")
        if st.session_state.get("latest_review_record"):
            st.markdown("**Latest sign-off record**")
            st.json(st.session_state.latest_review_record)
        if st.session_state.get("latest_audit_path"):
            render_path_line("Latest audit record", st.session_state.latest_audit_path)
            try:
                audit_bytes = open(st.session_state.latest_audit_path, "rb").read()
                st.download_button(
                    "Download audit JSON",
                    data=audit_bytes,
                    file_name=os.path.basename(st.session_state.latest_audit_path),
                    mime="application/json",
                    use_container_width=True,
                )
            except OSError:
                st.warning("The latest audit file could not be found on disk.")
        for index, item in enumerate(review_checklist):
            st.checkbox(item, key=f"review_check_{index}")


def render_reviewer_approval(
    collect_review_record,
    update_latest_report_signoff,
    update_latest_audit_review,
    persist_session_state,
):
    if st.session_state.get("organisation_name") and not st.session_state.get("approval_organisation_name"):
        st.session_state.approval_organisation_name = st.session_state.organisation_name
    if st.session_state.get("reviewer_name") and not st.session_state.get("approval_reviewer_name"):
        st.session_state.approval_reviewer_name = st.session_state.reviewer_name
    if st.session_state.get("reviewer_role") and not st.session_state.get("approval_reviewer_role"):
        st.session_state.approval_reviewer_role = st.session_state.reviewer_role
    if st.session_state.get("report_status") and not st.session_state.get("approval_status"):
        st.session_state.approval_status = st.session_state.report_status

    st.markdown("### Reviewer Approval / Human Sign-off")
    st.markdown(
        """
        <div class="source-note">
            Use this after generating a report to record who reviewed it and whether it remains
            a draft, needs revision, or has been approved by the responsible organisation.
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("reviewer_approval_form"):
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Reviewer name", key="approval_reviewer_name")
            st.text_input("Reviewer role / title", key="approval_reviewer_role")
            st.text_input("Organisation / department", key="approval_organisation_name")
        with col2:
            st.selectbox(
                "Approval status",
                [
                    "Draft - human review required",
                    "Needs revision",
                    "Reviewed draft",
                    "Approved by organisation",
                ],
                key="approval_status",
            )
            st.date_input("Review date", key="approval_review_date")
        st.text_area("Review notes", key="approval_review_notes", height=90)
        submitted = st.form_submit_button("Update sign-off record", use_container_width=True)

    if submitted:
        st.session_state.reviewer_name = st.session_state.get("approval_reviewer_name", "")
        st.session_state.reviewer_role = st.session_state.get("approval_reviewer_role", "")
        st.session_state.organisation_name = st.session_state.get("approval_organisation_name", "")
        st.session_state.report_status = st.session_state.get("approval_status", "Draft - human review required")
        st.session_state.review_date = st.session_state.get("approval_review_date", "")
        st.session_state.review_notes = st.session_state.get("approval_review_notes", "")
        review_record = collect_review_record()
        st.session_state.latest_review_record = review_record
        report_updated = update_latest_report_signoff(review_record)
        audit_updated = update_latest_audit_review(review_record)
        persist_session_state()
        if report_updated:
            st.success("Sign-off section updated in the latest report.")
        else:
            st.info("Sign-off record saved. Generate a report to attach it to report exports.")
        if audit_updated:
            st.success("Latest audit JSON updated.")
        elif st.session_state.get("latest_audit_path"):
            st.warning("The latest audit JSON could not be updated.")


def render_pilot_export_package(get_latest_assistant_text, collect_review_record, get_package_context):
    latest_report = get_latest_assistant_text()
    st.markdown("### Pilot Export Package")
    st.markdown(
        """
        <div class="source-note">
            Download one review package containing the latest report, PDF, DOCX, audit record,
            data register, reviewer sign-off and package manifest for stakeholder handover.
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not latest_report:
        st.info("Generate a report first, then the pilot export package will become available.")
        return
    try:
        package = create_pilot_export_package(
            latest_report,
            audit_path=st.session_state.get("latest_audit_path"),
            review_record=st.session_state.get("latest_review_record") or collect_review_record(),
            package_context=get_package_context(),
        )
        st.download_button(
            "Download pilot export package",
            data=package["content"],
            file_name=package["filename"],
            mime="application/zip",
            use_container_width=True,
        )
        with st.expander("View package manifest", expanded=False):
            st.json(package["manifest"])
    except Exception as exc:
        st.warning(f"Pilot package generation failed: {exc}")
