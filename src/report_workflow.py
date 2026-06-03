from datetime import datetime
import json
import os

import streamlit as st

from src.agents import run_analysis_pipeline
from src.agents.report_quality_agent import ReportQualityAgent
from src.audit import save_report_audit
from src.report_template import (
    append_evidence_tables,
    append_human_signoff,
    apply_governance_notice,
    build_report_prompt,
)


def collect_report_inputs():
    return {
        "pilot_mode": st.session_state.get("pilot_mode"),
        "organisation_name": st.session_state.get("organisation_name"),
        "reviewer_name": st.session_state.get("reviewer_name"),
        "reviewer_role": st.session_state.get("reviewer_role"),
        "review_date": str(st.session_state.get("review_date")),
        "review_notes": st.session_state.get("review_notes"),
        "report_status": st.session_state.get("report_status"),
        "location": st.session_state.get("form_location"),
        "audience": st.session_state.get("form_audience"),
        "scenario": st.session_state.get("form_scenario"),
        "concerns": st.session_state.get("form_concerns", []),
        "timeframe": st.session_state.get("form_timeframe"),
        "extra_context": st.session_state.get("form_extra_context"),
    }


def validate_report_inputs(inputs):
    location = (inputs.get("location") or "").strip()
    audience = (inputs.get("audience") or "").strip()
    concerns = inputs.get("concerns") or []
    report_status = inputs.get("report_status") or "Draft - human review required"
    organisation_name = (inputs.get("organisation_name") or "").strip()
    reviewer_name = (inputs.get("reviewer_name") or "").strip()
    reviewer_role = (inputs.get("reviewer_role") or "").strip()

    if not location or not audience:
        return "Please enter a location and audience, or load a pilot example."
    if not concerns:
        return "Please select at least one focus area, or load a pilot example."
    if report_status in {"Reviewed draft", "Approved by organisation"}:
        missing = []
        if not organisation_name:
            missing.append("organisation / department")
        if not reviewer_name:
            missing.append("reviewer name")
        if not reviewer_role:
            missing.append("reviewer role")
        if missing:
            return (
                "Before marking a report as reviewed or approved, please provide: "
                + ", ".join(missing)
                + "."
            )
    return None


def collect_review_record():
    return {
        "approval_status": st.session_state.get("report_status", "Draft - human review required"),
        "reviewer_name": st.session_state.get("reviewer_name", ""),
        "reviewer_role": st.session_state.get("reviewer_role", ""),
        "review_date": str(st.session_state.get("review_date", "")),
        "organisation_name": st.session_state.get("organisation_name", ""),
        "review_notes": st.session_state.get("review_notes", ""),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def update_latest_audit_review(review_record):
    audit_path = st.session_state.get("latest_audit_path")
    if not audit_path or not os.path.exists(audit_path):
        return False
    try:
        with open(audit_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        payload["human_review"] = review_record
        payload["report_status"] = review_record.get("approval_status")
        payload["review_updated_at"] = datetime.now().isoformat(timespec="seconds")
        with open(audit_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        return True
    except (OSError, json.JSONDecodeError):
        return False


def update_latest_report_signoff(review_record, is_welcome_message):
    for message in reversed(st.session_state.get("messages", [])):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if not isinstance(content, str) or is_welcome_message(content):
            continue
        message["content"] = append_human_signoff(content, review_record)
        return True
    return False


def get_package_context():
    inputs = collect_report_inputs()
    selected = st.session_state.get("selected_map_area") or {}
    return {
        "pilot_mode": inputs.get("pilot_mode"),
        "organisation_name": inputs.get("organisation_name"),
        "location": inputs.get("location"),
        "audience": inputs.get("audience"),
        "scenario": inputs.get("scenario"),
        "report_status": st.session_state.get("report_status"),
        "selected_map_area": selected,
        "model_provider": os.environ.get("LLM_PROVIDER", "ollama"),
        "model_name": os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
    }


def build_governance_context():
    selected = st.session_state.get("selected_map_area")
    selected_label = (
        f"{selected.get('state')} / {selected.get('level')} / {selected.get('area_name')}"
        if selected
        else "No explicit map selection; use best available location match."
    )
    return f"""
Government pilot governance context:
- Pilot mode: {st.session_state.get("pilot_mode")}
- Organisation / department: {st.session_state.get("organisation_name") or "Not specified"}
- Report status: {st.session_state.get("report_status")}
- Human reviewer name: {st.session_state.get("reviewer_name") or "Not specified"}
- Human reviewer role: {st.session_state.get("reviewer_role")}
- Selected geography for analysis: {selected_label}
- The report must be written as a draft for human review, not as an official emergency direction.
- Include a clear data sources and limitations section.
- Include a human review / approval note before any operational use.
"""


def validate_current_report_form():
    return validate_report_inputs(collect_report_inputs())


def generate_current_report(persist_session_state):
    validation_error = validate_current_report_form()
    if validation_error:
        return None, validation_error

    analysis = run_analysis_pipeline(
        st.session_state.form_location,
        st.session_state.form_audience,
        st.session_state.form_scenario,
        st.session_state.form_concerns,
        st.session_state.form_timeframe,
        st.session_state.form_extra_context,
        area_selection=st.session_state.get("selected_map_area"),
    )
    st.session_state.latest_analysis = analysis
    governance_context = build_governance_context()
    prompt = build_report_prompt(
        st.session_state.form_location,
        st.session_state.form_audience,
        st.session_state.form_scenario,
        st.session_state.form_concerns,
        st.session_state.form_timeframe,
        st.session_state.form_extra_context,
        analysis=analysis,
        area_selection=st.session_state.get("selected_map_area"),
        governance_context=governance_context,
    )
    st.session_state.messages.append({"role": "user", "content": prompt})
    full_response = st.session_state.assistant.get_assistant_response(prompt)
    full_response = apply_governance_notice(full_response)
    full_response = append_evidence_tables(full_response, analysis)
    full_response = append_human_signoff(full_response, collect_review_record())
    st.session_state.messages.append({"role": "assistant", "content": full_response})
    st.session_state.latest_quality = ReportQualityAgent().run(full_response)
    audit_path = save_report_audit(
        {
            "inputs": collect_report_inputs(),
            "area_selection": st.session_state.get("selected_map_area"),
            "analysis": analysis,
            "quality": st.session_state.latest_quality,
            "model_provider": os.environ.get("LLM_PROVIDER", "ollama"),
            "model_name": os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
            "report_status": st.session_state.report_status,
            "human_review": collect_review_record(),
            "report_text": full_response,
        }
    )
    st.session_state.latest_audit_path = audit_path
    persist_session_state()
    return full_response, None
