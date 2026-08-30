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
poetry run python scripts/verify_release.py --release-version 0.6.0
```

The `v0.6.0` evidence set is tied to source commit `44d0c3f1f8c78af4291f79b090eb3fc53da95ea7`, exact evaluation-dataset hashes, one RAG manifest, resolved model identities and `governed-report-v6`. This is an offline consistency check, not external user validation.

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

> The app runs seven deterministic Python analysis components first, asks the local Ollama model to write the report narrative, and then runs a deterministic quality component. The eight named agents are responsibility boundaries, not eight autonomous LLMs.

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

Clarify that retrieval provenance binds application inputs, the local index and returned source records. It does not prove that every narrative claim has a correct claim-level citation.

### 6. Show Report Quality And Review

Open:

```text
Governed Report Check
Human Review Checklist
Reviewer Approval / Human Sign-off
```

Say:

> The project keeps AI output in draft status until a responsible human reviewer checks the evidence, limitations and source boundaries.

Show that the current quality result is bound to `governed-report-v6`, fingerprint `b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745`. Explain that a policy-only reassessment of an unchanged historical report is not a human review and cannot authorise pilot-package export until a new review event is recorded.

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

The current package uses `pilot-export-v4`. The committed governed sample is under `examples/v0.6.0/`; it uses Ollama `bushfire-ready-qwen` through a local-loopback endpoint and the same RAG manifest as the release benchmarks.

### 9. Show Release Evidence

Open the committed `v0.6.0` benchmark summaries and say:

> The 73-question production RAG profile uses Top-8 and records recall 1.0000, MRR 0.9216, Top-1 0.8529, abstention 1.0000 and average retrieval latency 86.05 milliseconds on the release machine.

> All eight product cases passed at an average of 26.99 seconds. One controlled repair was required and succeeded; safety violations and repair exhaustion were both zero. All six red-team cases also passed, including 100% prompt-injection resistance, at a 30.45-second average. Every red-team scenario-level governed gate and the suite diagnostic gate passed; its release gate is inactive by design.

Point out that all three JSON artifacts keep their evaluation rows, bind exact dataset/Git/index provenance, and record stable provenance snapshots. The retrieval artifact binds the embedding identity; the report artifacts bind the generation-model identity and quality policy. The release run aborts rather than writing an artifact if those identities drift. Grounding and evidence-alignment results are diagnostics for human review, not semantic-truth or approval guarantees.

### 10. Close The Demo

Say:

> The current project is a working MVP for controlled demonstration and pilot scoping. No real external participant pilot has yet been completed. The next step toward commercial or government use would be validation of the confidence rules, legal and licence review, stronger approval records, user testing, accessibility review and deployment hardening.

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
- Intermediate deterministic component outputs are visible.
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
