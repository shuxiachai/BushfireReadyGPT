# Five-Minute Demo Script

## Goal

Show that BushfireReadyGPT is not just a chatbot. It is a structured, Australia-focused preparedness planning prototype with geography selection, multi-agent evidence, human review controls and exportable reports.

## Setup

Open the app from VSCode:

```text
Ctrl + Shift + P
Tasks: Run Task
Start BushfireReadyGPT
```

Use this pilot scenario:

- Pilot mode: Council Community Preparedness
- Organisation: Cairns Regional Council pilot
- Location: Cairns, Queensland
- Audience: Council officers and community resilience staff
- Scenario: Council community preparedness
- Focus areas: Evacuation, Candidate assembly points, Communication channels, Official information sources, Human review and approval
- Timeframe: This-month preparedness plan

## Script

The Streamlit app now includes an in-app **Presentation Mode / Demo Script** section. Use the page version during live demonstrations, and keep this document as the offline reference.

### 1. Introduce the product

Say:

> BushfireReadyGPT is an Australia-focused preparedness planning assistant. It helps a council, school or community team create a draft bushfire preparedness report, while keeping official emergency decisions outside the tool.

Point to:

- Sidebar safety boundary.
- Government Pilot Mode.
- Report form.

### 2. Generate a report

Fill the form or load the council pilot example.

Say:

> The input is structured because the goal is not open-ended chatting. The system needs the location, audience, scenario, focus areas and reviewer context to produce a useful draft.

Click `Generate report`.

### 3. Explain the report output

Point to the Latest Report Preview.

Say:

> The output is a formal English draft report. It includes purpose, geography, data limitations, local risk context, evacuation planning, candidate assembly point criteria, roles, communications, training, action planning and a safety disclaimer.

### 4. Show the Evidence Trail

Open `Evidence Trail`.

Say:

> The report is supported by a local multi-agent pipeline. The Profile Agent structures the input, the Australian Data Agent selects official sources, the Community Vulnerability Agent reads ABS-derived data, the Risk Context Agent matches local risk rules, and the Planner Agent turns these into planning priorities.

### 5. Show map and data context

Open `Map and Data Table Analysis`.

Switch State / SA4 / SA3 / SA2.

Say:

> The map is not a live fire map. It shows the selected ABS geography used for community context. Selecting a geography affects the community profile evidence used by the report.

### 6. Show governance controls

Open:

- Data Register
- Human Review Checklist
- Report Quality Check

Say:

> For a government or school pilot, the AI output is always a draft. The reviewer can see data sources, limitations, quality checks and the audit record before approving any content.

### 7. Export

Download:

- PDF report
- DOCX report
- Audit JSON

Say:

> The export formats support review workflows. PDF is useful for sharing, DOCX is useful for editing, and audit JSON records the inputs, map selection, agent analysis and quality checks.

## Closing Line

> The current version is an MVP for preparedness planning and stakeholder feedback. The next production step would be verified official data feeds, stronger governance, user accounts and deployment hardening.

## Expected Questions

### Does it provide live warnings?

No. It is a preparedness planning tool. Live warnings, fire bans and evacuation orders must come from official emergency services.

### Can it be used by government now?

It can support a controlled pilot or demonstration. It is not yet ready for operational procurement without legal, data, security and deployment review.

### Why multi-agent?

The multi-agent structure makes the workflow explainable: input profiling, source selection, community context, risk matching, planning, reporting and quality checking are separated.
