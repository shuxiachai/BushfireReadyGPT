"""Offline occurrence metadata shares the production evaluator's decisions."""

import inspect
import json
from collections import Counter
from copy import deepcopy

import pytest

from src import report_content_contract as contract
from src.model_evidence import bind_normalized_narrative, text_sha256
from src.report_claim_evidence import extract_body_claims
from src.report_generation_quality import CURRENT_POLICY, QUALITY_POLICY_FINGERPRINT, evaluate_governed_report
from src.report_template import GOVERNANCE_NOTICE_MARKDOWN, extract_narrative_body
from src.source_attribution import format_rag_attribution
from tests.support.model_evidence_fixtures import _analysis
from tests.support.report_fixtures import _valid_report
from tests.test_model_evidence import _capture, _chunk

# Literal legacy result captured from 21f83ba before the shared-evaluator change.
_EMPTY_CHECKS = [
    {
        "name": "Narrative word budget",
        "status": "fail",
        "detail": "narrative_word_budget: 1",
        "findings": [{"code": "narrative_word_budget", "count": 1}],
        "word_count": 0,
        "minimum": 650,
        "maximum": 800,
    },
    {
        "name": "Processed community provenance",
        "status": "pass",
        "detail": "No frozen community indicators require narration.",
        "findings": [],
    },
    {
        "name": "Local proposal attribution",
        "status": "pass",
        "detail": "Targeted local tasks carry their own proposal and confirmer.",
        "findings": [],
    },
    {
        "name": "Rule-derived causal qualification",
        "status": "pass",
        "detail": "Targeted causal planning inferences remain qualified.",
        "findings": [],
    },
    {
        "name": "Submitted passage scope and conflicts",
        "status": "pass",
        "detail": "No targeted submitted-passage, audience or source-conflict violation detected.",
        "findings": [],
        "snapshot_status": "unavailable",
    },
]
_TASK_CODE = "local_task_requires_own_proposal_and_confirmer"


def _diagnose(report, analysis=None, **kwargs):
    analysis = analysis or {}
    original = deepcopy((analysis, kwargs))
    result = contract.diagnose_report_content_contract(report, analysis, **kwargs)
    assert result["checks"] == contract.evaluate_report_content_contract(report, analysis, **kwargs)
    assert (analysis, kwargs) == original
    assert result["schema_version"] == "report-content-occurrences-v1"
    assert result["narrative_sha256"] == text_sha256(extract_narrative_body(str(report or "")))
    assert result["truncated"] is False
    counts = Counter((row["check_name"], row["code"]) for row in result["occurrences"])
    assert counts == Counter(
        {
            (check["name"], finding["code"]): finding["count"]
            for check in result["checks"]
            for finding in check["findings"]
        }
    )
    return result


def _rows(result, code):
    return [row for row in result["occurrences"] if row["code"] == code]


def _community(**indicators):
    return {
        "community": {
            "indicators": {
                "population": 1200,
                "older_people_pct": 15,
                "no_car_households_pct": None,
                "language_other_than_english_pct": None,
                "matched_sa2_count": 2,
                **indicators,
            },
            "data_quality": {"source_period": "2021 Census"},
        }
    }


def test_public_default_signature_and_empty_literal_baseline_remain_exact():
    assert str(inspect.signature(contract.evaluate_report_content_contract)) == (
        "(report_text, analysis, *, model_evidence=None, proposal_status_ruleset=None)"
    )
    assert contract.evaluate_report_content_contract("", {}) == _EMPTY_CHECKS
    assert _diagnose("")["checks"] == _EMPTY_CHECKS


def test_mixed_failure_literal_baseline_remains_exact():
    report = (
        "## 13. Action Plan\nAssign a warning monitor.\n"
        "## 6. Local Risk Context\nPower outages can affect warning access."
    )
    expected = deepcopy(_EMPTY_CHECKS)
    expected[0]["word_count"] = 17
    expected[2].update(
        status="fail",
        detail="local_task_requires_own_proposal_and_confirmer: 1",
        findings=[{"code": "local_task_requires_own_proposal_and_confirmer", "count": 1}],
    )
    expected[3].update(
        status="fail",
        detail="causal_planning_inference_unqualified: 1",
        findings=[{"code": "causal_planning_inference_unqualified", "count": 1}],
    )
    assert _diagnose(report)["checks"] == expected


@pytest.mark.parametrize("ruleset", [None, contract.PROPOSAL_STATUS_RULESET])
def test_status_legacy_and_current_literal_baselines_remain_exact(ruleset):
    report = "## 10. Roles and Responsibilities\nRoles and responsibilities are unverified proposals for local review."
    expected = deepcopy(_EMPTY_CHECKS)
    expected[0]["word_count"] = 13
    if ruleset is None:
        expected[2].update(
            status="fail",
            detail="local_task_requires_own_proposal_and_confirmer: 1",
            findings=[{"code": "local_task_requires_own_proposal_and_confirmer", "count": 1}],
        )
    result = _diagnose(report, proposal_status_ruleset=ruleset)
    assert result["checks"] == expected
    assert len(_rows(result, _TASK_CODE)) == (1 if ruleset is None else 0)


@pytest.mark.parametrize("ruleset", [False, True, 0, "", "unsupported", [], {}])
def test_diagnostics_reject_the_same_unsupported_rulesets(ruleset):
    for evaluate in (contract.evaluate_report_content_contract, contract.diagnose_report_content_contract):
        with pytest.raises(ValueError, match="^Unsupported proposal-status ruleset\\.$"):
            evaluate("A draft.", {}, proposal_status_ruleset=ruleset)


def test_valid_current_report_and_quality_fingerprint_are_unchanged():
    report, analysis = _valid_report()
    before = evaluate_governed_report(report, analysis)
    result = _diagnose(report, analysis, proposal_status_ruleset=contract.PROPOSAL_STATUS_RULESET)
    assert all(check["status"] == "pass" for check in result["checks"])
    assert result["occurrences"] == []
    assert evaluate_governed_report(report, analysis) == before
    assert CURRENT_POLICY == "governed-report-v12"
    assert QUALITY_POLICY_FINGERPRINT == "39c7ae6687fcef29f4ce1e8f6c3d7d04d13a65f89f2b15ea667a0a1af2140130"


def test_all_five_checks_have_occurrences_without_losing_global_failures():
    report = (
        "## 4. Selected Geography and Key Assumptions\nPopulation is 1.\n"
        "## 6. Local Risk Context\nPower outages can affect warning access.\n"
        "## 9. Candidate Assembly Point Criteria\nUse shade and water.\n"
        "## 13. Action Plan\nUnverified proposal for local review: assign a warning monitor."
    )
    result = _diagnose(report, _community())
    assert {row["check_name"] for row in result["occurrences"]} == {check["name"] for check in result["checks"]}
    assert _rows(result, "narrative_word_budget")[0]["unlocalized_reason"] == "report_wide"
    missing = _rows(result, "p2_available_fact_omitted") + _rows(result, "p2_unknown_measurement_omitted")
    assert missing and all(row["unlocalized_reason"] == "missing_required_content" for row in missing)
    assert all(row["locations"] == [] for row in missing)
    assert _rows(result, "p2_value_mismatch")[0]["unlocalized_reason"] is None


def test_repeated_identical_claims_retain_distinct_raw_spans_and_existing_ids():
    sentence = "Assign a PRIVATE-CODE-91827 review owner."
    report = "## 10. Roles and Responsibilities\n" + sentence + "\n## 13. Action Plan\n" + sentence
    result = _diagnose(report)
    units = extract_body_claims(report, {})
    locations = [row["locations"][0] for row in _rows(result, _TASK_CODE)]
    assert len(locations) == 2
    assert locations[0]["claim_id"] != locations[1]["claim_id"]
    assert [location["claim_id"] for location in locations] == [unit["claim_id"] for unit in units]
    for location, unit in zip(locations, units, strict=True):
        assert location == {"claim_id": unit["claim_id"], **unit["span"], "block_type": unit["block_type"]}
        assert report[location["start"] : location["end"]] == sentence
    assert "PRIVATE-CODE-91827" not in json.dumps(result)


def test_aggregate_unknown_measurement_has_one_finding_with_all_supporting_locations():
    report = "Transport is 10%.\n\nTransport is 20%.\n\nTransport and language remain unknown."
    result = _diagnose(report, _community(population=None, older_people_pct=None))
    rows = _rows(result, "p2_unknown_measurement_promoted")
    assert len(rows) == 1
    assert rows[0]["unlocalized_reason"] is None
    assert [report[loc["start"] : loc["end"]] for loc in rows[0]["locations"]] == [
        "Transport is 10%.",
        "Transport is 20%.",
    ]
    assert not _rows(result, "p2_unknown_measurement_omitted")


def test_two_fields_in_one_unit_keep_two_same_location_provenance_findings():
    report = "Population is 1200 and older-people share is 15%. Transport and language remain unknown."
    rows = _rows(_diagnose(report, _community()), "p2_adjacent_provenance_missing")
    assert len(rows) == 2
    assert rows[0] == rows[1]


@pytest.mark.parametrize("value", ["invalid-private-basis", "NaN", "Infinity"])
def test_invalid_frozen_measurement_is_report_wide_without_basis_text(value):
    result = _diagnose("Population is 1200.", _community(population=value))
    rows = _rows(result, "p2_invalid_frozen_measurement")
    assert rows == [
        {
            "check_name": "Processed community provenance",
            "code": "p2_invalid_frozen_measurement",
            "locations": [],
            "unlocalized_reason": "invalid_frozen_basis",
        }
    ]
    assert value not in json.dumps(result)


@pytest.mark.parametrize(
    "body,block_type",
    [
        ("Assign a warning monitor.", "prose"),
        ("- Assign a warning monitor.", "bullet"),
        ("- [ ] Assign a warning monitor.", "checklist"),
        ("| Owner | Responsibility |\n| --- | --- |\n| Preparedness lead | Assign a warning monitor. |", "table_cell"),
        ('"Roles and responsibilities are unconfirmed proposals."', "prose"),
        ("> Roles and responsibilities are unconfirmed proposals.", "prose"),
    ],
)
def test_table_list_and_quoted_status_locations_keep_extractor_boundaries(body, block_type):
    report = "## 10. Roles and Responsibilities\n" + body
    rows = _rows(_diagnose(report, proposal_status_ruleset=contract.PROPOSAL_STATUS_RULESET), _TASK_CODE)
    assert len(rows) == 1
    location = rows[0]["locations"][0]
    assert location["block_type"] == block_type
    assert location["claim_id"] in {unit["claim_id"] for unit in extract_body_claims(report, {})}
    if block_type == "table_cell":
        assert report[location["start"] : location["end"]] == "Assign a warning monitor."


def test_normalized_narrative_offsets_keep_unicode_and_soft_wrap_bytes():
    body = "## 13. Action Plan\nUnverified proposal for local\nreview: assign a 私密 review owner."
    report = GOVERNANCE_NOTICE_MARKDOWN + "\n\n  " + body + "\n\n## Evidence Tables\nPRIVATE APPENDIX"
    result = _diagnose(report)
    narrative = extract_narrative_body(report)
    units = extract_body_claims(narrative, {})
    for row in _rows(result, _TASK_CODE) + _rows(result, "proposal_confirmer_missing"):
        location = row["locations"][0]
        assert location["claim_id"] == units[0]["claim_id"]
        assert narrative[location["start"] : location["end"]] == units[0]["claim"]
        assert "local\nreview" in narrative[location["start"] : location["end"]]
    assert "私密" not in json.dumps(result, ensure_ascii=False)
    assert "PRIVATE APPENDIX" not in json.dumps(result)


@pytest.mark.parametrize("snapshot_kind", ["valid", "invalid", "unavailable"])
def test_submitted_evidence_and_conflict_occurrences_preserve_snapshot_decisions(snapshot_kind):
    chunk = _chunk("Household property maintenance will increase the impacts of bushfire.")
    analysis = _analysis(chunk)
    report = "## 8. Evacuation Planning\nSchools should check official contacts " + format_rag_attribution(chunk) + "."
    _, snapshot, _, _ = _capture(analysis, response=report)
    if snapshot_kind == "invalid":
        snapshot = {**snapshot, "normalized_narrative_sha256": "0" * 64}
    elif snapshot_kind == "unavailable":
        snapshot = None
    result = _diagnose(report, analysis, model_evidence=snapshot)
    assert _rows(result, "contradictory_source_used_as_advice")
    if snapshot_kind == "valid":
        assert _rows(result, "household_source_scope_not_preserved")
        assert not _rows(result, "cited_passage_not_final_submitted")
    else:
        assert _rows(result, "cited_passage_not_final_submitted")
    for row in result["occurrences"]:
        if row["code"] != "narrative_word_budget":
            assert len(row["locations"]) == 1


def test_explicit_source_conflict_notice_stays_exempt():
    chunk = _chunk("Property maintenance will increase the impacts of bushfire.")
    analysis = _analysis(chunk)
    report = "## 5. Data Sources and Limitations\nUnresolved source conflict requires review "
    report += format_rag_attribution(chunk) + "."
    _, snapshot, _, _ = _capture(analysis, response=report)
    snapshot = bind_normalized_narrative(snapshot, report)
    result = _diagnose(report, analysis, model_evidence=snapshot)
    assert not _rows(result, "contradictory_source_used_as_advice")


@pytest.mark.parametrize("limit_name", ["MAX_CONTENT_OCCURRENCES", "MAX_CONTENT_OCCURRENCE_LOCATIONS"])
def test_diagnostic_truncation_is_explicit_and_never_changes_legacy_counts(monkeypatch, limit_name):
    report = "## 13. Action Plan\n" + "Assign a warning monitor.\n" * 4
    expected = contract.evaluate_report_content_contract(report, {})
    monkeypatch.setattr(contract, limit_name, 2)
    result = contract.diagnose_report_content_contract(report, {})
    assert result["truncated"] is True
    assert result["checks"] == expected
    if limit_name == "MAX_CONTENT_OCCURRENCES":
        assert len(result["occurrences"]) == 2
    else:
        assert sum(len(row["locations"]) for row in result["occurrences"]) == 2
        assert any(row["unlocalized_reason"] == "producer_location_unavailable" for row in result["occurrences"])


def test_truncated_multi_location_event_remains_one_finding(monkeypatch):
    report = "Transport is 10%. Transport is 20%. Transport and language are unknown."
    analysis = _community(population=None, older_people_pct=None)
    expected = contract.evaluate_report_content_contract(report, analysis)
    monkeypatch.setattr(contract, "MAX_CONTENT_OCCURRENCE_LOCATIONS", 1)
    result = contract.diagnose_report_content_contract(report, analysis)
    assert result["truncated"] is True
    assert result["checks"] == expected
    rows = _rows(result, "p2_unknown_measurement_promoted")
    assert len(rows) == 1 and len(rows[0]["locations"]) == 1
    assert rows[0]["unlocalized_reason"] == "producer_location_unavailable"


@pytest.mark.parametrize(
    "invalid",
    [
        {"claim_id": "PRIVATE-ID-UNSAFE"},
        {"span": {"start": -1, "end": 5}},
        {"span": {"start": True, "end": 5}},
        {"block_type": "PRIVATE-BLOCK-UNSAFE"},
        {"block_type": []},
    ],
)
def test_unusable_producer_locations_have_fixed_reason_and_no_private_metadata(monkeypatch, invalid):
    report = "## 13. Action Plan\nAssign a warning monitor."
    units = extract_body_claims(report, {})
    units[0].update(invalid)
    monkeypatch.setattr(contract, "extract_body_claims", lambda *_args: units)
    result = _diagnose(report)
    rows = _rows(result, _TASK_CODE)
    assert rows[0]["locations"] == []
    assert rows[0]["unlocalized_reason"] == "producer_location_unavailable"
    assert "PRIVATE" not in json.dumps(result)


def test_diagnostic_path_extracts_once_and_does_not_reextract_for_each_check(monkeypatch):
    extract_calls = []
    original = contract.extract_body_claims

    def extract(report, analysis):
        extract_calls.append(report)
        return original(report, analysis)

    monkeypatch.setattr(contract, "extract_body_claims", extract)
    contract.diagnose_report_content_contract("## 13. Action Plan\nAssign a review owner.", {})
    assert len(extract_calls) == 1
