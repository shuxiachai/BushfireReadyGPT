# BushfireReadyGPT Showcase Package

This folder already contains the main materials needed to present BushfireReadyGPT as a working MVP. Use this document as the starting point when preparing an internship presentation, portfolio review, supervisor update or early stakeholder demo.

Current visual and sample assets:

- `docs/assets/bushfire-ready-gpt-demo.webm` — 89-second local demonstration;
- `docs/assets/*.png` — current Create Report, report, evidence, map and readiness views;
- `examples/v0.6.0/` — current governed Cairns Council Markdown, PDF, DOCX and `pilot-export-v4` package;
- `docs/benchmarks/rag-retrieval-v0.6.0.json` — current 73-question structured Top-8 release gate;
- `docs/benchmarks/report-generation-v0.6.0.json` — current eight-scenario real-model product gate;
- `docs/benchmarks/report-red-team-v0.6.0.json` — current six-scenario adversarial prompt-injection diagnostic gate; its release gate is inactive by design.

Earlier sample and benchmark versions remain historical evidence,
not the current release baseline.

## v0.6.0 Evidence Snapshot

| Evidence | Current measured result |
| --- | --- |
| Benchmark source and policy | Commit `44d0c3f1f8c78af4291f79b090eb3fc53da95ea7`; `governed-report-v6` fingerprint `b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745`; `pilot-export-v4` |
| Automated validation | 885 passing checks: 884 non-E2E plus one Chromium E2E; 86.95% non-E2E `src` coverage |
| Structured RAG Top-8 | 73 questions; recall 1.0000; MRR 0.9216; Top-1 0.8529; abstention 1.0000; average 86.05 ms |
| Governed product reports | 8/8 passed; average 26.99 s; one controlled repair succeeded; zero safety violations and zero repair exhaustion |
| Adversarial reports | 6/6 passed; prompt-injection resistance 1.0000; average 30.45 s; every scenario-level governed gate and the suite diagnostic gate passed; release gate inactive by design |
| Grounding boundary | Evidence-alignment metrics are diagnostics for human review, not semantic-truth or claim-level citation guarantees |

The current sample set is committed under `examples/v0.6.0/`. Its audit binds the
provider (`ollama`), model name (`bushfire-ready-qwen`), `local_loopback` boundary
and release RAG manifest. The evaluation artifacts bind exact dataset, Git,
index and model/embedding provenance. This is application-level retrieval
provenance, not proof that every narrative claim has a correct claim-level citation.

## Recommended Reading Order

| Purpose | Document | Use it for |
| --- | --- | --- |
| First-time project explanation | `docs/project_overview.md` | Explain what the project is, what changed from the original open-source project, and what it can do now. |
| Live demo preparation | `docs/demo_walkthrough.md` | Follow a clear step-by-step demo flow during a presentation. |
| Commercial / pilot positioning | `docs/pilot_pitch.md` | Explain the problem, solution, target users, pilot scope and governance boundary. |
| Technical architecture | `docs/architecture.md` | Explain the Streamlit app, eight-role deterministic component pipeline, data flow and model runtime. |
| Current maturity and gaps | `docs/project_reassessment.md` | Explain what is already working and what is still missing before commercial use. |
| Commercial readiness | `docs/commercial_gap_assessment.md` | Discuss the gap between the MVP and a procurement-ready product. |
| Feedback collection | `docs/pilot_feedback_form.md` | Collect structured feedback from a school, council or community reviewer. |
| Controlled pilot execution | `docs/pilot_protocol.md` | Run a consistent, privacy-minimised 3-5 person evaluation. |
| Pilot evidence status | `docs/pilot_results.md` | Record anonymised measures and clearly distinguish pending from completed validation. |

## Suggested Presentation Structure

1. **Opening**
   Introduce BushfireReadyGPT as an Australia-focused bushfire preparedness planning MVP.

2. **Problem**
   Explain that schools, councils and communities often need structured preparedness planning material, but source information, local data, review status and export records are usually fragmented.

3. **Solution**
   Show the form-first workflow, deterministic component evidence trail, local data context, human review boundary and report exports.

4. **Live Demo**
   Use `docs/demo_walkthrough.md` and the Cairns Council or Cairns school pilot example.

5. **Architecture**
   Use `docs/architecture.md` to explain that eight named agent roles are deterministic Python components and only report narration calls the LLM, then cover the data layer and Ollama runtime.

6. **Current Boundary**
   Clearly state that the app does not provide live warnings, evacuation orders, fire bans or life-safety decisions.

7. **Future Path**
   Use `docs/project_reassessment.md` to explain the next steps: evidence-label validation, approval workflow, legal/licence review, user testing and deployment hardening.

## Recommended Demo Scenario

Use the built-in **Cairns Council pilot** first because it best shows the full project value:

- Council/community preparedness audience
- Queensland official source context
- ABS / ASGS geography evidence
- Deterministic eight-role component summary
- Human review and sign-off
- PDF, DOCX, Markdown and pilot package export

Use the **Cairns school pilot** as the second example if the audience cares more about campus safety and student/teacher workflows.

## What To Avoid Saying

- Do not say the tool predicts bushfires.
- Do not say it provides live emergency warnings.
- Do not say it identifies confirmed safe evacuation routes or assembly points.
- Do not say it is ready for government procurement.
- Do not present generated reports as official emergency instructions.

## Best One-Sentence Description

BushfireReadyGPT is an Australia-focused governed MVP that uses eight deterministic Python responsibility components, local hybrid RAG and one LLM report-narration step to create reviewable draft preparedness reports and audit records.

## Current Status

The project is ready for:

- Internship demonstration
- Coursework presentation
- Portfolio showcase
- Controlled stakeholder discussion
- Early pilot scoping

No real external participant pilot has yet been completed; engineering, retrieval and model regression results are not user validation.

The project is not yet ready for:

- Operational emergency use
- Public life-safety decision support
- Government procurement
- Commercial deployment without legal, security, privacy and licence review
