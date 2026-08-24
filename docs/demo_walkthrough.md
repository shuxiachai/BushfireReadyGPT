# BushfireReadyGPT Demo Walkthrough

Use this walkthrough for a live demonstration. It assumes the app is already installed and Ollama is available.

## Before The Demo

Double-click the single self-checking launcher:

```text
Start BushfireReadyGPT.bat
```

The launcher reuses valid dependencies, models and the RAG index, starts Ollama
when needed, waits for Streamlit health, and opens the browser. Alternatively,
start the same workflow from VSCode:

```text
Ctrl + Shift + P
Tasks: Run Task
Start BushfireReadyGPT
```

Or run its PowerShell implementation directly:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_app.ps1
```

Confirm that the page opens and the sidebar shows the safety boundary.

Before presenting committed release evidence, run the offline verifier:

```powershell
poetry run python scripts/verify_release.py
```

The `v0.5.0` evidence set is tied to source commit `e02f076`, exact evaluation-dataset hashes, one RAG manifest, resolved model identities and the current governed-report policy. This is an offline consistency check, not external user validation.

## Recommended Demo: Cairns Council Pilot

### 1. Introduce The Product

Say:

> BushfireReadyGPT is an Australia-focused preparedness planning MVP. It helps councils, schools and communities create structured draft bushfire preparedness reports with local evidence, human review controls and exportable records.

Show:

- App title and hero section.
- Sidebar safety boundary.
- Planning Workspace tabs.

Key point:

> This is not a live emergency system. It supports preparedness planning and draft report review.

### 2. Load The Example

Go to `Create Report`.

Select:

```text
Cairns Council pilot
```

Click:

```text
Load example
```

Say:

> The example fills in the geography, audience, scenario, focus areas and review context. Users can also start from an empty form.

### 3. Generate The Report

Click:

```text
Generate report
```

Say:

> The app runs a deterministic multi-agent analysis pipeline first, then asks the local Ollama model to generate a formal report using that evidence context.

Wait for the report to appear.

### 4. Explain The Report

Show `Latest Report Preview`.

Say:

> The output is a formal English draft report. It includes purpose, scope, selected geography, data limitations, local risk context, evacuation planning, candidate assembly point criteria, roles, communications, first aid, action planning, human review and a safety disclaimer.

Point out:

- Draft status notice.
- Evidence confidence and provenance labels.
- Evidence tables.
- Human review sign-off.
- Safety disclaimer.

### 5. Show The Evidence Trail

Go to:

```text
Review & Export
```

Open:

```text
Evidence Trail
```

Say:

> The evidence trail shows that the report is not just a single chatbot answer. It separates profile analysis, official source selection, community vulnerability context, risk rules and planning priorities. O1 identifies official references, P2 processed data, R3 deterministic inference, A4 AI-generated draft text and U0 unverified input.

Key point:

> These codes describe provenance and review needs. They are not fire danger ratings or live incident severity levels.

Mention the agents:

- Profile Agent
- Australian Data Agent
- Official Knowledge Agent
- Community Vulnerability Agent
- Risk Context Agent
- Planner Agent
- Report Agent
- Report Quality Agent

### 6. Show Report Quality And Review

Open:

```text
Governed Report Check
Human Review Checklist
Reviewer Approval / Human Sign-off
```

Say:

> The project keeps AI output in draft status until a responsible human reviewer checks the evidence, limitations and source boundaries.

Show that the current quality result is bound to `governed-report-v2`. Explain that a policy-only reassessment of an unchanged historical report is not a human review and cannot authorise pilot-package export until a new review event is recorded.

Key point:

> This is important for government or school pilots because the product must not pretend to make official emergency decisions.

### 7. Show Data And Map Context

Go to:

```text
Data & Map
```

Show:

- Coverage Analysis Tools
- Official Source Reachability
- Official Sources
- Data Status
- Data Register
- Licence Register

Say:

> The map and data panels show the local evidence context used by the app. The official status panel is a source reachability check, not an interpretation of live warnings.

### 8. Export The Output

Go back to:

```text
Create Report
```

or:

```text
Review & Export
```

Download:

- Markdown report
- PDF report
- DOCX report
- Pilot export package

Say:

> The export package is useful for stakeholder handover because it includes the report, review metadata, data register and audit materials.

The current package uses `pilot-export-v4`. The committed Cairns Council sample passed on its first generation attempt and verifies as a 16-page PDF plus a 203-paragraph DOCX; it uses Ollama `bushfire-ready-qwen` through a local-loopback endpoint and the same RAG manifest as the release benchmarks.

### 9. Show Release Evidence

Open the committed `v0.5.0` benchmark summaries and say:

> The production RAG profile uses Top-8 and records recall 1.0000, MRR 0.9216, Top-1 0.8529 and abstention 1.0000. The separate free-text Top-5 profile records recall 0.9706, MRR 0.8922, Top-1 0.8235 and abstention 1.0000.

> All eight report cases passed the governed and RAG gates with zero safety violations. Repair rate was 0.625 and average latency was 46.77 seconds on the release machine. Grounding support was 0.9280, citation coverage 0.2687, citation precision 0.8571, numeric consistency 0.9167 and jurisdiction conflicts zero; all reports still require human evidence review.

Point out that both JSON artifacts keep every evaluation row, bind exact dataset/Git/index/model provenance, and record a stable end-of-run snapshot. The release run aborts rather than writing an artifact if those identities drift.

### 10. Close The Demo

Say:

> The current project is a working MVP for controlled demonstration and pilot scoping. The next step toward commercial or government use would be validation of the confidence rules, legal and licence review, stronger approval records, user testing, accessibility review and deployment hardening.

## Short Version

If you only have two minutes:

1. Show the app and safety boundary.
2. Load `Cairns Council pilot`.
3. Generate the report.
4. Show Evidence Trail.
5. Show Review & Export.
6. Download the pilot package.
7. Show the offline release-verifier result.
8. State the current limitation: draft planning support only, not live emergency advice.

## Backup Talking Points

### Why This Is Not Just A Chatbot

- The main workflow is form-first.
- The report follows a fixed structure.
- Intermediate agent outputs are visible.
- Data sources and limitations are documented.
- Human review and export records are built into the workflow.

### Why It Uses Ollama

- It can run locally.
- It does not require an OpenAI API key.
- It is easier to demonstrate in a student or internship setting.
- It keeps the MVP independent from paid API access.

### Why It Is Not Commercial Yet

- No formal legal review.
- No production authentication.
- No immutable approval workflow.
- No deployment hardening.
- No official procurement/security documentation.
- No real stakeholder pilot feedback yet.
