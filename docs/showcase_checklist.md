# Showcase Checklist

Use this checklist before presenting BushfireReadyGPT.

## 1. Local Setup

- [ ] Ollama is installed.
- [ ] The configured Ollama model is available.
- [ ] `.env` exists and points to the local Ollama endpoint.
- [ ] `Start BushfireReadyGPT.bat` completes its environment checks.
- [ ] Re-running the launcher reopens the existing app instead of starting a duplicate.
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
- [ ] You can explain O1 official references, P2 processed data, R3 rule inference, A4 AI draft and U0 unverified inputs.
- [ ] The Governed Report Check appears after report generation.
- [ ] The Human Review Checklist is visible.
- [ ] Reviewer Approval / Human Sign-off can be explained.
- [ ] The audit path or audit record is available after generation.
- [ ] You can identify the `governed-report-v2` policy binding and explain that policy-only reassessment is not human review or export approval.

## 4. Data And Map

- [ ] The `Data & Map` tab opens.
- [ ] Geography / coverage controls are visible.
- [ ] Official Sources are visible.
- [ ] Official Source Reachability is visible.
- [ ] Data Status / Data Sources are visible.
- [ ] Licence Register is visible.
- [ ] You can explain that the map is not a live fire map.

## 5. Export

- [ ] Markdown download is available.
- [ ] PDF download is available.
- [ ] DOCX download is available.
- [ ] Pilot export package download is available.
- [ ] The package reports `pilot-export-v4` and verifies its hashes, policy and governed gate.
- [ ] You can explain what each export is for.

## 6. Talking Points

- [ ] One-sentence pitch is ready.
- [ ] You can explain why this is not just a chatbot.
- [ ] You can explain the multi-agent pipeline.
- [ ] You can explain the current data layer.
- [ ] You can explain the human review boundary.
- [ ] You can explain that evidence codes describe provenance, not live incident severity or fire danger.
- [ ] You can explain why it is demo/pilot-ready but not government-procurement-ready.

## 7. Safety Boundary

Before presenting, be ready to say:

> BushfireReadyGPT does not provide live fire conditions, fire bans, evacuation orders, confirmed safe routes or life-safety decisions. It is a preparedness planning and draft reporting tool. In a real emergency, users must follow official emergency services and call 000 if life is at risk.

## 8. Current `v0.5.0` Project Proof Points

- [ ] The release artifacts identify clean source commit `e02f076`.
- [ ] The local verification passes 428 non-E2E tests plus one Chromium E2E (429 total), with 86.08% non-E2E `src` coverage.
- [ ] Structured Top-8 RAG records recall 1.0000, MRR 0.9216, Top-1 0.8529 and abstention 1.0000.
- [ ] Free-text Top-5 RAG records recall 0.9706, MRR 0.8922, Top-1 0.8235 and abstention 1.0000.
- [ ] All eight report cases pass the governed and RAG gates with zero safety violations; repair rate is 0.625 and average release-machine latency is 46.77 seconds.
- [ ] Grounding metrics are support 0.9280, citation coverage 0.2687, citation precision 0.8571, numeric consistency 0.9167 and zero jurisdiction conflicts; all eight reports remain human-review-required.
- [ ] Both evaluation JSON files include every row and exact dataset, Git, index, model/embedding and quality-policy provenance, with a stable end-of-run drift check.
- [ ] `poetry run python scripts/verify_release.py` verifies the release evidence offline.
- [ ] The Cairns sample records one generation attempt, a 16-page PDF, 203 DOCX paragraphs, `pilot-export-v4`, Ollama `bushfire-ready-qwen`, a local-loopback boundary and the release RAG manifest.
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
- Re-run `Start BushfireReadyGPT.bat`.

If export fails:

- Continue with Markdown preview.
- Explain that PDF/DOCX exports are included for pilot handover but the key project value is the report workflow, evidence trail and human review boundary.
