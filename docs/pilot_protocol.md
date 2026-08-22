# Controlled Pilot Protocol

## Status

This protocol is ready to run. External participant sessions have not yet been completed. Do not describe the project as user-validated until the anonymised results in `docs/pilot_results.md` are populated from real sessions.

## Objective

Evaluate whether BushfireReadyGPT helps a reviewer produce and assess a draft preparedness report without mistaking the product for a live warning or operational decision system.

## Participants

Recruit 3-5 adult reviewers. Aim for at least two of the following perspectives:

- council resilience, emergency-management support or community engagement;
- school safety, facilities or administration;
- community preparedness, public health or volunteer coordination;
- software, data or governance review.

Use participant codes `P01`-`P05` in project records. Keep names, contact details and employer-specific notes outside the repository. Participation should be voluntary and reviewers may stop at any time.

## Safety and Privacy Boundary

- Use only the built-in demonstration scenarios or invented, non-sensitive details.
- Do not run the pilot during an active incident or ask the app for live conditions, safe routes, fire bans, evacuation decisions or emergency instructions.
- Do not enter personal, health, student, resident or operationally sensitive information.
- Remind participants that all reports remain drafts for human review.
- Record screen or audio only with explicit consent. Written notes are the default.

## Session Format

Allow 30 minutes per participant:

1. **Introduction — 3 minutes.** Read the product and safety boundary without explaining the interface.
2. **Task flow — 15 minutes.** Ask the participant to complete the tasks below while thinking aloud.
3. **Feedback form — 8 minutes.** Complete `docs/pilot_feedback_form.md`.
4. **Debrief — 4 minutes.** Ask what must change before they would use the tool in a formal process.

## Participant Tasks

1. Start the application and load one built-in pilot example.
2. Explain, in their own words, what the product can and cannot do.
3. Generate a report and identify its draft status.
4. Find the selected geography, community evidence and at least one official source.
5. Explain the difference between O1, P2, R3, A4 and U0 evidence classes.
6. Identify one limitation that requires human verification.
7. Open the human review section and describe the approval boundary.
8. Download the pilot export package and identify its main files.

The facilitator may help only after noting where the participant became blocked.

## Measures

Record these measures for every participant:

| Measure | Collection method | Pilot target |
| --- | --- | --- |
| Task completion | Completed tasks / 8 | At least 7/8 for 80% of participants |
| Workflow time | Start to export package | 10 minutes or less, excluding first-time model downloads |
| Report usefulness | Feedback-form rating | Median at least 4/5 |
| Evidence understanding | Correct explanation of five evidence classes | At least 4/5 classes |
| Safety-boundary understanding | Correctly rejects live warning/decision use | 100% of participants |
| Export success | Pilot package downloaded and opened | 100% of participants |
| Facilitator dependence | Count of interventions after a participant becomes blocked | Record every intervention; investigate repeated blocks |
| Citation support | Citations supported / citations checked against the current official page | Record the measured rate; no invented target before calibration |
| Citation trust | Feedback-form rating after source checking | Median at least 4/5 |
| Editing effort | None / light / partial rewrite / major rewrite | Majority should require no more than light edits |
| Critical safety issue | Facilitator severity assessment | Zero unresolved critical issues |

## Issue Severity

- **Critical:** could encourage unsafe operational use, conceal the draft boundary or expose sensitive data.
- **High:** prevents report generation, evidence review or export, or materially misstates provenance.
- **Medium:** causes task failure but has a clear workaround.
- **Low:** wording, visual or convenience issue that does not prevent task completion.

Critical findings stop the pilot until corrected. High findings must be resolved or explicitly accepted before a wider pilot.

## Facilitator Record

For each session, record:

- participant code and perspective;
- selected scenario and geography;
- start/end time and task outcomes;
- points where help was needed;
- feedback-form ratings and comments;
- issue IDs with severity;
- participant consent for any quotation, using anonymised wording only.

Store raw notes outside Git. Add only anonymised aggregates and non-identifying quotations to `docs/pilot_results.md`.

Enter repository-safe measurements in a copy of `docs/pilot_evaluation_template.json`.
The machine-readable contract accepts only anonymous participant codes, bounded
numbers, booleans and controlled categories. It rejects additional fields such as
names, emails, phone numbers and free-text notes. Calculate the aggregate summary
with:

```powershell
poetry run python scripts\evaluate_pilot_results.py --input path\to\anonymous-pilot.json --output output\pilot-summary.json
```

Raw notes, consent records, quotations and identifying organisational context must
remain in an access-controlled location outside Git. Do not commit the generated
summary until it has been manually checked against those source records.

## Bad Case Regression Workflow

1. Assign every material finding a `BC-001`-style ID and severity.
2. Record only its anonymous category, short non-identifying title, participant code(s), owner role and disposition.
3. Add a deterministic regression test for every fixed Critical or High finding where automation is feasible.
4. Store the `tests/...py::test_name` reference in the Bad Case record.
5. Re-run the affected test plus the full non-E2E suite before marking the finding Fixed.

The repository-safe Bad Case register is an index, not the complete research
record. Detailed notes stay outside Git.

## Completion Gate

The controlled pilot is complete only when:

- at least three real participants have completed the session;
- all required measures have been recorded;
- every critical/high finding has an owner and disposition;
- results and limitations have been summarised without invented data;
- the README and readiness assessment use wording consistent with the evidence.
