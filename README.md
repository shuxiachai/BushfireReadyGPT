# BushfireReadyGPT

BushfireReadyGPT is an Australia-focused Streamlit prototype for bushfire emergency preparedness planning. It converts a location, audience, scenario and planning focus into a structured English draft report, supported by local Ollama generation, an evidence trail, ABS-derived community context, official source registers and exportable audit records.

The project was adapted from the open-source WildfireGPT / MARSHA project. Original United States wildfire datasets, experiments and inactive tools are treated as local legacy reference material only; the main application no longer treats those files as Australian evidence.

## Key Features

- Form-based report generation for councils, schools, communities, households, care facilities and land management scenarios.
- Fixed English report structure covering purpose, scope, selected geography, local risk context, evacuation planning, candidate assembly point criteria, roles, communications, training, action planning and safety disclaimers.
- Local multi-agent analysis pipeline: Profile, Australian Data, Community Vulnerability, Risk Context, Planner, Report and Report Quality agents.
- Evidence Trail panel showing intermediate agent outputs, matched geography, community profile evidence, official sources, risk factors and limitations.
- Deterministic Evidence Tables appended to generated reports for selected geography, community indicators, LGA candidates, official sources and human-review limitations.
- Government Pilot Mode for school, council and community workshop trials.
- Demo Mode / Sample Scenario Pack with one-click load or generate for Cairns council, Cairns school and remote Queensland walkthroughs.
- Presentation Mode / Demo Script with presenter steps, expected questions and a live checklist.
- Project Maturity / Commercial Gap Assessment with readiness scores, gaps and roadmap.
- Live Official Status Panel that checks official entry-point reachability without interpreting emergency warnings.
- Data Register for ABS, Queensland Government, BoM and other official source metadata.
- Licence Register for ABS, BoM, Queensland Government, Cairns Council and Triple Zero reuse assumptions.
- Human Review Checklist, reviewer sign-off records and audit JSON export for traceability.
- All-Australia offline SA2 / SA3 / SA4 geography selection using ABS-derived data.
- Map selection linked to the Community Vulnerability Agent and final report generation.
- Markdown, PDF and DOCX report export.
- Pilot Export Package zip containing report Markdown, PDF, DOCX, audit JSON, reviewer sign-off and data register files.
- Local Ollama runtime; no OpenAI API key is required.
- VSCode task entry for one-click startup.

## Current Maturity

The project is currently a working MVP suitable for coursework, internship demonstration, portfolio use and early stakeholder discussion. It is not yet ready for operational emergency management or government procurement without further validation.

Already implemented:

- Australia-specific bushfire preparedness positioning.
- Form-first workflow instead of a generic chatbot page.
- Local Ollama model integration.
- Multi-agent analysis flow with visible intermediate evidence.
- ABS raw / processed data separation.
- All-Australia SA2 / SA3 / SA4 selection.
- ABS ASGS allocation and correspondence files for official geography traceability.
- Report exports include a draft notice, human-review boundary and evidence tables for audit review.
- Markdown, PDF, DOCX and audit JSON export.
- Government pilot governance screens.
- Reviewer Approval / Human Sign-off workflow for recording reviewer name, role, review date, approval status and notes.
- One-click pilot package export for stakeholder handover and controlled pilot review.
- VSCode startup task.

Still required before commercial or government use:

- Replace approximate regional matching with verified official correspondence files where needed.
- Add live warning and incident status panels from official sources.
- Add stronger source citation and data freshness controls.
- Add role-based access, deployment hardening and privacy controls.
- Add formal user testing with a school, council or community resilience team.
- Complete legal review for licences, disclaimers, procurement claims and liability boundaries.

## Run The App

Make sure Ollama is installed, running and has a model available:

```powershell
ollama pull qwen2.5:7b
ollama serve
```

The project root should contain `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:7b
```

Recommended VSCode startup:

```text
Ctrl + Shift + P
Tasks: Run Task
Start BushfireReadyGPT
```

Or run from the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_app.ps1
```

The startup script checks Ollama and automatically selects an available Streamlit port from `8501` to `8505`. Closing the running Streamlit terminal, or pressing `Ctrl + C`, releases the port.

## Project Structure

```text
src/wildfireChat.py                 Streamlit application
src/app_state.py                    Shared Streamlit state helpers and latest-report utilities
src/session_store.py                Session persistence, thread sync and conversation reset
src/report_workflow.py              Report generation, audit and human-review workflow
src/ui/                             Streamlit UI modules for theme, layout, reports, review, data/source, map and sidebar views
src/app_catalog.py                  Official sources, form options and pilot examples
src/report_template.py              English report prompt and fixed report structure
src/agents/                         Local Australia-focused multi-agent pipeline
src/assistants/                     Model client and active profile/chat assistant layer
src/coverage_map.py                 SA2 / SA3 / SA4 map and community profile loading
src/data_register.py                Data source register for pilot governance
src/licence_register.py             Licence register loader and export helpers
src/data_status.py                  Data status and source checks
src/audit.py                        Audit JSON saving
src/pdf_export.py                   PDF report export
src/docx_export.py                  DOCX report export
data_australia/official_sources.yml Official information source metadata
data_australia/licence_register.yml Official source licence assumptions and review status
data_australia/risk_context_rules.yml
                                    Australia / Queensland / Cairns risk rules
data_australia/raw/                 Raw official downloads or API responses
data_australia/processed/           Cleaned data used by agents
scripts/download_abs_community_profiles.py
                                    Configured ABS community profile download script
scripts/download_abs_sa2_all.py     All-Australia ABS SA2 profile and boundary script
scripts/download_abs_asgs_allocations.py
                                    ABS ASGS allocation / correspondence download script
docs/README.md                     Documentation index and recommended reading order
docs/architecture.md                Architecture, data flow and agent responsibilities
docs/showcase_package.md            Showcase material index for presentations and portfolio review
docs/project_overview.md            First-time project explanation and current positioning
docs/demo_walkthrough.md            Step-by-step live demonstration walkthrough
docs/showcase_checklist.md          Pre-presentation readiness checklist
docs/demo_scenarios.md              Built-in demo scenario pack
docs/commercial_gap_assessment.md   Maturity, commercial gap and roadmap assessment
docs/project_reassessment.md        Current reassessment, gaps and recommended next build order
docs/licence_register.md            Licence assumptions and commercial review notes
docs/legacy_cleanup_plan.md         Archived legacy module notes
chat_history/                       Local reports and interaction logs
chat_history/audit/                 Government pilot audit JSON records
legacy/                            Optional local archive of inactive original-project material; ignored by Git
tests/                              Deterministic regression tests for core project flows
start_app.ps1                       VSCode / PowerShell startup entry
```

## Run Tests

The project includes a small deterministic test suite for the local agent pipeline, report appendices, data and licence registers, and pilot export package.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Data Notes

The current data layer is split as follows:

- `data_australia/raw/` stores raw official downloads or API responses for traceability.
- `data_australia/processed/` stores cleaned CSV / GeoJSON files used by the agents.
- `legacy/` may keep original-project material locally as an inactive archive. It is ignored by Git and is not part of the active Australian evidence layer.

The all-Australia map selector uses:

```text
data_australia/processed/sa2_profiles_all.csv
data_australia/processed/sa2_boundaries_all.geojson
data_australia/processed/sa2_boundaries_by_state/*.geojson
```

To rebuild the all-Australia SA2 / SA3 / SA4 selection data:

```powershell
.\.venv\Scripts\python.exe scripts\download_abs_sa2_all.py
```

To rebuild the official ASGS allocation and correspondence reference layer:

```powershell
.\.venv\Scripts\python.exe scripts\download_abs_asgs_allocations.py
```

This creates:

```text
data_australia/processed/asgs_allocations/sa2_to_sa3_sa4_state_2021.csv
data_australia/processed/asgs_allocations/lga_2025_summary.csv
data_australia/processed/asgs_allocations/lga_2024_to_2025_correspondence.csv
data_australia/processed/asgs_allocations/metadata.json
```

Large raw and processed geospatial files are intentionally ignored by Git.

## Safety Boundary

This application does not provide live fire conditions, fire bans, evacuation orders, official safe routes or life-safety decisions. It is a preparedness planning and draft reporting tool. In an emergency, follow official emergency services and call `000` if life is at risk.

## Suggested Next Extensions

- Add a live official information status panel using Queensland and BoM sources.
- Add formal data freshness indicators for every report.
- Add scenario-specific templates for councils, schools, care facilities, households and remote communities.
- Add reviewer accounts, approvals and signed report status.
- Add a deployable cloud architecture with private data handling and access control.
- Prepare a pilot package for one council or school, including a demo script, data register, review process and feedback form.
