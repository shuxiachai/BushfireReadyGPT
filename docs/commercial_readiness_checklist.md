# Commercial Readiness Checklist

This checklist describes what should be completed before BushfireReadyGPT is positioned as a commercial or government-ready product.

## 1. Product Scope

- [x] Define the product as preparedness planning support, not emergency command and control.
- [x] Define supported user groups: council, school, community workshop, household, care facility or land manager.
- [x] Define unsupported use cases, including live evacuation decisions.
- [x] Create a plain-English safety boundary for all user-facing pages and exports.
- [ ] Create scenario-specific templates for the highest-priority customer segment.

## 2. Data And Evidence

- [ ] Verify all ABS datasets, fields, update dates and licences.
- [ ] Replace approximate geography matching with official correspondence files where required.
- [x] Add data freshness indicators to every generated report.
- [x] Add source citations or source notes to generated report evidence tables.
- [x] Distinguish official references, processed data, rule inference, AI-generated text and unverified user inputs.
- [ ] Document all derived indicators and aggregation methods.
- [x] Add a data quality warning when a selected geography has limited coverage.

## 3. Official Information

- [x] Identify official live sources for warnings, fire danger ratings, fire bans and weather.
- [x] Decide whether the product will display live status or only link to official sources.
- [x] If live status is added, record refresh time, source URL, coverage area and failure state.
- [x] Add clear wording that official emergency services remain authoritative.
- [ ] Review source terms of use before commercial integration.

## 4. Governance And Legal

- [ ] Review disclaimers with a legal or risk advisor.
- [x] Define human review and approval workflow.
- [x] Add versioned report records and reset prior approval/checklist state after every generation or revision.
- [ ] Define liability boundaries for generated reports.
- [ ] Add versioning for report templates.
- [x] Add privacy-minimised, hash-linked audit events for report hashes, model/data versions and reviewer actions.
- [x] Keep AI-generated content in draft status until approved by a responsible human.

## 5. Security And Privacy

- [x] Define current storage: isolated in-memory browser sessions by default, with local reports/audits and optional single-user JSON session persistence.
- [ ] Add authentication for multi-user deployments.
- [ ] Add role-based permissions for draft, reviewer and admin users.
- [x] Minimise default audit storage and require explicit consent before external-model data transfer.
- [ ] Add encryption/key management and field-level retention controls for any authorised sensitive data.
- [ ] Add retention rules for reports and audit files.
- [ ] Add backup and recovery procedures.

## 6. Deployment

- [ ] Decide deployment target: local demo, internal council server, cloud app or managed SaaS.
- [ ] Containerise the app.
- [ ] Add environment-specific configuration.
- [ ] Add health checks and logging.
- [x] Add model availability checks for Ollama or the chosen model service.
- [ ] Add graceful errors for every missing/corrupt data file; model-service errors and normal data limitation states are already handled.

## 7. Quality Assurance

- [x] Add automated tests for the report template.
- [x] Add automated tests for the agent pipeline.
- [x] Add export tests for PDF and DOCX.
- [x] Add Streamlit health smoke, AppTest workflow and Chromium end-to-end tests.
- [x] Add real-model regression cases for each supported scenario, plus safety-boundary and no-RAG behavior cases.
- [x] Add a human review checklist to every generated report.
- [x] Add deterministic report-level evidence-alignment metrics and human-review flags.
- [x] Add privacy-minimised local per-stage runtime diagnostics.

## 8. Commercial Packaging

- [x] Prepare a one-page product pitch.
- [x] Prepare a five-minute demo script.
- [x] Prepare a pilot feedback form.
- [x] Prepare a strict anonymous pilot-measurement schema and Bad Case regression register.
- [ ] Prepare a pricing and support hypothesis.
- [ ] Prepare a deployment and data handling explanation.
- [x] Prepare a short roadmap for live official data integration.

## Recommended Next Milestone

Run a controlled pilot with one school or council team. The goal is not to prove the tool is operationally complete. The goal is to validate whether the report format, evidence trail, data register and review workflow are useful enough to justify a production roadmap.
