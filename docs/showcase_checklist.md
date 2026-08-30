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
- [ ] You can identify the `governed-report-v6` policy binding and explain that policy-only reassessment is not human review or export approval.

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
- [ ] You can explain that the eight named agent roles are deterministic Python components, not eight autonomous LLMs, and that only report narration calls the LLM.
- [ ] You can explain the current data layer.
- [ ] You can explain the human review boundary.
- [ ] You can explain that evidence codes describe provenance, not live incident severity or fire danger.
- [ ] You can explain why it is demo/pilot-ready but not government-procurement-ready.

## 7. Safety Boundary

Before presenting, be ready to say:

> BushfireReadyGPT does not provide live fire conditions, fire bans, evacuation orders, confirmed safe routes or life-safety decisions. It is a preparedness planning and draft reporting tool. In a real emergency, users must follow official emergency services and call 000 if life is at risk.

## 8. Current `v0.6.0` Project Proof Points

- [ ] The release artifacts identify clean source commit `44d0c3f1f8c78af4291f79b090eb3fc53da95ea7`.
- [ ] The release verification passes 884 non-E2E tests plus one Chromium E2E, with 86.95% non-E2E `src` coverage.
- [ ] `governed-report-v6` has fingerprint `b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745`.
- [ ] The 73-question structured Top-8 RAG gate records recall 1.0000, MRR 0.9216, Top-1 0.8529, abstention 1.0000 and average latency 86.05 ms.
- [ ] All 8/8 product cases pass at a 26.99-second average; one controlled repair succeeds, with zero safety violations and zero repair exhaustion.
- [ ] All 6/6 red-team cases pass at a 30.45-second average, including 100% prompt-injection resistance, passing scenario-level governed gates and a passing suite diagnostic gate; its release gate is inactive by design.
- [ ] Grounding and evidence-alignment results are described as diagnostics that require human review, not proof of semantic truth.
- [ ] RAG provenance is described as application-level retrieval provenance, not claim-level citation accuracy.
- [ ] All three evaluation JSON files include their rows and exact dataset, Git and RAG-index provenance, with drift checks; the retrieval artifact binds the embedding identity, while both report artifacts bind the generation-model identity and quality-policy fingerprint.
- [ ] `poetry run python scripts/verify_release.py --release-version 0.6.0` verifies the release evidence offline.
- [ ] The governed showcase sample is available under `examples/v0.6.0/` and binds `pilot-export-v4`, Ollama `bushfire-ready-qwen`, a local-loopback boundary and the release RAG manifest.
- [ ] You state that no real external participant pilot has been completed; automated evaluations are not user validation.
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
