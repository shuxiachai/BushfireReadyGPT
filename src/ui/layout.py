import streamlit as st

from src.deployment_access import is_cloud_deployment


def render_header():
    runtime_label = "Cloud demo" if is_cloud_deployment() else "Local Ollama"
    hero = """
        <section class="app-hero">
            <div class="app-kicker">Australian Bushfire Preparedness Intelligence</div>
            <h1 class="app-title">BushfireReadyGPT Preparedness Planning Workspace</h1>
            <p class="app-subtitle">
                A government-pilot style preparedness planning assistant for Australian councils,
                schools and communities. Complete the form to generate a structured English draft
                report, then review the evidence trail and export the report for human approval.
            </p>
            <div class="hero-signal-row">
                <span>Government-pilot MVP</span>
                <span>__RUNTIME_LABEL__</span>
                <span>ABS / ASGS evidence</span>
                <span>Human review required</span>
            </div>
        </section>
        <section class="workflow-strip">
            <div class="workflow-heading">Pilot Workflow</div>
            <div class="workflow-steps">
                <div class="workflow-step">
                    <div class="workflow-number">1</div>
                    <div class="workflow-title">Select geography</div>
                    <div class="workflow-copy">Choose State, SA4, SA3 or SA2 context for the pilot area.</div>
                </div>
                <div class="workflow-step">
                    <div class="workflow-number">2</div>
                    <div class="workflow-title">Generate draft</div>
                    <div class="workflow-copy">Create a structured preparedness report from the form inputs.</div>
                </div>
                <div class="workflow-step">
                    <div class="workflow-number">3</div>
                    <div class="workflow-title">Review evidence</div>
                    <div class="workflow-copy">Check agent outputs, data status, source register and limitations.</div>
                </div>
                <div class="workflow-step">
                    <div class="workflow-number">4</div>
                    <div class="workflow-title">Export records</div>
                    <div class="workflow-copy">Download PDF, DOCX, Markdown and audit JSON for review.</div>
                </div>
                <div class="workflow-step">
                    <div class="workflow-number">5</div>
                    <div class="workflow-title">Human approval</div>
                    <div class="workflow-copy">Keep outputs as drafts until reviewed by the responsible organisation.</div>
                </div>
            </div>
        </section>
        """
    st.markdown(
        hero.replace("__RUNTIME_LABEL__", runtime_label),
        unsafe_allow_html=True,
    )
