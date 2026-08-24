import os
from html import escape

import streamlit as st

from src.audit import AuditIntegrityError, capture_current_audit_chain
from src.evidence_confidence import build_evidence_confidence_rows
from src.export_package import create_pilot_export_package
from src.ui.components import render_path_line, safe_display_text


def render_agent_analysis_summary(get_active_map_selection_label):
    analysis = st.session_state.get("latest_analysis")
    if not analysis:
        return

    with st.expander("Evidence Trail", expanded=True):
        _render_evidence_overview(analysis.get("community", {}), get_active_map_selection_label)
        _render_confidence_provenance(analysis)
        _render_profile_and_sources(analysis.get("profile", {}), analysis.get("data", {}))
        _render_retrieved_knowledge(analysis.get("knowledge", {}))
        _render_community_evidence(analysis.get("community", {}))
        _render_geography_reference(analysis.get("community", {}).get("geography_reference", {}))
        _render_planning_evidence(
            analysis.get("data", {}),
            analysis.get("community", {}),
            analysis.get("knowledge", {}),
            analysis.get("risk_context", {}),
            analysis.get("plan", {}),
        )


def _render_evidence_overview(community_result, get_active_map_selection_label):
    community_indicators = community_result.get("indicators", {})
    data_quality = community_result.get("data_quality", {})
    overview_items = [
        ("Matched area", safe_display_text(community_result.get("matched_location"), "Not matched")),
        ("Population", safe_display_text(community_indicators.get("population"))),
        ("Data freshness", safe_display_text(data_quality.get("freshness"), "Not assessed")),
        ("Match quality", safe_display_text(data_quality.get("match_quality"), "Not assessed")),
    ]
    for col, (label, value) in zip(st.columns(4), overview_items):
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


def _render_confidence_provenance(analysis):
    st.markdown("#### Evidence Confidence and Provenance")
    st.caption(
        "These codes classify provenance and review needs. They are not live incident severity or fire danger ratings."
    )
    confidence_rows = analysis.get("evidence_confidence") or build_evidence_confidence_rows(analysis)
    st.dataframe(
        [
            {
                "code": row.get("code", ""),
                "evidence_class": row.get("evidence_class", ""),
                "current_use": row.get("current_use", ""),
                "confidence_boundary": row.get("confidence_boundary", ""),
                "required_review": row.get("required_review", ""),
            }
            for row in confidence_rows
        ],
        width="stretch",
        hide_index=True,
    )


def _render_profile_and_sources(profile, data_result):
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
    sources = data_result.get("sources", [])
    for source in sources:
        st.markdown(f"- **{source.get('name')}**: {source.get('purpose')}")
    if not sources:
        st.markdown("- No specific official sources were matched.")


def _render_retrieved_knowledge(knowledge_result):
    st.markdown("#### Retrieved Official Knowledge (RAG)")
    fields = [
        ("Status", knowledge_result.get("status_label") or "Not configured"),
        ("Embedding model", knowledge_result.get("embedding_model") or "Not available"),
        ("Retrieval mode", knowledge_result.get("retrieval_mode") or "Not available"),
        ("Index manifest", knowledge_result.get("index_manifest_sha256") or "Not available"),
    ]
    for label, value in fields:
        st.markdown(f"- **{label}:** {value}")
    retrieved_chunks = knowledge_result.get("retrieved_chunks", [])
    if not retrieved_chunks:
        st.markdown("- No verified RAG passage was supplied to the report model.")
        return
    st.caption("Similarity supports retrieval ranking only. Review the current official page before use.")
    st.dataframe([_retrieved_chunk_row(chunk) for chunk in retrieved_chunks], width="stretch", hide_index=True)


def _retrieved_chunk_row(chunk):
    return {
        "source": chunk.get("title", ""),
        "agency": chunk.get("agency", ""),
        "page": chunk.get("page") or "web",
        "hybrid_score": chunk.get("score", ""),
        "dense_score": chunk.get("dense_score", ""),
        "dense_rank": chunk.get("dense_rank", ""),
        "bm25_score": chunk.get("lexical_score", ""),
        "bm25_rank": chunk.get("lexical_rank", ""),
        "rerank_reasons": ", ".join(chunk.get("rerank_reasons", [])),
        "document_date": chunk.get("document_date", ""),
        "chunk_sha256": chunk.get("chunk_sha256", ""),
        "url": chunk.get("url", ""),
        "excerpt": str(chunk.get("text") or "")[:500],
    }


def _render_community_evidence(community_result):
    st.markdown("#### Community Data Evidence")
    matched_location = community_result.get("matched_location")
    if not matched_location:
        st.markdown("- No local community profile data was matched.")
    else:
        indicators = community_result.get("indicators", {})
        rows = [
            ("Matched community", matched_location),
            ("Population", indicators.get("population")),
            ("Older people percentage", f"{indicators.get('older_people_pct')}%"),
            ("No-car household percentage", f"{indicators.get('no_car_households_pct')}%"),
            ("Language support need", indicators.get("language_support_needed")),
        ]
        optional_rows = [
            ("Language other than English at home", "language_other_than_english_pct", "%"),
            ("Geography mapping type", "geography_type", ""),
            ("Matched SA2 count", "matched_sa2_count", ""),
        ]
        rows.extend(
            (label, f"{indicators[key]}{suffix}") for label, key, suffix in optional_rows if indicators.get(key)
        )
        for label, value in rows:
            st.markdown(f"- **{label}:** {value}")
    for note in community_result.get("vulnerability_notes", []):
        st.markdown(f"- {note}")
    _render_community_data_quality(community_result.get("data_quality", {}))


def _render_community_data_quality(data_quality):
    st.markdown("#### Data Currency and Geographic Match")
    if not data_quality:
        st.warning("No structured data-quality assessment was recorded. Verify source age and geography manually.")
        return
    source_age = data_quality.get("source_age_years")
    fields = [
        ("Source period", data_quality.get("source_period")),
        ("Latest source year", data_quality.get("latest_source_year")),
        ("Source age at analysis", f"{source_age} year(s)" if source_age is not None else "Not available"),
        ("Freshness", data_quality.get("freshness")),
        ("Match quality", data_quality.get("match_quality")),
        ("Match method", data_quality.get("match_method")),
        ("Match basis", data_quality.get("match_basis")),
    ]
    for label, value in fields:
        st.markdown(f"- **{label}:** {safe_display_text(value)}")
    for warning in data_quality.get("warnings", []):
        st.warning(safe_display_text(warning))


def _render_geography_reference(geography_reference):
    if not geography_reference:
        return
    st.markdown("#### ABS ASGS Geography Reference")
    selected_area = geography_reference.get("selected_asgs_area")
    if selected_area:
        labels = [
            ("Selected ASGS area", f"{selected_area.get('selected_level')} {selected_area.get('selected_area')}"),
            ("State / territory", selected_area.get("state_name")),
            ("SA2 rows in selected area", selected_area.get("sa2_count")),
            ("SA3 reference", selected_area.get("sa3_names")),
            ("SA4 reference", selected_area.get("sa4_names")),
            ("GCCSA reference", selected_area.get("gccsa_names")),
            ("Albers area", f"{selected_area.get('area_albers_sqkm')} sq km"),
            ("Source file", selected_area.get("source_file")),
        ]
        for label, value in labels:
            st.markdown(f"- **{label}:** {value}")
    lga_candidates = geography_reference.get("lga_candidates", [])
    if lga_candidates:
        st.markdown("**LGA 2025 candidate reference areas**")
        st.table([_lga_candidate_row(item) for item in lga_candidates])
    if geography_reference.get("source_note"):
        st.markdown(f"- {geography_reference['source_note']}")
    for limitation in geography_reference.get("limitations", []):
        st.markdown(f"- {limitation}")


def _lga_candidate_row(item):
    return {
        "lga_code_2025": item.get("lga_code_2025", ""),
        "lga_name_2025": item.get("lga_name_2025", ""),
        "state": item.get("state_name_2021", ""),
        "mesh_blocks": item.get("mesh_block_count", ""),
        "area_sqkm": item.get("area_albers_sqkm", ""),
    }


def _render_planning_evidence(data_result, community_result, knowledge_result, risk_context, plan_result):
    st.markdown("#### Risk Factors")
    matched_rule_ids = risk_context.get("matched_rule_ids", [])
    matched_rules = ", ".join(matched_rule_ids) if matched_rule_ids else "No local rules matched"
    st.markdown(f"- **Matched rules:** {matched_rules}")
    for point in risk_context.get("risk_points", []):
        st.markdown(f"- {point}")
    st.markdown("#### Planning Priorities")
    for priority in plan_result.get("planning_priorities", []):
        st.markdown(f"- {priority}")
    st.markdown("#### Data Limitations and Assumptions")
    limitations = list(data_result.get("data_limitations", []))
    if community_result.get("data_source_note"):
        limitations.append(community_result["data_source_note"])
    limitations.extend((community_result.get("data_quality") or {}).get("warnings", []))
    limitations.extend(risk_context.get("assumptions", []))
    limitations.extend(knowledge_result.get("limitations", []))
    for limitation in limitations:
        st.markdown(f"- {limitation}")


def render_report_quality_summary():
    quality = st.session_state.get("latest_quality")
    if not quality:
        return

    summary = quality.get("summary", {})
    with st.expander("Governed Report Check", expanded=False):
        st.caption(
            quality.get("assessment_scope", "Structural checks do not establish factual or operational accuracy.")
        )
        st.markdown(
            f"**Passed:** {summary.get('passed', 0)} / {summary.get('total', 0)}  "
            f"**Warnings:** {summary.get('warnings', 0)}  "
            f"**Needs fix:** {summary.get('failed', 0)}"
        )
        approval_gate = quality.get("approval_gate", {})
        if approval_gate.get("passed") is True:
            st.success("Governed quality gate passed. Human review is still required.")
        else:
            st.error("Approval is blocked until every governed quality failure is resolved.")
        for check in quality.get("checks", []):
            status = check.get("status")
            marker = "OK" if status == "pass" else "Warning" if status == "warning" else "Fix"
            st.markdown(f"{marker}: **{check.get('name')}**: {check.get('detail')}")

    grounding = (st.session_state.get("latest_report") or {}).get("grounding_evaluation")
    if not isinstance(grounding, dict):
        return
    metrics = grounding.get("metrics", {})
    with st.expander("Evidence Alignment Review (heuristic)", expanded=False):
        st.caption(
            "This deterministic check compares attributable narrative claims with the frozen analysis and "
            "retrieved passages. It does not prove factual truth or source currency."
        )
        if grounding.get("status") == "pass":
            st.success("Configured evidence-alignment thresholds passed. Human source verification is still required.")
        elif grounding.get("status") == "not_applicable":
            st.info("No externally attributable narrative claim was selected by the deterministic extractor.")
        else:
            st.warning("One or more claims need human evidence review; report generation was not blocked.")
        st.markdown(
            f"**Claims checked:** {metrics.get('claims_evaluated', 0)}  "
            f"**Support rate:** {_format_metric_rate(metrics.get('support_rate'))}  "
            f"**Citation coverage:** {_format_metric_rate(metrics.get('citation_coverage_rate'))}  "
            f"**Numeric consistency:** {_format_metric_rate(metrics.get('numeric_consistency_rate'))}  "
            f"**Jurisdiction conflicts:** {metrics.get('jurisdiction_conflicts', 0)}"
        )
        flagged = [claim for claim in grounding.get("claims", []) if claim.get("supported") is not True]
        if flagged:
            st.markdown("**Claims requiring review**")
            for claim in flagged[:10]:
                reasons = []
                if claim.get("numeric_consistent") is False:
                    reasons.append("number not found in frozen evidence")
                if claim.get("jurisdiction_conflicts"):
                    reasons.append("jurisdiction conflict")
                if not claim.get("cited_source_ids"):
                    reasons.append("no recognised source attribution")
                if not reasons:
                    reasons.append("insufficient lexical evidence alignment")
                st.markdown(f"- `{claim.get('claim_id')}` — {claim.get('claim')} ({'; '.join(reasons)})")


def _format_metric_rate(value):
    return "N/A" if value is None else f"{float(value) * 100:.1f}%"


def render_human_review_checklist(review_checklist, verify_report_record_snapshot):
    st.markdown("### Human Review Checklist")
    st.markdown(
        """
        <div class="source-note">
            In a government or organisational pilot, AI output should be treated as a draft.
            This checklist helps reviewers confirm data, official sources, safety boundaries
            and approval status before any formal use.
            Report creation and review write privacy-minimised audit events to local disk by default;
            clearing the current session does not remove those retained audit files.
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("View human review checklist", expanded=False):
        report_record = st.session_state.get("latest_report") or {}
        recorded_review = report_record.get("review_record") or {}
        st.markdown(
            f"**Current report status:** "
            f"{recorded_review.get('approval_status') or st.session_state.get('report_status', 'Draft - human review required')}"
        )
        st.markdown(f"**Reviewer name:** {recorded_review.get('reviewer_name') or 'Not specified'}")
        st.markdown(f"**Reviewer role:** {recorded_review.get('reviewer_role') or 'Not specified'}")
        st.markdown(f"**Review date:** {recorded_review.get('review_date') or 'Not specified'}")
        if recorded_review:
            st.markdown("**Latest sign-off record**")
            st.json(recorded_review)
        audit_path = report_record.get("audit_path")
        if audit_path:
            render_path_line("Latest audit record", audit_path)
            if not verify_report_record_snapshot(report_record):
                st.warning(
                    "The current report does not match its authoritative audit snapshot; audit download is disabled."
                )
            else:
                try:
                    audit_bytes = capture_current_audit_chain(audit_path)[-1]["bytes"]
                    st.download_button(
                        "Download audit JSON",
                        data=audit_bytes,
                        file_name=os.path.basename(audit_path),
                        mime="application/json",
                        width="stretch",
                        on_click="ignore",
                    )
                except (AuditIntegrityError, OSError, TypeError, ValueError):
                    st.warning("The latest audit is missing, legacy, malformed or not the authoritative current head.")
        for item in review_checklist:
            st.checkbox(item["label"], key=f"review_check_{item['id']}")


def _apply_review_record_to_report_state(review_record):
    # Reviewer/organisation drafting fields are Streamlit widgets rendered earlier
    # in the same run. The version-scoped report record is authoritative for identity.
    st.session_state.report_status = review_record.get("approval_status", "Draft - human review required")
    st.session_state.review_date = review_record.get("review_date", "")
    st.session_state.review_notes = review_record.get("review_notes", "")


def render_reviewer_approval(
    collect_review_record,
    update_latest_report_signoff,
    update_latest_audit_review,
    validate_review_record,
    persist_session_state,
):
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
    st.warning(
        "This prototype does not authenticate reviewer identity or create a legally binding approval. "
        "The status is a local pilot record only."
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
        submitted = st.form_submit_button(
            "Update sign-off record",
            width="stretch",
        )

    if submitted:
        review_record = collect_review_record(from_approval_form=True)
        validation_error = validate_review_record(
            review_record,
            st.session_state.get("latest_quality") or {},
            st.session_state.get("latest_report"),
        )
        if validation_error:
            st.warning(validation_error)
            return
        latest_report = st.session_state.get("latest_report") or {}
        if latest_report:
            audit_updated = update_latest_audit_review(review_record)
            if not audit_updated:
                st.error(
                    "The review was not recorded because a new verified audit event could not be created. "
                    "No approval state was committed."
                )
                return
            report_updated = True
        else:
            audit_updated = False
            report_updated = update_latest_report_signoff(review_record)
        _apply_review_record_to_report_state(review_record)
        st.session_state.latest_review_record = review_record
        persistence_succeeded = persist_session_state()
        if persistence_succeeded is False:
            st.warning(
                "The review and audit are available in this browser session, but the optional "
                "session file was not updated. Download the pilot package before closing the app."
            )
        if report_updated:
            st.success("Sign-off section updated in the latest report.")
        else:
            st.info("Sign-off record saved. Generate a report to attach it to report exports.")
        if audit_updated:
            st.success("A new append-only audit event was created and linked to the prior event.")
        elif st.session_state.get("latest_audit_path"):
            st.warning("No new audit event was created.")


def render_pilot_export_package(get_latest_assistant_text, collect_review_record, get_package_context):
    latest_report = get_latest_assistant_text()
    st.markdown("### Pilot Export Package")
    st.markdown(
        """
        <div class="source-note">
            Download one review package containing the latest report, PDF, DOCX, audit record,
            data register, reviewer sign-off and package manifest for stakeholder handover.
            It contains the full report and may contain reviewer identity and notes; store and
            share it only with authorised recipients.
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not latest_report:
        st.info("Generate a report first, then the pilot export package will become available.")
        return
    try:
        report_record = st.session_state.get("latest_report") or {}
        package = create_pilot_export_package(
            latest_report,
            audit_path=report_record.get("audit_path"),
            review_record=report_record.get("review_record") or {},
            package_context=get_package_context(),
            parent_audit_path=report_record.get("parent_audit_path"),
            register_snapshot=report_record.get("export_register_snapshot"),
            analysis=report_record.get("analysis"),
        )
        st.download_button(
            "Download pilot export package",
            data=package["content"],
            file_name=package["filename"],
            mime="application/zip",
            width="stretch",
            on_click="ignore",
        )
        with st.expander("View package manifest", expanded=False):
            st.json(package["manifest"])
    except Exception as exc:
        st.warning(f"Pilot package generation failed: {exc}")
