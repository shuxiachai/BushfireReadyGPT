# Demo Scenario Pack

These scenarios are built into the Streamlit app under **Demo Mode / Sample Scenario Pack**. They are intended for controlled walkthroughs, internship demonstrations and early stakeholder discussions.

In `v0.6.0`, the eight named agent roles are deterministic Python components rather than autonomous LLM agents. Seven components prepare evidence and planning context, the local LLM writes the report narrative, and the eighth component applies the governed quality checks. RAG records provide application-level retrieval provenance, not claim-level citation accuracy; grounding results are diagnostic and require human review.

Each demo card has two actions:

- **Load** fills the form and sets the matching map geography.
- **Generate** fills the form, sets the map geography, runs the eight-role deterministic component analysis and creates a draft report with evidence tables, sign-off section and audit record.

## Cairns Council Executive Demo

- Audience: Council / community resilience team
- Map selection: Queensland / SA4 / Cairns
- Goal: Show a council-style draft report with evidence tables, source register, review status and export package.
- Expected export: Council-ready pilot package for stakeholder review.

Talking points:

- All outputs are draft planning support, not emergency directions.
- The selected SA4 geography is linked to ABS ASGS and LGA reference data.
- The pilot package includes report exports, audit JSON, data register and reviewer sign-off.

## Cairns School Campus Demo

- Audience: School leadership / campus safety team
- Map selection: Queensland / SA4 / Cairns
- Goal: Show a school-focused preparedness report covering evacuation, candidate assembly points, first aid and staff roles.
- Expected export: School pilot report with reviewer sign-off and evidence tables.

Talking points:

- Candidate assembly points are presented as criteria requiring local approval.
- Student, teacher, parent communication and first-aid readiness are foregrounded.
- The report remains a draft until reviewed by the responsible school or organisation.

## Remote Queensland Community Demo

- Audience: Remote community / local services / council officers
- Map selection: Queensland / SA4 / Queensland - Outback
- Goal: Show how the tool supports remote-area planning where roads, communications and service access are key constraints.
- Expected export: Community workshop package for controlled pilot discussion.

Talking points:

- The selected geography uses Queensland - Outback as a demonstration area.
- The report emphasises early planning, backup communications and welfare checks.
- Official sources must still be checked for current warnings and local emergency instructions.

## v0.6.0 Regression Boundary

The formal product suite is broader than these three presentation cards: it covers all six planning scenarios, live-request refusal and no-RAG degradation. All `8/8` product cases passed with one successful controlled repair, zero safety violations and zero repair exhaustion. The separate adversarial suite passed `6/6`, including `100%` prompt-injection resistance. Governed samples are committed under `examples/v0.6.0/`.

These are engineering and model-regression results. No real external participant pilot has yet been completed, so the scenarios must not be presented as evidence of user validation or operational readiness.
