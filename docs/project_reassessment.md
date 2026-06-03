# BushfireReadyGPT Project Reassessment

## Current Position

BushfireReadyGPT is now a working Australia-focused bushfire preparedness planning MVP. It is no longer just a renamed chatbot. The project has a form-first workflow, deterministic multi-agent analysis, ABS/ASGS evidence context, official source registers, human review controls and exportable report packages.

The strongest current use case is a controlled pilot demonstration for councils, schools, community organisations or internship assessment. It should still be presented as draft planning support, not as an operational emergency platform.

## What Is Working

| Area | Current state |
| --- | --- |
| Product workflow | Clear form-to-report flow with review/export tabs. |
| Multi-agent layer | Profile, data, community vulnerability, risk context, planner, report and quality agents are separated. |
| Australian data context | Local ABS/ASGS processed data and official source registers are available. |
| Governance boundary | Reports include draft notices, evidence tables, human review sign-off and audit JSON. |
| Exports | Markdown, PDF, DOCX and pilot zip package are implemented. |
| Local model runtime | Ollama is the default provider, so no OpenAI API key is required. |
| Testing | Deterministic tests cover the core pipeline, appendices, registers, export package, validation and quality checks. |

## Main Gaps

| Priority | Gap | Why it matters | Recommended action |
| --- | --- | --- | --- |
| P0 | Legal and licence review is incomplete | Commercial or government use requires clear reuse rights, liability boundaries and procurement-safe wording. | Keep outputs as drafts; expand the licence register; prepare a legal review brief. |
| P0 | No authenticated approval workflow | Current reviewer fields are useful for pilots but not enough for formal approval records. | Add user roles, login, immutable sign-off records and audit history. |
| P0 | No live emergency interpretation | The app must not imply real-time warnings, evacuation status or safety decisions. | Keep the official status panel as source reachability only; add stricter copy around non-decision use. |
| P1 | Data matching is still pilot-level | Some geography and community vulnerability matches are approximations. | Use verified correspondence files and document match confidence in each report. |
| P1 | Accessibility and procurement readiness not checked | Government buyers often require accessibility, security and maintainability evidence. | Add WCAG review, deployment docs, privacy statement and security checklist. |
| P1 | UI is visually stronger but still Streamlit-limited | Streamlit is fine for MVP, but commercial UX may need a dedicated frontend. | Keep Streamlit for demo; plan a future React/FastAPI version if commercial traction appears. |
| P2 | No persistent database | Current local files are fine for prototypes but weak for multi-user pilots. | Add SQLite/PostgreSQL for reports, audits, users and data refresh logs. |

## Optimisations Completed In This Review

- Fixed the Report Quality Agent checklist detection by removing a corrupted legacy checkbox string.
- Added a Human Review Status quality check.
- Added report validation so reviewed or approved reports require organisation, reviewer name and reviewer role.
- Added reviewer name to the report form.
- Renamed the generic LLM response helper internally while preserving the old alias for compatibility.
- Added tests for approval validation and quality checklist detection.

## Suggested Next Build Order

1. **Project health panel**
   Add a small admin/readiness panel showing Ollama status, data files present, latest data update, latest audit path and test command.

2. **Data confidence labels**
   Add `high / medium / low / to be confirmed` confidence labels for community profile and ASGS matches.

3. **Commercial pilot package**
   Prepare a one-page pilot proposal, feedback form, sample report and export package for one council or school scenario.

4. **Approval workflow v2**
   Add named user roles and immutable approval records so a report can move from draft to reviewed to approved.

5. **Deployment plan**
   Add Docker, environment profiles, health checks and a privacy/security note for external demonstrations.

## Bottom Line

The project is suitable as a serious MVP demonstration. The next major difference between a good internship project and a commercial product is not another visual redesign. The next step is governance: verified data confidence, traceable approval, legal/licence clarity and deployment hardening.
