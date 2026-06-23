# BushfireReadyGPT

BushfireReadyGPT is an Australia-focused bushfire preparedness planning MVP. It helps councils, schools and community resilience teams generate structured draft preparedness reports from a selected location, audience, scenario and planning focus.

The project runs locally through Ollama, exposes a deterministic multi-agent evidence trail, uses ABS / ASGS-derived Australian data context, and exports reviewable reports with human sign-off and audit records.

This project was adapted from the open-source WildfireGPT / MARSHA project. Original United States wildfire data, experiments and inactive tools are treated as local legacy reference material only; the active application is now positioned around Australian bushfire preparedness.

## Current Status

**Stage:** Government-pilot MVP

Ready for:

- Internship demonstration
- Coursework or portfolio showcase
- Controlled stakeholder discussion
- Early school, council or community pilot scoping

Not ready for:

- Operational emergency management
- Public life-safety decision support
- Government procurement
- Commercial deployment without legal, security, privacy and licence review

## What It Does

- Generates formal English bushfire preparedness draft reports.
- Supports council, school, community, household, care facility and land management scenarios.
- Uses a form-first workflow rather than a generic chatbot flow.
- Runs a local Australia-focused multi-agent analysis pipeline.
- Shows an Evidence Trail with profile, official source, community vulnerability, risk and planning outputs.
- Uses local ABS / ASGS-derived geography and community context.
- Provides official source, data and licence registers.
- Adds draft notices, evidence tables, safety disclaimers and human review sign-off.
- Exports Markdown, PDF, DOCX and pilot export packages.
- Runs locally with Ollama, so no OpenAI API key is required.

## Example Output

For a quick view of the type of report this project produces, see:

- [examples/cairns_campus_bushfire_report.md](examples/cairns_campus_bushfire_report.md) - sample draft report for a Cairns campus scenario.

The sample is a static demonstration output. It is not a live emergency plan and should not be used for real operational decisions.

## Safety Boundary

BushfireReadyGPT does **not** provide live fire conditions, fire bans, evacuation orders, official safe routes, confirmed safe assembly points or life-safety decisions.

It is a preparedness planning and draft reporting tool. In an emergency, follow official emergency services and call `000` if life is at risk.

## Quick Start

These commands assume Windows PowerShell from the project root.

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

Install Ollama, then download and start the configured local model:

```powershell
ollama pull qwen2.5:7b
ollama serve
```

Create `.env` in the project root:

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

Or run from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_app.ps1
```

The startup script checks Ollama and automatically selects an available Streamlit port from `8501` to `8505`. Keep the terminal open while using the app. Press `Ctrl + C` or close the terminal to stop Streamlit and release the port.

## Demo Path

For the cleanest demonstration:

1. Open the app.
2. Go to `Create Report`.
3. Select `Cairns Council pilot`.
4. Click `Load example`.
5. Click `Generate report`.
6. Show `Latest Report Preview`.
7. Open `Review & Export` and show the Evidence Trail, Report Quality Check and Human Review Checklist.
8. Open `Data & Map` and show official sources, data status, licence register and map context.
9. Download the pilot export package.
10. Explain the safety boundary and current commercial limitations.

See [docs/demo_walkthrough.md](docs/demo_walkthrough.md) for a full presentation script.

## Documentation

Start with:

- [docs/README.md](docs/README.md) - Documentation index and recommended reading order.
- [docs/showcase_package.md](docs/showcase_package.md) - Showcase package for presentations and portfolio review.
- [docs/project_overview.md](docs/project_overview.md) - Plain project explanation and positioning.
- [docs/demo_walkthrough.md](docs/demo_walkthrough.md) - Step-by-step live demo walkthrough.
- [docs/showcase_checklist.md](docs/showcase_checklist.md) - Pre-presentation readiness checklist.

Project and commercial context:

- [docs/architecture.md](docs/architecture.md) - Architecture, agent responsibilities and data flow.
- [docs/project_reassessment.md](docs/project_reassessment.md) - Current maturity, gaps and next build order.
- [docs/commercial_gap_assessment.md](docs/commercial_gap_assessment.md) - Commercial and government-readiness gap assessment.
- [docs/commercial_readiness_checklist.md](docs/commercial_readiness_checklist.md) - Commercial readiness checklist.
- [docs/pilot_pitch.md](docs/pilot_pitch.md) - One-page pilot pitch.
- [docs/pilot_feedback_form.md](docs/pilot_feedback_form.md) - Controlled pilot feedback form.

Sample output:

- [examples/cairns_campus_bushfire_report.md](examples/cairns_campus_bushfire_report.md) - static sample report for GitHub review.

## Architecture Summary

```text
Streamlit UI
  -> Report form and workspace tabs
  -> Deterministic multi-agent pipeline
      -> Profile Agent
      -> Australian Data Agent
      -> Community Vulnerability Agent
      -> Risk Context Agent
      -> Planner Agent
      -> Report Agent
      -> Report Quality Agent
  -> Local Ollama generation
  -> Evidence tables, sign-off and audit JSON
  -> Markdown / PDF / DOCX / pilot package export
```

## Project Structure

```text
src/wildfireChat.py                 Streamlit application entry
src/app_state.py                    Shared Streamlit state helpers
src/session_store.py                Session persistence and conversation reset
src/report_workflow.py              Report generation, audit and human-review workflow
src/ui/                             Streamlit UI modules
src/app_catalog.py                  Official sources, form options and pilot examples
src/report_template.py              Fixed English report prompt and report structure
src/agents/                         Australia-focused multi-agent pipeline
src/assistants/                     Model client and conversation assistant layer
src/coverage_map.py                 SA2 / SA3 / SA4 map and community profile loading
src/data_register.py                Data source register
src/licence_register.py             Licence register loader and export helpers
src/data_status.py                  Data status and source checks
src/audit.py                        Audit JSON saving
src/pdf_export.py                   PDF report export
src/docx_export.py                  DOCX report export
data_australia/                     Australian metadata, rules and lightweight processed data
scripts/                            Data download / rebuild scripts
docs/                               Project, demo, governance and commercial-readiness docs
tests/                              Deterministic regression tests
start_app.ps1                       VSCode / PowerShell startup entry
```

## Data Notes

The active data layer is under `data_australia/`.

- `data_australia/raw/` stores raw official downloads or API responses for traceability and is ignored by Git.
- `data_australia/processed/` stores cleaned files used by the agents.
- Lightweight processed reference files may be committed for reproducible demos.
- Large raw and geospatial files are intentionally ignored by Git.
- Original-project legacy material is not part of the active Australian evidence layer.

The committed data is intended for demonstration, traceability and planning context only. It does not provide live incident status, fire danger ratings, evacuation orders, safe routes or confirmed assembly points.

To rebuild all-Australia SA2 / SA3 / SA4 selection data:

```powershell
.\.venv\Scripts\python.exe scripts\download_abs_sa2_all.py
```

To rebuild ASGS allocation and correspondence reference data:

```powershell
.\.venv\Scripts\python.exe scripts\download_abs_asgs_allocations.py
```

## Tests

Run the deterministic test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Current expected result:

```text
9 passed
```

## Git And Repository Hygiene

Before publishing or sharing the repository, review the current Git status and commit the intended changes:

```powershell
git status
git log --oneline -8
```

Ignored local files include `.env`, `.venv/`, `.claude/`, `.agents/`, runtime chat history and large raw/geospatial data.

## Next Improvement Areas

Without expanding the feature set, the next polishing work is:

- Keep README and docs aligned as the project changes.
- Strengthen UI smoke tests for the main workflow.
- Add data-confidence wording to reports and demo materials.
- Prepare a polished sample report package for one scenario.
- Review licence and disclaimer language with a legal/risk advisor before any commercial positioning.
