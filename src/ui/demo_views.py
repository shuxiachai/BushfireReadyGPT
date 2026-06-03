from html import escape
from pathlib import Path

import streamlit as st

from src.app_catalog import (
    DEMO_EXPECTED_QUESTIONS,
    DEMO_PRESENTATION_STEPS,
    DEMO_SCENARIO_PACK,
    PROJECT_MATURITY_ASSESSMENT,
)


PILOT_DOCUMENTS = [
    {
        "title": "Pilot Pitch",
        "path": "docs/pilot_pitch.md",
        "description": "One-page product positioning for council, school or community stakeholders.",
    },
    {
        "title": "Demo Walkthrough",
        "path": "docs/demo_walkthrough.md",
        "description": "Step-by-step walkthrough for presenting the product.",
    },
    {
        "title": "Feedback Form",
        "path": "docs/pilot_feedback_form.md",
        "description": "Structured reviewer feedback for a controlled pilot.",
    },
    {
        "title": "Commercial Readiness Checklist",
        "path": "docs/commercial_readiness_checklist.md",
        "description": "Commercial, legal, data, deployment and governance readiness checklist.",
    },
]


def render_demo_scenario_pack(load_demo_scenario, generate_current_report):
    st.markdown("### Demo Mode / Sample Scenario Pack")
    st.markdown(
        """
        <div class="source-note">
            Use these sample scenarios for a controlled walkthrough. Loading a demo fills the
            report form, sets the pilot context and pre-selects the matching map geography.
        </div>
        """,
        unsafe_allow_html=True,
    )
    active_demo = st.session_state.get("active_demo_scenario")
    cols = st.columns(len(DEMO_SCENARIO_PACK))
    for col, demo in zip(cols, DEMO_SCENARIO_PACK):
        with col:
            st.markdown(
                f"""
                <div class="status-card">
                    <div class="status-label">{escape(demo["audience_label"])}</div>
                    <div class="status-value">{escape(demo["title"])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(demo["demo_goal"])
            load_col, generate_col = st.columns(2)
            with load_col:
                if st.button("Load", key=f"load_demo_{demo['example_case']}", use_container_width=True):
                    load_demo_scenario(demo)
                    st.rerun()
            with generate_col:
                if st.button("Generate", key=f"generate_demo_{demo['example_case']}", use_container_width=True):
                    load_demo_scenario(demo)
                    with st.spinner(f"Generating {demo['title']}..."):
                        _, error = generate_current_report()
                    if error:
                        st.warning(error)
                    else:
                        st.session_state.demo_generation_notice = f"Generated: {demo['title']}"
                        st.rerun()
            if active_demo == demo["title"]:
                st.success("Loaded")

    if st.session_state.get("demo_generation_notice"):
        st.success(st.session_state.demo_generation_notice)
        st.session_state.demo_generation_notice = ""

    selected_demo = next((item for item in DEMO_SCENARIO_PACK if item["title"] == active_demo), None)
    if selected_demo:
        with st.expander("Current demo talking points", expanded=True):
            st.markdown(f"**Expected export:** {selected_demo['expected_export']}")
            for point in selected_demo["talking_points"]:
                st.markdown(f"- {point}")


def render_presentation_mode():
    st.markdown("### Presentation Mode / Demo Script")
    st.markdown(
        """
        <div class="source-note">
            Use this as an in-app script during a presentation. It tells you what to say,
            what to click and what result to show.
        </div>
        """,
        unsafe_allow_html=True,
    )
    active_demo = st.session_state.get("active_demo_scenario") or "No demo loaded yet"
    st.caption(f"Active demo: {active_demo}")

    with st.expander("Open presentation script", expanded=False):
        for item in DEMO_PRESENTATION_STEPS:
            st.markdown(f"#### {item['step']}. {item['title']}")
            st.markdown(f"**Say:** {item['say']}")
            st.markdown("**Show / click:**")
            for target in item["show"]:
                st.markdown(f"- {target}")
            st.markdown(f"**Expected result:** {item['expected']}")

    with st.expander("Expected questions", expanded=False):
        for item in DEMO_EXPECTED_QUESTIONS:
            st.markdown(f"**Q: {item['question']}**")
            st.markdown(f"A: {item['answer']}")

    with st.expander("Quick presenter checklist", expanded=False):
        checklist = [
            "Ollama is running and the Streamlit app is open.",
            "One demo scenario has been loaded or generated.",
            "Evidence Trail can be opened without errors.",
            "Data Status and Data Register show ABS and official source records.",
            "Reviewer Approval / Human Sign-off is visible.",
            "Pilot Export Package can be downloaded.",
            "Safety boundary is stated clearly before discussing outputs.",
        ]
        for index, item in enumerate(checklist):
            st.checkbox(item, key=f"presenter_check_{index}")


def render_maturity_assessment():
    assessment = PROJECT_MATURITY_ASSESSMENT
    st.markdown("### Project Maturity / Commercial Gap Assessment")
    st.markdown(
        f"""
        <div class="source-note">
            <strong>Current stage:</strong> {escape(assessment["current_stage"])}<br/>
            {escape(assessment["summary"])}
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Read maturity scores", expanded=False):
        for item in assessment["scores"]:
            st.markdown(
                f"""
                <div class="status-card maturity-card">
                    <div class="status-label">{escape(item["area"])} | {escape(item["status"])}</div>
                    <div class="status-value">{escape(item["score"])}</div>
                    <div class="maturity-note">{escape(item["note"])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with st.expander("Completed capabilities", expanded=False):
        for item in assessment["completed"]:
            st.markdown(f"- {item}")

    with st.expander("Commercial and government readiness gaps", expanded=False):
        for item in assessment["gaps"]:
            st.markdown(
                f"""
                <div class="status-card maturity-card">
                    <div class="status-label">{escape(item["priority"])} | {escape(item["area"])}</div>
                    <div class="status-value">{escape(item["gap"])}</div>
                    <div class="maturity-note"><strong>Next action:</strong> {escape(item["next_action"])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with st.expander("Recommended roadmap", expanded=False):
        for item in assessment["roadmap"]:
            st.markdown(
                f"""
                <div class="status-card maturity-card">
                    <div class="status-label">{escape(item["phase"])}</div>
                    <div class="status-value">{escape(item["goal"])}</div>
                    <div class="maturity-note">{escape(item["work"])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_government_pilot_brief():
    st.markdown("### Government Pilot Brief")
    with st.expander("Read pilot positioning and operating boundaries", expanded=False):
        st.markdown(
            """
            **Product positioning**

            BushfireReady Planner is a preparedness planning support tool for Australian councils,
            schools and community resilience teams. It helps users generate draft evidence reports
            using ABS community data, official information source registers, map-based geography
            selection and a human review workflow.

            **What it supports**

            - Draft bushfire preparedness reports
            - Community profile and vulnerability context
            - Evidence trail and data limitation review
            - Action planning, communication planning and checklist drafting
            - PDF / DOCX export for human review

            **What it does not do**

            - It does not provide live fire conditions.
            - It does not issue evacuation orders, fire bans or emergency directions.
            - It does not replace QFD, BoM, councils or emergency services.
            - It does not make life-safety decisions. Call 000 in life-threatening emergencies.

            **Recommended pilot workflow**

            1. Select the pilot mode and organisation.
            2. Select the map geography using State / SA4 / SA3 / SA2.
            3. Generate a draft report.
            4. Review the Evidence Trail, Data Register and Human Review Checklist.
            5. Export the report and audit JSON for reviewer records.
            """
        )
    render_pilot_document_library()


def read_markdown_document(path):
    file_path = Path(path)
    if not file_path.exists():
        return None
    return file_path.read_text(encoding="utf-8")


def render_pilot_document_library():
    st.markdown("#### Pilot Document Library")
    st.caption("Use these materials for stakeholder demos, controlled pilots and commercial-readiness planning.")

    doc_tabs = st.tabs([doc["title"] for doc in PILOT_DOCUMENTS])
    for tab, doc in zip(doc_tabs, PILOT_DOCUMENTS):
        with tab:
            st.markdown(f"**{doc['description']}**")
            content = read_markdown_document(doc["path"])
            if content is None:
                st.warning(f"Document not found: {doc['path']}")
                continue

            action_cols = st.columns([1, 3])
            with action_cols[0]:
                st.download_button(
                    "Download Markdown",
                    data=content,
                    file_name=Path(doc["path"]).name,
                    mime="text/markdown",
                    use_container_width=True,
                    key=f"download_{Path(doc['path']).stem}",
                )
            with action_cols[1]:
                st.caption(doc["path"])

            with st.expander("Preview document", expanded=False):
                st.markdown(content)


def render_usage_guide():
    with st.expander("About Project / Usage Guide", expanded=False):
        st.markdown(
            """
            **Project positioning**

            BushfireReadyGPT is an Australia-focused bushfire preparedness report generator for
            councils, schools, communities, households, care facilities and land managers. It
            converts a location, audience, scenario and planning focus into a structured English
            draft report.

            **Multi-agent analysis flow**

            The app runs a local multi-agent analysis flow before generating each report: Profile
            Agent, Australian Data Agent, Community Vulnerability Agent, Risk Context Agent,
            Planner Agent and Report Agent. The Evidence Trail shows the intermediate reasoning,
            data notes and limitations.

            **Quality and governance**

            The Report Quality Agent checks required sections, official sources, safety disclaimer,
            000 guidance, action plan, checklist, roles and responsibilities, and safe wording
            around assembly points. Government pilot mode also adds a data register, audit JSON
            and human review checklist.

            **Workflow**

            1. Complete the report form.
            2. For a demonstration, select a pilot example and click Load example.
            3. Click Generate report.
            4. Review the Evidence Trail, Data Register and Human Review Checklist.
            5. Download Markdown, PDF, DOCX or the audit JSON for reviewer records.
            6. Use the chat box to request edits to the latest report.

            **Safety boundary**

            This tool does not provide live fire information, fire bans, evacuation orders or
            life-safety decisions. In a real emergency, follow official emergency services and
            call 000 if life is at risk.
            """
        )
