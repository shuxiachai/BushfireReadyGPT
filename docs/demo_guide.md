# BushfireReadyGPT Demo Guide

## One-Sentence Pitch

BushfireReadyGPT is an Australia-focused multi-agent prototype that turns a location, audience, scenario and planning focus into a structured bushfire preparedness report using local Ollama, ABS-derived community context and a human review workflow.

## Recommended Demo Flow

1. Start the app from VSCode.
2. Open the report form.
3. Select a pilot example and click `Load example`, or enter your own organisation, location, audience, scenario and focus areas.
4. Generate the report.
5. Show the `Evidence Trail` panel and explain how each agent contributes.
6. Show the `Data Status / Data Sources` panel and point out the processed ABS data.
7. Show the `Map and Data Table Analysis` panel. Switch between State, SA4, SA3 and SA2 to demonstrate all-Australia offline geography selection.
8. Regenerate the report and explain that the selected map area is used by the Community Vulnerability Agent.
9. Show the `Data Register` panel.
10. Show the `Human Review Checklist` panel and explain that AI output is treated as a draft.
11. Show the `Report Quality Check` panel.
12. Download the report as Markdown, PDF or DOCX.
13. Download the audit JSON for reviewer records.
14. Ask a follow-up question in the chat box, for example: `Rewrite this plan for an orientation week evacuation drill.`

## What To Emphasise

- The project does not require an OpenAI API key; it runs through local Ollama.
- The old United States wildfire data has been archived and is not used as Australian evidence.
- The current data pipeline separates raw and processed data.
- The application exposes intermediate agent analysis rather than hiding everything inside one chatbot response.
- The map selector provides visible geographic evidence behind the report.
- The government pilot workflow keeps output in draft status, adds a data register and saves an audit JSON record.
- The output is a structured report, not an informal chat answer.

## Honest Limitations

- The system does not read live warnings, evacuation orders or current fire incidents.
- Some regional matching may still need official correspondence-file validation before operational use.
- Transport and vulnerability indicators depend on the available ABS-derived dataset.
- Generated reports require human review before formal school, council or community use.
- The tool must not be presented as an emergency command, control or life-safety system.

## Suggested Next Extension

Run a small pilot around one user group:

- Council community resilience officer.
- School emergency coordinator.
- Community workshop facilitator.

For that pilot, collect:

- Whether the report structure is useful.
- Which official sources reviewers actually need.
- Which data fields are missing.
- Whether the evidence trail is understandable.
- Whether PDF, DOCX and audit JSON outputs are sufficient for internal review.
