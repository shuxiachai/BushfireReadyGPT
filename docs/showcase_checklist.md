# Showcase Checklist

Use this checklist before presenting BushfireReadyGPT.

## 1. Local Setup

- [ ] Ollama is installed.
- [ ] The configured Ollama model is available.
- [ ] `.env` exists and points to the local Ollama endpoint.
- [ ] The VSCode task `Start BushfireReadyGPT` is available.
- [ ] The app starts from `start_app.ps1`.
- [ ] The browser opens a local Streamlit URL.

## 2. Core Demo Flow

- [ ] The homepage loads without Streamlit errors.
- [ ] The sidebar safety boundary is visible.
- [ ] The `Create Report` tab is visible.
- [ ] The `Cairns Council pilot` example can be loaded.
- [ ] The report can be generated.
- [ ] The latest report preview appears.
- [ ] The report includes draft status, evidence tables, human review and safety disclaimer sections.

## 3. Evidence And Review

- [ ] The `Review & Export` tab opens.
- [ ] The Evidence Trail is available after report generation.
- [ ] The Report Quality Check appears after report generation.
- [ ] The Human Review Checklist is visible.
- [ ] Reviewer Approval / Human Sign-off can be explained.
- [ ] The audit path or audit record is available after generation.

## 4. Data And Map

- [ ] The `Data & Map` tab opens.
- [ ] Geography / coverage controls are visible.
- [ ] Official Sources are visible.
- [ ] Official Status Panel is visible.
- [ ] Data Status / Data Sources are visible.
- [ ] Licence Register is visible.
- [ ] You can explain that the map is not a live fire map.

## 5. Export

- [ ] Markdown download is available.
- [ ] PDF download is available.
- [ ] DOCX download is available.
- [ ] Pilot export package download is available.
- [ ] You can explain what each export is for.

## 6. Talking Points

- [ ] One-sentence pitch is ready.
- [ ] You can explain why this is not just a chatbot.
- [ ] You can explain the multi-agent pipeline.
- [ ] You can explain the current data layer.
- [ ] You can explain the human review boundary.
- [ ] You can explain why it is demo/pilot-ready but not government-procurement-ready.

## 7. Safety Boundary

Before presenting, be ready to say:

> BushfireReadyGPT does not provide live fire conditions, fire bans, evacuation orders, confirmed safe routes or life-safety decisions. It is a preparedness planning and draft reporting tool. In a real emergency, users must follow official emergency services and call 000 if life is at risk.

## 8. Current Project Proof Points

- [ ] Git baseline commit exists.
- [ ] Tests pass.
- [ ] README explains setup and structure.
- [ ] Project overview document exists.
- [ ] Demo walkthrough exists.
- [ ] Commercial gap assessment exists.
- [ ] Pilot pitch exists.
- [ ] Feedback form exists.

## 9. If Something Goes Wrong During Demo

If report generation is slow:

- Explain that the local model is running through Ollama and may take time depending on the computer.
- Show the existing demo documents and explain the workflow.

If the model does not respond:

- Check that Ollama is running.
- Check that the model in `.env` is installed.
- Restart from VSCode task.

If export fails:

- Continue with Markdown preview.
- Explain that PDF/DOCX exports are included for pilot handover but the key project value is the report workflow, evidence trail and human review boundary.
