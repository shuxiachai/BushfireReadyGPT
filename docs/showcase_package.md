# BushfireReadyGPT Showcase Package

This folder already contains the main materials needed to present BushfireReadyGPT as a working MVP. Use this document as the starting point when preparing an internship presentation, portfolio review, supervisor update or early stakeholder demo.

Current visual and sample assets:

- `docs/assets/bushfire-ready-gpt-demo.webm` — 89-second local demonstration;
- `docs/assets/*.png` — current Create Report, report, evidence, map and readiness views;
- `examples/v0.5.0/` — current governed Cairns Council Markdown, PDF, DOCX and `pilot-export-v4` package;
- `docs/benchmarks/rag-retrieval-v0.5.0.json` — current structured Top-8 release gate and free-text Top-5 diagnostic;
- `docs/benchmarks/report-generation-v0.5.0.json` — current eight-scenario real-model release gate with diagnostic grounding metrics.

The v0.3.0 sample and v0.3.0/v0.4.0 report artifacts remain historical evidence,
not the current release baseline.

## v0.5.0 Evidence Snapshot

| Evidence | Current measured result |
| --- | --- |
| Benchmark source and policy | Commit `e02f076`; `governed-report-v2` fingerprint `7c20b6fa...a5da9d1`; `pilot-export-v4` |
| Automated validation | 429 passing tests: 428 non-E2E plus one Chromium E2E; 86.08% coverage |
| Structured RAG Top-8 | 73 questions (68 answerable + 5 safety negatives); recall 1.0000; MRR 0.9216; Top-1 0.8529; abstention 1.0000; average/p95 130.36/157.49 ms |
| Free-text RAG Top-5 | 84 questions (68 answerable + 16 negatives); recall 0.9706; MRR 0.8922; Top-1 0.8235; abstention 1.0000; average/p95 131.59/159.00 ms |
| Governed reports | Eight scenarios; governed, structural, evidence, RAG attribution, RAG behaviour and topic rates 1.0000; safety and unsafe-live rates 0.0000; repair 0.6250; average 46.77 s |
| Grounding diagnostics | Support 0.9280; citation coverage 0.2687; precision 0.8571; numeric consistency 0.9167; zero jurisdiction conflicts; all cases require human review |

The current sample passed on its first generation attempt and contains a 16-page PDF
and a 203-paragraph DOCX. Its audit binds the provider (`ollama`), model name
(`bushfire-ready-qwen`), `local_loopback` boundary and release RAG manifest. The
sample does not bind a model digest; only the real-model benchmark artifact records
its own model identity and digest.

## Recommended Reading Order

| Purpose | Document | Use it for |
| --- | --- | --- |
| First-time project explanation | `docs/project_overview.md` | Explain what the project is, what changed from the original open-source project, and what it can do now. |
| Live demo preparation | `docs/demo_walkthrough.md` | Follow a clear step-by-step demo flow during a presentation. |
| Commercial / pilot positioning | `docs/pilot_pitch.md` | Explain the problem, solution, target users, pilot scope and governance boundary. |
| Technical architecture | `docs/architecture.md` | Explain the Streamlit app, multi-agent pipeline, data flow and model runtime. |
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
   Show the form-first workflow, multi-agent evidence trail, local data context, human review boundary and report exports.

4. **Live Demo**
   Use `docs/demo_walkthrough.md` and the Cairns Council or Cairns school pilot example.

5. **Architecture**
   Use `docs/architecture.md` to explain the agents, data layer and Ollama runtime.

6. **Current Boundary**
   Clearly state that the app does not provide live warnings, evacuation orders, fire bans or life-safety decisions.

7. **Future Path**
   Use `docs/project_reassessment.md` to explain the next steps: evidence-label validation, approval workflow, legal/licence review, user testing and deployment hardening.

## Recommended Demo Scenario

Use the built-in **Cairns Council pilot** first because it best shows the full project value:

- Council/community preparedness audience
- Queensland official source context
- ABS / ASGS geography evidence
- Multi-agent summary
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

BushfireReadyGPT is an Australia-focused multi-agent MVP that helps councils, schools and communities generate draft bushfire preparedness reports with local evidence, official-source references, human review controls and exportable audit records.

## Current Status

The project is ready for:

- Internship demonstration
- Coursework presentation
- Portfolio showcase
- Controlled stakeholder discussion
- Early pilot scoping

The project is not yet ready for:

- Operational emergency use
- Public life-safety decision support
- Government procurement
- Commercial deployment without legal, security, privacy and licence review
