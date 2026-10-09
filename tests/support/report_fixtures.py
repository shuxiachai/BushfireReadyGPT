"""Pure report fixtures shared by content-contract consumers."""

from tests.support.model_evidence_fixtures import _analysis


def with_owned_field_selectors(analysis):
    """Add explicit synthetic selector inputs to older non-selector unit fixtures."""
    from copy import deepcopy

    if not isinstance(analysis, dict):
        return analysis
    result = deepcopy(analysis)
    profile = result.setdefault("profile", {})
    if not profile.get("scenario_concept"):
        profile["scenario_concept"] = {"id": "community_workshop"}
    if not profile.get("timeframe_concept"):
        profile["timeframe_concept"] = {"id": "seven_day"}
    return result


def _valid_report():
    """Current synthetic organisational draft; no fabricated external facts."""
    from src.report_owned_fields import assemble_owned_fields
    from src.source_attribution import canonicalise_model_source_section, expand_known_attribution_tokens

    analysis = _analysis()
    narrative = """# 1. Title
Synthetic Community Preparedness Planning Draft

## 2. Executive Summary
This synthetic planning draft presents an organisational review agenda for a hypothetical community. It contains no verified local operating arrangements, current incident information or nominated destinations. The audience is the responsible organisation and its appointed reviewers. The document records evidence gaps and proposed confirmation work before any formal organisational use. Every listed responsibility remains subject to local confirmation and accountable review. Review outcomes, supporting records, unresolved questions and decision dates remain incomplete until the responsible organisation records its findings.

## 3. Purpose and Scope
The scope is a community workshop and preparedness discussion over seven days, with evacuation planning, communication and first aid as review topics. This document is not emergency advice or an instruction to move people. Local decisions, responsibilities and procedures remain outside the verified information supplied for this example. Its administrative timetable is a proposal for review, with no claim about the effects of any measure. This draft covers the application-recognised community workshop scenario.

## 4. Selected Geography and Key Assumptions
No site address, map boundary, occupancy figure or community dataset was supplied for this hypothetical example. Geographic applicability remains unknown. The responsible organisation has not approved the assumptions, proposed roles or review timetable. An exact premises boundary and the intended participant group remain matters for local verification before further planning can proceed.

[APP_P2_FIELDS]

## 5. Data Sources and Limitations
The source register contains verification entry points only, with no submitted passage supporting a local operational arrangement. No live warning feed or current road information is available. Source currency, geographic applicability and organisational relevance remain unresolved review matters. The report's prose is draft synthesis, not a substitute for the original evidence or responsible-authority advice.

## 6. Local Risk Context
Bushfire, smoke, heat, road access, power and communication are topics for the proposed review agenda. Their local occurrence, severity and effects are unknown in this example. No causal assessment of this hypothetical community is established by the available information. Any later assessment belongs with qualified reviewers using appropriate evidence and current official information.

## 7. Preparedness Priorities
Unverified proposal for local review: the responsible organisation must confirm the evacuation, first aid and communication priorities, including the evidence needed for each topic and the accountable reviewer for outstanding questions.

## 8. Evacuation Planning
Local warning procedures, candidate routes, movement arrangements and accountability processes are not supplied. No destination or route is verified. Unverified proposal for local review: the responsible organisation must confirm a process for obtaining authorised advice on notification, movement, assisted transport and participant accountability before any operational use.

## 9. Candidate Assembly Point Criteria
Physical assembly criteria are unknown and no candidate venue has been verified. Unverified proposal for local review: the responsible organisation must confirm which authority will provide applicable criteria and which records will be needed for a later venue assessment.

## 10. Roles and Responsibilities
These role labels describe review responsibilities and have no confirmed appointment status.

[APP_ROLE_FIELDS]

## 11. Communication and Inclusion Needs
Internal notification, accessible public information and backup communication arrangements are unknown. Unverified proposal for local review: the communications officer must confirm channel ownership, participant needs and the process for checking current official warning information.

## 12. First Aid, Training and Exercises
First aid readiness, smoke and heat support, AED and burn preparedness, training qualifications and exercise frequency are unknown. Unverified proposal for local review: the first aid coordinator must confirm qualified reviewers, evidence requirements and exercise records.

## 13. Action Plan
[APP_ACTION_FIELDS]

## 14. Human Review and Approval Checklist
[APP_REVIEW_FIELDS]

## 15. Safety Disclaimer
This draft does not establish operational safety. Live warnings, fire bans, evacuation orders and life-safety decisions must come from official emergency services. Call 000 in a life-threatening emergency.
"""
    narrative = assemble_owned_fields(narrative, analysis)
    narrative = canonicalise_model_source_section(
        narrative, official_sources=analysis["data"]["sources"], rag_sources=[]
    )
    narrative = expand_known_attribution_tokens(narrative, official_sources=analysis["data"]["sources"], rag_sources=[])
    return narrative, analysis
