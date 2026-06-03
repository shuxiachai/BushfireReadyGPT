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
- [ ] Add data freshness indicators to every generated report.
- [x] Add source citations or source notes to generated report evidence tables.
- [ ] Document all derived indicators and aggregation methods.
- [ ] Add a data quality warning when a selected geography has limited coverage.

## 3. Official Information

- [x] Identify official live sources for warnings, fire danger ratings, fire bans and weather.
- [x] Decide whether the product will display live status or only link to official sources.
- [x] If live status is added, record refresh time, source URL, coverage area and failure state.
- [x] Add clear wording that official emergency services remain authoritative.
- [ ] Review source terms of use before commercial integration.

## 4. Governance And Legal

- [ ] Review disclaimers with a legal or risk advisor.
- [x] Define human review and approval workflow.
- [ ] Define liability boundaries for generated reports.
- [ ] Add versioning for report templates.
- [x] Add audit logs for inputs, outputs, model version, data version and reviewer actions.
- [x] Keep AI-generated content in draft status until approved by a responsible human.

## 5. Security And Privacy

- [ ] Define whether user data is stored locally, in cloud storage or in a database.
- [ ] Add authentication for multi-user deployments.
- [ ] Add role-based permissions for draft, reviewer and admin users.
- [ ] Avoid storing sensitive personal data unless necessary.
- [ ] Add retention rules for reports and audit files.
- [ ] Add backup and recovery procedures.

## 6. Deployment

- [ ] Decide deployment target: local demo, internal council server, cloud app or managed SaaS.
- [ ] Containerise the app.
- [ ] Add environment-specific configuration.
- [ ] Add health checks and logging.
- [ ] Add model availability checks for Ollama or the chosen model service.
- [ ] Add graceful errors when data files or model services are unavailable.

## 7. Quality Assurance

- [x] Add automated tests for the report template.
- [x] Add automated tests for the agent pipeline.
- [ ] Add export tests for PDF and DOCX.
- [ ] Add UI smoke tests for the main workflow.
- [ ] Add regression examples for each supported scenario.
- [x] Add a human review checklist to every generated report.

## 8. Commercial Packaging

- [x] Prepare a one-page product pitch.
- [x] Prepare a five-minute demo script.
- [x] Prepare a pilot feedback form.
- [ ] Prepare a pricing and support hypothesis.
- [ ] Prepare a deployment and data handling explanation.
- [x] Prepare a short roadmap for live official data integration.

## Recommended Next Milestone

Run a controlled pilot with one school or council team. The goal is not to prove the tool is operationally complete. The goal is to validate whether the report format, evidence trail, data register and review workflow are useful enough to justify a production roadmap.
