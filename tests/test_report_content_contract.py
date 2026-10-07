"""Offline content guards use synthetic passages and mocked SDK transport only."""

from copy import deepcopy

import pytest

from src.model_evidence import EvidenceResponse, bind_normalized_narrative
from src.report_claim_evidence import extract_body_claims
from src.report_content_contract import evaluate_report_content_contract
from src.report_generation_quality import assess_generated_narrative, evaluate_governed_report
from src.report_template import (
    GOVERNANCE_NOTICE_MARKDOWN,
    REQUIRED_DAY_ONE_ACTION,
    append_evidence_tables,
    append_human_signoff,
    apply_governance_notice,
)
from src.source_attribution import format_rag_attribution
from tests.test_model_evidence import _analysis, _capture, _chunk


def _checks(text, analysis=None, snapshot=None):
    return {
        item["name"]: item for item in evaluate_report_content_contract(text, analysis or {}, model_evidence=snapshot)
    }


def _codes(check):
    return {item["code"] for item in check["findings"]}


def _community():
    return {
        "community": {
            "matched_location": "Synthetic district",
            "indicators": {
                "population": 172888,
                "older_people_pct": 15.6,
                "no_car_households_pct": None,
                "language_other_than_english_pct": None,
                "geography_type": "lga_approximation",
                "matched_sa2_count": 22,
            },
            "data_quality": {"source_period": "2021 Census and 2022 ERP"},
        }
    }


def _p2_text():
    return (
        "## 4. Selected Geography and Key Assumptions\n"
        "Community population is 172,888 and older people represent 15.6% in the approximate 22-SA2 "
        "aggregation (2021 Census and 2022 ERP) [P2].\n"
        "Transport and language measurements remain unknown."
    )


def _valid_report():
    """Current synthetic organisational draft; no fabricated external facts."""
    from src.source_attribution import canonicalise_model_source_section, expand_known_attribution_tokens

    analysis = _analysis()
    narrative = """# 1. Title
Synthetic Community Preparedness Planning Draft

## 2. Executive Summary
This synthetic planning draft presents an organisational review agenda for a hypothetical community. It contains no verified local operating arrangements, current incident information or nominated destinations. The audience is the responsible organisation and its appointed reviewers. The document records evidence gaps and proposed confirmation work before any formal organisational use. Every listed responsibility remains subject to local confirmation and accountable review. Review outcomes, supporting records, unresolved questions and decision dates remain incomplete until the responsible organisation records its findings.

## 3. Purpose and Scope
The scope is preparedness discussion over seven days, with evacuation planning, communication and first aid as review topics. This document is not emergency advice or an instruction to move people. Local decisions, responsibilities and procedures remain outside the verified information supplied for this example. Its administrative timetable is a proposal for review, with no claim about the effects of any measure.

## 4. Selected Geography and Key Assumptions
No site address, map boundary, occupancy figure or community dataset was supplied for this hypothetical example. Geographic applicability remains unknown. The responsible organisation has not approved the assumptions, proposed roles or review timetable. An exact premises boundary and the intended participant group remain matters for local verification before further planning can proceed.

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

| Role | Responsibility |
| --- | --- |
| Planning lead | Unverified proposal for local review: the responsible organisation must confirm the review owner and backup. |

## 11. Communication and Inclusion Needs
Internal notification, accessible public information and backup communication arrangements are unknown. Unverified proposal for local review: the communications officer must confirm channel ownership, participant needs and the process for checking current official warning information.

## 12. First Aid, Training and Exercises
First aid readiness, smoke and heat support, AED and burn preparedness, training qualifications and exercise frequency are unknown. Unverified proposal for local review: the first aid coordinator must confirm qualified reviewers, evidence requirements and exercise records.

## 13. Action Plan
Unverified proposal for local review: Day 1: the responsible organisation must confirm the preparedness lead, official contacts, action owners and review checkpoints.

## 14. Human Review and Approval Checklist
- [ ] Unverified proposal for local review: the responsible organisation must confirm the evidence gaps and record the approval decision.

## 15. Safety Disclaimer
This draft does not establish operational safety. Live warnings, fire bans, evacuation orders and life-safety decisions must come from official emergency services. Call 000 in a life-threatening emergency.
"""
    narrative = canonicalise_model_source_section(
        narrative, official_sources=analysis["data"]["sources"], rag_sources=[]
    )
    narrative = expand_known_attribution_tokens(narrative, official_sources=analysis["data"]["sources"], rag_sources=[])
    return narrative, analysis


def test_complete_current_synthetic_draft_passes_without_erasing_required_available_facts():
    narrative, analysis = _valid_report()
    quality = assess_generated_narrative(narrative, analysis)
    assert quality["approval_gate"]["passed"] is True, quality["approval_gate"]["blocking_failures"]


@pytest.mark.parametrize("count,passed", [(649, False), (650, True), (800, True), (801, False)])
def test_word_budget_counts_all_authored_words_and_excludes_appendices(count, passed):
    text = " ".join(["planning"] * count)
    full = GOVERNANCE_NOTICE_MARKDOWN + "\n" + text + "\n## Evidence Tables\n" + "ignored " * 500
    check = _checks(full)["Narrative word budget"]
    assert (check["status"] == "pass") is passed
    assert check["word_count"] == count


def test_p2_positive_retains_useful_facts_without_external_evidence():
    assert _checks(_p2_text(), _community())["Processed community provenance"]["status"] == "pass"


def _p2_basis_text():
    return (
        _p2_text()
        .replace("population is", "population basis is")
        .replace("older people represent", "older-people share is")
    )


def test_p2_population_basis_and_hyphenated_older_people_keep_exact_values_and_units():
    assert _checks(_p2_basis_text(), _community())["Processed community provenance"]["status"] == "pass"


@pytest.mark.parametrize(
    "old,new",
    [
        ("172,888", "15.6"),
        ("15.6%", "172,888%"),
        ("172,888", "172,888%"),
        ("15.6%", "15.6"),
        ("172,888", "172,888 and population basis is 42"),
    ],
)
def test_new_measure_labels_do_not_relax_value_or_unit_binding(old, new):
    check = _checks(_p2_basis_text().replace(old, new), _community())["Processed community provenance"]
    assert "p2_value_mismatch" in _codes(check)


@pytest.mark.parametrize(
    "body,expected",
    [
        (
            "The matched geography is an approximate 22-SA2 aggregation [P2]. "
            "The population basis is 172,888 and older-people share is 15.6%, "
            "drawn from 2021 Census and 2022 ERP fields [P2].",
            {"p2_geographic_basis_missing", "p2_aggregation_limit_missing"},
        ),
        (
            "The population basis is 172,888 and older-people share is 15.6% in the approximate 22-SA2 aggregation. "
            "The source period is 2021 Census and 2022 ERP [P2].",
            {"p2_adjacent_provenance_missing", "p2_period_missing"},
        ),
    ],
)
def test_new_measure_labels_cannot_borrow_basis_from_adjacent_sentence(body, expected):
    text = "## 4. Selected Geography and Key Assumptions\n" + body + " Transport and language remain unknown."
    codes = _codes(_checks(text, _community())["Processed community provenance"])
    assert "p2_available_fact_omitted" not in codes
    assert expected <= codes


@pytest.mark.parametrize(
    "old,new,code",
    [
        (" [P2]", "", "p2_adjacent_provenance_missing"),
        ("2021 Census and 2022 ERP", "old ABS data", "p2_period_missing"),
        ("22-SA2", "Cairns", "p2_geographic_basis_missing"),
        ("172,888", "170,000", "p2_value_mismatch"),
        ("Transport and language measurements remain unknown.", "", "p2_unknown_measurement_omitted"),
    ],
)
def test_each_p2_occurrence_requires_own_exact_basis(old, new, code):
    check = _checks(_p2_text().replace(old, new), _community())["Processed community provenance"]
    assert code in _codes(check)


def test_p2_bare_repeat_is_not_covered_by_an_earlier_qualified_sentence():
    text = _p2_text() + "\n## 6. Local Risk Context\nThe population is 172,888."
    assert "p2_adjacent_provenance_missing" in _codes(_checks(text, _community())["Processed community provenance"])


def test_p2_cannot_pass_by_omitting_all_facts_or_marking_them_unknown():
    for text in (
        "All local data are unverified.",
        "Population and older people are unknown; transport and language are unknown.",
    ):
        assert "p2_available_fact_omitted" in _codes(_checks(text, _community())["Processed community provenance"])


@pytest.mark.parametrize(
    "text",
    [
        _p2_text().replace("172,888", "SWAP").replace("15.6", "172,888").replace("SWAP", "15.6"),
        _p2_text().replace("population is 172,888", "population is 172,888 and population is 42"),
        _p2_text().replace("older people represent 15.6%", "older people represent 15.6"),
    ],
)
def test_p2_values_and_units_cannot_swap_or_conflict_with_another_measure(text):
    assert "p2_value_mismatch" in _codes(_checks(text, _community())["Processed community provenance"])


@pytest.mark.parametrize(
    "body",
    [
        "Assign a warning monitor.",
        "- [ ] Confirm the communication channels.",
        "| Role | Responsibility | Status |\n| --- | --- | --- |\n| Lead | Verify official contacts | To be confirmed by the responsible organisation |",
        "Unverified proposal for local review: verify official contacts.",
        "The responsible organisation must confirm official contacts.",
    ],
)
def test_each_local_action_requires_its_own_prefix_and_confirmer(body):
    text = "## 10. Roles and Responsibilities\n" + body
    assert _checks(text)["Local proposal attribution"]["status"] == "fail"


def test_table_action_cell_has_its_own_qualification_and_no_heading_inheritance():
    valid = "Unverified proposal for local review: the responsible organisation must confirm official contacts."
    table = "| Role | Responsibility |\n| --- | --- |\n| Lead | " + valid + " |"
    text = "## 10. Roles and Responsibilities\n" + table
    assert _checks(text)["Local proposal attribution"]["status"] == "pass"
    invalid = text.replace(valid, "Verify official contacts") + "\n" + valid
    assert _checks(invalid)["Local proposal attribution"]["status"] == "fail"


@pytest.mark.parametrize(
    "duty",
    [
        "Coordinates plan and review checkpoints",
        "Tracks official Queensland channels",
        "Maintains class lists and visitor records",
        "Handles parent and guardian updates",
    ],
)
def test_proposed_function_column_requires_each_third_person_duty_to_be_qualified(duty):
    confirmer = "Unverified proposal for local review: the responsible authority must confirm this duty."
    text = (
        "## 10. Roles and Responsibilities\n| Role | Proposed function | Confirmation needed |\n"
        "| --- | --- | --- |\n| Lead | " + duty + " | " + confirmer + " |"
    )
    check = _checks(text)["Local proposal attribution"]
    assert check["findings"] == [{"code": "local_task_requires_own_proposal_and_confirmer", "count": 1}]
    qualified = text.replace(
        duty, "Unverified proposal for local review: " + duty + "; the responsible authority must confirm"
    )
    assert _checks(qualified)["Local proposal attribution"]["status"] == "pass"
    same_cell_later_sentence = text.replace(duty, duty + ". " + confirmer)
    assert _checks(same_cell_later_sentence)["Local proposal attribution"]["status"] == "fail"


@pytest.mark.parametrize("role", ["responsible authority", "responsible organisation", "qualified reviewer"])
def test_direct_confirmer_duty_qualifies_local_proposal(role):
    text = (
        "## 13. Action Plan\nUnverified proposal for local review: assign a review owner; the "
        + role
        + " must confirm."
    )
    assert _checks(text)["Local proposal attribution"]["status"] == "pass"


@pytest.mark.parametrize(
    "confirmer",
    [
        "the responsible authority must not confirm this task",
        "the responsible authority will never confirm this task",
        "the responsible authority does not need to confirm this task",
        "no responsible authority must confirm this task",
        "it is not true that the responsible authority must confirm this task",
        "there is no requirement that the responsible authority must confirm this task",
        "the responsible authority is unavailable, so the operator must confirm this task",
        "if the responsible authority must confirm this task, it can be recorded",
        "unless the responsible authority must confirm this task, it can be recorded",
        "whether the responsible authority must confirm this task is unknown",
        "hypothetically the responsible authority must confirm this task",
        'the example reads "the responsible authority must confirm this task"',
        "the note says 'the responsible authority must confirm this task'",
        "the quoted instruction is ‘the responsible authority must confirm this task’",
        "the responsible authority must confirm this task is not required",
    ],
)
def test_non_asserted_or_negated_confirmer_does_not_qualify_a_local_task(confirmer):
    text = "## 13. Action Plan\nUnverified proposal for local review: assign a review owner; " + confirmer + "."
    codes = _codes(_checks(text)["Local proposal attribution"])
    assert {"local_task_requires_own_proposal_and_confirmer", "proposal_confirmer_missing"} <= codes


@pytest.mark.parametrize(
    "confirmer",
    [
        "the responsible authority must confirm only if it chooses to",
        "the responsible authority must confirm this task only if it chooses to",
        "the responsible authority must confirm this task if it chooses to",
        "the responsible authority must confirm this task only if convenient",
        "the responsible authority must confirm this task only if requested",
        "the responsible authority must confirm this task only if a later meeting occurs",
        "the responsible authority must confirm this task unless the owner opts out",
        "the responsible authority must confirm this task provided that funding remains",
        "it is false that the responsible authority must confirm this task",
    ],
)
def test_optional_or_false_confirmation_obligation_does_not_qualify_task(confirmer):
    text = "## 13. Action Plan\nUnverified proposal for local review: assign a review owner; " + confirmer + "."
    codes = _codes(_checks(text)["Local proposal attribution"])
    assert {"local_task_requires_own_proposal_and_confirmer", "proposal_confirmer_missing"} <= codes


@pytest.mark.parametrize(
    "confirmation_object",
    [
        "whether the route has authorisation",
        "if the route has authorisation",
        "if the route has authorisation before use",
        "this task before use",
    ],
)
def test_confirmation_question_object_or_before_use_is_not_an_optional_obligation(confirmation_object):
    text = (
        "## 13. Action Plan\nUnverified proposal for local review: assign a review owner; "
        "the responsible authority must confirm " + confirmation_object + "."
    )
    assert _checks(text)["Local proposal attribution"]["status"] == "pass"


def test_quoted_example_does_not_hide_a_separate_direct_confirmer_in_the_same_unit():
    text = (
        '## 13. Action Plan\nUnverified proposal for local review: assign the task labelled "review owner"; '
        "the responsible authority must confirm the appointment."
    )
    assert _checks(text)["Local proposal attribution"]["status"] == "pass"


def test_action_column_can_precede_owner_and_nominal_review_context_is_not_a_task():
    action = "Unverified proposal for local review: the responsible organisation must confirm official contacts."
    text = (
        "## 10. Roles and Responsibilities\nThe review responsibilities remain unknown.\n"
        "| Responsibility | Owner |\n| --- | --- |\n| " + action + " | Preparedness lead |"
    )
    assert _checks(text)["Local proposal attribution"]["status"] == "pass"
    assert (
        _checks(text.replace(action, "Official contact coordination"))["Local proposal attribution"]["status"] == "fail"
    )


def test_gap_does_not_excuse_concrete_criteria_later_in_same_sentence():
    text = (
        "## 9. Candidate Assembly Point Criteria\nNo evidence establishes school criteria, "
        "but shade and water should be included."
    )
    assert _checks(text)["Submitted passage scope and conflicts"]["status"] == "fail"


_CRITERIA_NON_PROPOSAL = (
    "The supplied passages do not establish criteria for shade, water, smoke or traffic at a candidate point, "
    "so no such criteria are proposed here."
)


def test_complete_non_proposal_criteria_denial_is_not_a_task_or_physical_criterion():
    checks = _checks("## 9. Candidate Assembly Point Criteria\n" + _CRITERIA_NON_PROPOSAL)
    assert checks["Local proposal attribution"]["status"] == "pass"
    assert checks["Submitted passage scope and conflicts"]["status"] == "pass"


@pytest.mark.parametrize(
    "body",
    [
        _CRITERIA_NON_PROPOSAL[:-1] + ", but shade and water should be included.",
        _CRITERIA_NON_PROPOSAL[:-1] + "; use shade and water.",
        _CRITERIA_NON_PROPOSAL[:-1] + ", and shade and water are proposed.",
        _CRITERIA_NON_PROPOSAL + " Shade and water should be included.",
        "| Evidence gap | Criteria |\n| --- | --- |\n| " + _CRITERIA_NON_PROPOSAL + " | Use shade and water. |",
    ],
)
def test_non_proposal_criteria_denial_cannot_hide_appended_or_other_cell_advice(body):
    checks = _checks("## 9. Candidate Assembly Point Criteria\n" + body)
    assert checks["Local proposal attribution"]["status"] == "fail"
    assert "physical_assembly_criteria_require_authority_verification" in _codes(
        checks["Submitted passage scope and conflicts"]
    )


def test_repeated_task_and_long_independent_sentence_are_not_hidden_by_prior_prefix():
    text = "## 13. Action Plan\n" + REQUIRED_DAY_ONE_ACTION
    assert _checks(text)["Local proposal attribution"]["status"] == "pass"
    text += "\n" + ("Document " + "the detailed planning context " * 150 + "and official contacts.")
    assert "local_task_requires_own_proposal_and_confirmer" in _codes(_checks(text)["Local proposal attribution"])


@pytest.mark.parametrize(
    "task",
    [
        "Unverified proposal for local\nreview: the responsible organisation must confirm official contacts.",
        "Unverified proposal for local review: the responsible organisation\nmust confirm official contacts.",
        "Unverified proposal for local review: the responsible\norganisation must confirm official contacts.",
    ],
)
def test_soft_wrapping_inside_one_task_preserves_its_own_qualification(task):
    wrapped = "## 8. Evacuation Planning\n" + task
    unwrapped = "## 8. Evacuation Planning\n" + " ".join(task.split())
    assert _checks(wrapped)["Local proposal attribution"]["status"] == "pass"
    assert _checks(wrapped)["Local proposal attribution"] == _checks(unwrapped)["Local proposal attribution"]


@pytest.mark.parametrize(
    "body",
    [
        "Unverified proposal for local review. The responsible organisation must confirm official contacts.",
        "Unverified proposal for local review:\n\nThe responsible organisation must confirm official contacts.",
        "- [ ] Unverified proposal for local review:\n- [ ] The responsible organisation must confirm official contacts.",
        "| Qualification | Responsibility |\n| --- | --- |\n| Unverified proposal for local review: | "
        "The responsible organisation must confirm official contacts. |",
    ],
)
def test_whitespace_shadow_cannot_share_qualifications_across_claim_units(body):
    assert _checks("## 10. Roles and Responsibilities\n" + body)["Local proposal attribution"]["status"] == "fail"


def test_soft_wrap_check_shadow_does_not_change_report_spans_or_sdk_binding():
    from src.model_evidence import text_sha256, validate_model_evidence

    report = (
        "## 8. Evacuation Planning\nUnverified proposal for local\nreview: "
        "the responsible organisation\nmust confirm official contacts."
    )
    analysis = _analysis(_chunk("Households prepare plans."))
    _, snapshot, _, _ = _capture(analysis, response=report)
    original_snapshot = deepcopy(snapshot)
    original_hash = text_sha256(report)
    original_claims = extract_body_claims(report, analysis)
    assert "\n" in original_claims[0]["claim"]
    assert _checks(report, analysis, snapshot)["Local proposal attribution"]["status"] == "pass"
    assert extract_body_claims(report, analysis) == original_claims
    for claim in original_claims:
        assert report[claim["span"]["start"] : claim["span"]["end"]] == claim["claim"]
    assert snapshot == original_snapshot
    assert text_sha256(report) == original_hash == snapshot["normalized_narrative_sha256"]
    assert validate_model_evidence(snapshot, analysis, report_text=report)


def test_exact_complete_non_directive_disclaimer_is_not_a_local_task():
    report = "## 8. Evacuation Planning\nThis draft contains no direction about when or where people should move."
    assert _checks(report)["Local proposal attribution"]["status"] == "pass"


@pytest.mark.parametrize(
    "body",
    [
        "This draft contains no direction about when or where people should move; assign a warning monitor.",
        "This draft contains no direction about when or where people should move, but people should use the hall.",
        "This draft contains no direction about when or where people should move. Assign a warning monitor.",
        "- [ ] This draft contains no direction about when or where people should move.\n- [ ] Assign a warning monitor.",
        "| Qualification | Responsibility |\n| --- | --- |\n| This draft contains no direction about when or where people "
        "should move. | Assign a warning monitor. |",
    ],
)
def test_non_directive_sentence_does_not_qualify_an_actual_task(body):
    assert _checks("## 10. Roles and Responsibilities\n" + body)["Local proposal attribution"]["status"] == "fail"


@pytest.mark.parametrize(
    "section,claim,check_name",
    [
        (
            "9. Candidate Assembly Point Criteria",
            "Shade and water are assembly criteria.",
            "Submitted passage scope and conflicts",
        ),
        ("6. Local Risk Context", "Power outages can affect warning access.", "Rule-derived causal qualification"),
    ],
)
def test_non_directive_exemption_does_not_suppress_physical_or_causal_checks(section, claim, check_name):
    report = "## " + section + "\nThis draft contains no direction about when or where people should move. " + claim
    assert _checks(report)[check_name]["status"] == "fail"


@pytest.mark.parametrize("prefix", ["", "Unverified proposal for local review: "])
def test_proposal_label_cannot_establish_physical_assembly_criteria(prefix):
    text = (
        "## 9. Candidate Assembly Point Criteria\n"
        + prefix
        + "the responsible organisation must confirm shade, water and traffic separation for the school assembly point."
    )
    assert "physical_assembly_criteria_require_authority_verification" in _codes(
        _checks(text)["Submitted passage scope and conflicts"]
    )


def test_assembly_gap_and_verification_task_are_allowed_without_invented_criteria():
    text = (
        "## 9. Candidate Assembly Point Criteria\nSchool physical assembly criteria are unknown.\n"
        "Unverified proposal for local review: the responsible organisation must confirm criteria with local authorities."
    )
    checks = _checks(text)
    assert checks["Local proposal attribution"]["status"] == "pass"
    assert checks["Submitted passage scope and conflicts"]["status"] == "pass"


def test_r3_causal_sentence_is_an_inference_not_a_fact_or_unverified_effect():
    body = "Power outages can affect warning access."
    text = "## 6. Local Risk Context\n" + body
    assert _checks(text)["Rule-derived causal qualification"]["status"] == "fail"
    qualified = (
        "## 6. Local Risk Context\n[R3] Planning inference: power outages can affect warning access; "
        "the responsible organisation must confirm local applicability."
    )
    assert _checks(qualified)["Rule-derived causal qualification"]["status"] == "pass"
    unsafe = (
        "## 7. Preparedness Priorities\nUnverified proposal for local review: training reduces smoke injury; "
        "the responsible organisation must confirm the programme."
    )
    assert _checks(unsafe)["Rule-derived causal qualification"]["status"] == "fail"


def _sourced(text, source_text, identity="guide"):
    chunk = _chunk(source_text, identity)
    analysis = _analysis(chunk)
    report = text + " " + format_rag_attribution(chunk) + "."
    _, snapshot, _, _ = _capture(analysis, response=report)
    return report, analysis, snapshot


@pytest.mark.parametrize(
    "source",
    [
        "School assembly areas do not require shade or water.",
        "School assembly criteria include shade and water.",
    ],
)
def test_physical_criteria_are_not_authorised_by_lexical_match_or_exact_source_quotation(source):
    report, analysis, snapshot = _sourced(
        "## 9. Candidate Assembly Point Criteria\nUnverified proposal for local review: "
        "the responsible organisation must confirm local use of this source criterion: " + source,
        source,
    )
    assert "physical_assembly_criteria_require_authority_verification" in _codes(
        _checks(report, analysis, snapshot)["Submitted passage scope and conflicts"]
    )


def test_household_scope_preserved_and_separate_campus_proposal_remains_possible():
    source = "Households should check local warning systems with the council."
    report, analysis, snapshot = _sourced(
        "## 8. Evacuation Planning\nHouseholds should check local warning systems with the council", source
    )
    assert _checks(report, analysis, snapshot)["Submitted passage scope and conflicts"]["status"] == "pass"
    changed = report.replace("Households should", "Schools should")
    snapshot = bind_normalized_narrative(snapshot, changed)
    assert "household_source_scope_not_preserved" in _codes(
        _checks(changed, analysis, snapshot)["Submitted passage scope and conflicts"]
    )


def test_retrieval_and_unavailable_or_invalid_capture_cannot_discharge_citation_check():
    report, analysis, snapshot = _sourced(
        "## 8. Evacuation Planning\nHouseholds should check local warning systems with the council",
        "Households should check local warning systems with the council.",
    )
    for evidence in (None, {**snapshot, "normalized_narrative_sha256": "0" * 64}):
        check = _checks(report, analysis, evidence)["Submitted passage scope and conflicts"]
        assert "cited_passage_not_final_submitted" in _codes(check)
    assert _checks(report, analysis, snapshot)["Submitted passage scope and conflicts"]["status"] == "pass"


def test_retrieved_but_omitted_passage_cannot_supply_support():
    from src.rag.context import assemble_planning_context

    chunk = _chunk("Schools should verify " + "detailed planning context " * 30 + "with the council.", "omitted")
    analysis = _analysis(_chunk("Households should prepare plans."), chunk)
    assembly = assemble_planning_context(analysis["knowledge"], max_chunk_characters=100)
    assert [item["source_id"] for item in assembly["visible_chunks"]] == ["guide"]
    report = "## 8. Evacuation Planning\nSchools should verify assembly criteria " + format_rag_attribution(chunk) + "."
    _, snapshot, _, _ = _capture(analysis, assembly=assembly, response=report)
    assert "cited_passage_not_final_submitted" in _codes(
        _checks(report, analysis, snapshot)["Submitted passage scope and conflicts"]
    )


def test_one_visible_citation_cannot_hide_an_omitted_citation_in_the_same_claim():
    from src.rag.context import assemble_planning_context

    visible = _chunk("Households prepare plans.")
    omitted = _chunk("Households consider " + "additional planning details " * 30 + "before action.", "omitted")
    analysis = _analysis(visible, omitted)
    assembly = assemble_planning_context(analysis["knowledge"], max_chunk_characters=100)
    assert [item["source_id"] for item in assembly["visible_chunks"]] == ["guide"]
    report = (
        "## 8. Evacuation Planning\nHouseholds prepare plans "
        + format_rag_attribution(visible)
        + " "
        + format_rag_attribution(omitted)
        + "."
    )
    _, snapshot, _, _ = _capture(analysis, assembly=assembly, response=report)
    assert "cited_passage_not_final_submitted" in _codes(
        _checks(report, analysis, snapshot)["Submitted passage scope and conflicts"]
    )


@pytest.mark.parametrize(
    "section,body",
    [
        ("8. Evacuation Planning", "Assign a warning monitor"),
        (
            "10. Roles and Responsibilities",
            "| Role | Responsibility |\n| --- | --- |\n| Lead | Assign a warning monitor",
        ),
        ("14. Human Review and Approval Checklist", "- [ ] Assign a warning monitor"),
    ],
)
def test_citation_does_not_excuse_unqualified_local_task(section, body):
    source = _chunk("Community organisations assign a warning monitor.")
    analysis = _analysis(source)
    report = "## " + section + "\n" + body + " " + format_rag_attribution(source)
    report += " |" if "| Role |" in body else "."
    _, snapshot, _, _ = _capture(analysis, response=report)
    assert "local_task_requires_own_proposal_and_confirmer" in _codes(
        _checks(report, analysis, snapshot)["Local proposal attribution"]
    )


def test_conflicting_source_is_not_silently_repaired_and_explicit_gap_is_allowed():
    source = "Property maintenance will increase the impacts of bushfire and reduce your chances of survival."
    report, analysis, snapshot = _sourced(
        "## 7. Preparedness Priorities\nProperty maintenance reduces bushfire impacts", source
    )
    original = deepcopy(analysis)
    assert "contradictory_source_used_as_advice" in _codes(
        _checks(report, analysis, snapshot)["Submitted passage scope and conflicts"]
    )
    report = (
        "## 5. Data Sources and Limitations\nUnresolved source conflict: maintenance wording requires responsible-source review "
        + format_rag_attribution(analysis["knowledge"]["retrieved_chunks"][0])
        + "."
    )
    snapshot = bind_normalized_narrative(snapshot, report)
    assert _checks(report, analysis, snapshot)["Submitted passage scope and conflicts"]["status"] == "pass"
    assert analysis == original


def test_generation_preserves_attested_snapshot_through_deterministic_formatting():
    report, analysis, snapshot = _sourced(
        "## 8. Evacuation Planning\nHouseholds should check local warning systems with the council",
        "Households should check local warning systems with the council.",
    )
    quality = assess_generated_narrative(EvidenceResponse(report, snapshot), analysis)
    check = next(item for item in quality["checks"] if item["name"] == "Submitted passage scope and conflicts")
    assert check["status"] == "pass"
    assert check["snapshot_status"] == "captured"
    full = append_human_signoff(
        append_evidence_tables(apply_governance_notice(report), analysis),
        {"report_status": "Draft - human review required"},
    )
    assert quality == evaluate_governed_report(full, analysis, model_evidence=snapshot)


def test_experiment_final_quality_uses_its_final_snapshot_without_retrieval_fallback():
    from scripts.body_evidence_experiment import _report_result

    report, analysis, snapshot = _sourced(
        "## 8. Evacuation Planning\nHouseholds should check local warning systems with the council",
        "Households should check local warning systems with the council.",
    )
    result = _report_result(report, analysis, snapshot)
    check = next(
        item for item in result["governed_quality"]["checks"] if item["name"] == "Submitted passage scope and conflicts"
    )
    assert check["snapshot_status"] == "captured"
    assert check["status"] == "pass"


def test_findings_do_not_persist_private_claim_text():
    import json

    text = "## 13. Action Plan\nAssign PRIVATE-CODE-91827 as the warning monitor."
    result = _checks(text)
    assert result["Local proposal attribution"]["status"] == "fail"
    assert "PRIVATE-CODE-91827" not in json.dumps(result)
