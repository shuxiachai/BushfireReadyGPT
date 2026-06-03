# BushfireReadyGPT Showcase Package

This folder already contains the main materials needed to present BushfireReadyGPT as a working MVP. Use this document as the starting point when preparing an internship presentation, portfolio review, supervisor update or early stakeholder demo.

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
   Use `docs/project_reassessment.md` to explain the next steps: data-confidence labels, approval workflow, legal/licence review, user testing and deployment hardening.

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
