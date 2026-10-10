"""Current-only abstract proposal status; all task and evidence gates stay active."""

from copy import deepcopy

import pytest

from src.report_claim_evidence import extract_body_claims
from src.report_content_contract import PROPOSAL_STATUS_RULESET, evaluate_report_content_contract
from src.report_generation_quality import (
    CURRENT_POLICY,
    KNOWN_QUALITY_POLICY_MANIFESTS,
    READABLE_QUALITY_POLICY_BINDINGS,
    evaluate_governed_report,
)
from src.report_section_protocol import project_section_report, render_section_report
from tests.support.report_fixtures import _valid_report

STATUS_CASES = (
    (
        "9. Candidate Assembly Point Criteria",
        "Candidate assembly point criteria are unverified proposals for local review.",
    ),
    ("10. Roles and Responsibilities", "Roles and responsibilities for the workshop are unconfirmed proposals."),
    (
        "12. First Aid, Training and Exercises",
        "First aid, smoke/heat support, AED/burn preparedness, staff training, and exercise objectives "
        "are unverified proposals for local review.",
    ),
)
LOCAL_CHECK = "Local proposal attribution"
TASK_CODE = "local_task_requires_own_proposal_and_confirmer"


def _checks(text, *, current=True):
    kwargs = {"proposal_status_ruleset": PROPOSAL_STATUS_RULESET} if current else {}
    return {check["name"]: check for check in evaluate_report_content_contract(text, {}, **kwargs)}


def _task_count(checks):
    return sum(item["count"] for item in checks[LOCAL_CHECK]["findings"] if item["code"] == TASK_CODE)


@pytest.mark.parametrize("heading,status", STATUS_CASES)
def test_complete_status_only_removes_its_local_task_false_positive(heading, status):
    report = f"## {heading}\n{status}"
    before = extract_body_claims(report, {})
    legacy, current = _checks(report, current=False), _checks(report)
    assert _task_count(legacy) == 1
    assert current[LOCAL_CHECK]["status"] == "pass"
    assert {key: value for key, value in current.items() if key != LOCAL_CHECK} == {
        key: value for key, value in legacy.items() if key != LOCAL_CHECK
    }
    assert extract_body_claims(report, {}) == before  # No deletion, clipping or span changes.


@pytest.mark.parametrize("heading,status", STATUS_CASES)
@pytest.mark.parametrize("verb", ["are", "remain"])
@pytest.mark.parametrize("state", ["unverified", "unconfirmed"])
def test_closed_status_grammar_accepts_soft_wrap_and_supported_state_variants(heading, status, verb, state):
    value = status.replace(" are ", f"\n{verb} ").replace("unverified", state).replace("unconfirmed", state)
    assert _checks(f"## {heading}\n{value}")[LOCAL_CHECK]["status"] == "pass"


@pytest.mark.parametrize("ruleset", [False, True, 0, 1, "", "bounded-status-v1", [], {}, object()])
def test_unknown_ruleset_fails_closed(ruleset):
    with pytest.raises(ValueError, match="Unsupported proposal-status ruleset"):
        evaluate_report_content_contract("A draft.", {}, proposal_status_ruleset=ruleset)


@pytest.mark.parametrize("heading,status", STATUS_CASES)
def test_explicit_none_retains_complete_legacy_check_output(heading, status):
    report = f"## {heading}\n{status}"
    assert evaluate_report_content_contract(report, {}) == evaluate_report_content_contract(
        report, {}, proposal_status_ruleset=None
    )
    assert _task_count(_checks(report, current=False)) == 1


@pytest.mark.parametrize(
    "body",
    [
        "Roles and responsibilities are verified proposals.",
        "Roles and responsibilities are unconfirmed proposals?",
        "Roles and responsibilities are not unconfirmed proposals.",
        "Roles and responsibilities will be unconfirmed proposals.",
        "Role appointments are unconfirmed proposals only if funding is available.",
        "Roles and responsibilities are unconfirmed proposals; assign staff immediately.",
        "Roles and responsibilities are unconfirmed proposals and must be implemented.",
        "Roles and responsibilities are unconfirmed proposals because they improve readiness.",
        "Two role appointments are unconfirmed proposals.",
        "Daily role appointments are unconfirmed proposals.",
        "Assigning staff and training wardens are unconfirmed proposals.",
        "Unverified proposal for local review: roles and responsibilities are unconfirmed proposals.",
        '"Roles and responsibilities are unconfirmed proposals."',
        "“Roles and responsibilities are unconfirmed proposals.”",
        "Hypothetically, roles and responsibilities are unconfirmed proposals.",
        "If invited, roles and responsibilities are unconfirmed proposals.",
        "For example. Roles and responsibilities are unconfirmed proposals.",
        "Suppose this. Roles and responsibilities are unconfirmed proposals.",
        "Assume the following example.\n\nRoles and responsibilities are unconfirmed proposals.",
        "If the exercise proceeds.\n\nRoles and responsibilities are unconfirmed proposals.",
        "Roles and responsibilities are unconfirmed proposals.\n\nThe preceding statement is hypothetical.",
        "> Roles and responsibilities are unconfirmed proposals.",
        "> An example. Roles and responsibilities are unconfirmed proposals.",
        "- Roles and responsibilities are unconfirmed proposals.",
        "- [ ] Roles and responsibilities are unconfirmed proposals.",
        "| Role | Responsibility |\n| --- | --- |\n| Lead | Roles and responsibilities are unconfirmed proposals. |",
        'The quoted example is: "\n\nRoles and responsibilities are unconfirmed proposals.\n\n"',
        "The quoted example is: ‘\n\nRoles and responsibilities are unconfirmed proposals.\n\n’",
        "The quoted example is: &#34;\n\nRoles and responsibilities are unconfirmed proposals.\n\n&#34;",
    ],
)
def test_tasks_conditions_quotes_examples_and_containers_never_gain_status_exemption(body):
    report = "## 10. Roles and Responsibilities\n" + body
    assert _task_count(_checks(report)) >= 1
    assert _checks(report) == _checks(report, current=False)


def test_closed_quote_in_another_paragraph_does_not_taint_unquoted_status():
    report = '## 10. Roles and Responsibilities\nThe label is "review record".\n\n'
    report += "Roles and responsibilities are unconfirmed proposals."
    assert _checks(report)[LOCAL_CHECK]["status"] == "pass"


@pytest.mark.parametrize(
    "tail",
    [
        "The responsible organisation must confirm role appointments.",
        "Assign role appointments.",
        "Unverified proposal for local review: assign role appointments.",
    ],
)
def test_status_never_qualifies_a_later_independent_task(tail):
    report = "## 10. Roles and Responsibilities\nRoles and responsibilities are unconfirmed proposals. " + tail
    assert _task_count(_checks(report)) == 1
    assert _task_count(_checks(report, current=False)) == 2
    if tail.startswith("Unverified proposal"):
        assert {item["code"] for item in _checks(report)[LOCAL_CHECK]["findings"]} == {
            TASK_CODE,
            "proposal_confirmer_missing",
        }


def test_status_does_not_borrow_a_confirmer_across_sentences_or_cells():
    text = (
        "## 10. Roles and Responsibilities\nRoles and responsibilities are unconfirmed proposals. "
        "Unverified proposal for local review: assign appointments. The responsible organisation must confirm them."
    )
    assert _task_count(_checks(text)) == 2
    text = (
        "## 10. Roles and Responsibilities\n| Responsibility | Confirmation |\n| --- | --- |\n"
        "| Roles and responsibilities are unconfirmed proposals. | "
        "Unverified proposal for local review: the responsible organisation must confirm appointments. |"
    )
    assert _task_count(_checks(text)) == 1


def test_causal_and_physical_criteria_checks_still_run():
    report = (
        "## 10. Roles and Responsibilities\nRoles and responsibilities are unconfirmed proposals. They reduce harm."
    )
    assert _checks(report)["Rule-derived causal qualification"]["status"] == "fail"
    physical = "## 9. Candidate Assembly Point Criteria\nFirst aid and shade are unverified proposals for local review."
    checks = _checks(physical)
    assert checks[LOCAL_CHECK]["status"] == "fail"
    assert checks["Submitted passage scope and conflicts"]["findings"] == [
        {"code": "physical_assembly_criteria_require_authority_verification", "count": 1}
    ]


def test_current_gate_opts_in_while_v11_remains_readable_and_unchanged():
    report, analysis = _valid_report()
    sections = project_section_report(report, analysis)
    sections["s10"] = STATUS_CASES[1][1]
    report = render_section_report(sections, analysis)
    frozen_analysis = deepcopy(analysis)
    assert _task_count({item["name"]: item for item in evaluate_report_content_contract(report, analysis)}) == 1
    checks = {item["name"]: item for item in evaluate_governed_report(report, analysis)["checks"]}
    assert checks[LOCAL_CHECK]["status"] == "pass"
    assert analysis == frozen_analysis
    assert CURRENT_POLICY == "governed-report-v12"
    assert READABLE_QUALITY_POLICY_BINDINGS["governed-report-v11"] == frozenset(
        {"a690c5afc1b7497ca04cd06cc2197ced685f14159387c1237c9ee11268ccc2b4"}
    )
    assert (
        KNOWN_QUALITY_POLICY_MANIFESTS["governed-report-v11"]["local_proposal_ruleset"]
        == "occurrence-proposal-confirmer-v2"
    )
    assert KNOWN_QUALITY_POLICY_MANIFESTS[CURRENT_POLICY]["local_proposal_ruleset"] == PROPOSAL_STATUS_RULESET


def test_three_status_false_positives_do_not_hide_thirteen_real_occurrences_or_overlength_body():
    # Synthetic occurrence inventory retained from the bounded diagnostic. No
    # model/provider call, saved-report rewrite or historical quality replay.
    groups = [
        (
            "7. Preparedness Priorities",
            ["The community workshop will cover these priorities to ensure household readiness."],
        ),
        (
            "8. Evacuation Planning",
            [
                "Participants will learn to monitor official warnings, receive notifications, and follow movement and accountability procedures."
            ],
        ),
        (
            STATUS_CASES[0][0],
            [
                STATUS_CASES[0][1],
                "The responsible organisation must confirm the criteria through authorised official sources before operational use.",
                "The workshop will identify candidate assembly points and require local approval before treating them as safe.",
            ],
        ),
        (
            STATUS_CASES[1][0],
            [
                STATUS_CASES[1][1],
                "The application will add the role table, which will outline the responsibilities of participants and local authorities.",
                "The workshop will ensure that all roles are clearly defined and understood.",
            ],
        ),
        (
            "11. Communication and Inclusion Needs",
            [
                "Participants will learn about warning channels, internal/public/parent communication, accessibility, inclusion, multilingual needs, and backup arrangements.",
                "The workshop will provide general maintenance support and ensure that all communication channels are accessible and inclusive.",
            ],
        ),
        (
            STATUS_CASES[2][0],
            [
                STATUS_CASES[2][1],
                "The workshop will cover these topics to ensure that participants are prepared for potential emergencies.",
                "The application will add the frequency and records of locally confirmed first aid, training, and exercises.",
            ],
        ),
        ("13. Action Plan", ["The application will add the specific actions and Day 1 tasks."]),
        (
            "14. Human Review and Approval Checklist",
            [
                "The responsible organisation must confirm the incomplete human review tasks before operational use.",
                "The application will add the unchecked checklist.",
            ],
        ),
    ]
    report = "\n\n".join("## " + heading + "\n" + " ".join(sentences) for heading, sentences in groups)
    words = _checks(report, current=False)["Narrative word budget"]["word_count"]
    report += "\n\n" + "planning " * (886 - words)
    legacy, current = _checks(report, current=False), _checks(report)
    assert _task_count(legacy) == 16
    assert _task_count(current) == 13
    assert current[LOCAL_CHECK]["status"] == "fail"
    assert current["Narrative word budget"]["word_count"] == 886
    assert current["Narrative word budget"]["status"] == "fail"
    assert {key: value for key, value in current.items() if key != LOCAL_CHECK} == {
        key: value for key, value in legacy.items() if key != LOCAL_CHECK
    }
