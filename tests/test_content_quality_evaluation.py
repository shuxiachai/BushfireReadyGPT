"""Mechanics tests for the offline content challenge runner.

These fixtures are intentionally tiny and self-authored.  They are not the
production holdout and do not inspect it.
"""

import json
import subprocess
import sys

import pytest

from scripts import evaluate_content_quality as runner


@pytest.fixture(autouse=True)
def _offline_git_metadata(monkeypatch):
    monkeypatch.setattr(runner, "_git", lambda *_args: None)


def _case(case_id, *, state="correct", expected="not_required", layout="prose"):
    return {
        "id": case_id,
        "category": "preparedness",
        "region": "Queensland",
        "scenario": "synthetic",
        "evidence_text": "Residents prepare a household emergency kit before fire season.",
        "claim_text": "Residents prepare a household emergency kit before fire season.",
        "citation_state": state,
        "format": layout,
        "expected_review": expected,
        "expected_reason_tags": [],
    }


def _fixture(tmp_path, cases):
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return path


def _evaluator(report_text, _analysis, snapshot=None):
    assert snapshot and snapshot["status"] == "captured"
    missing = "[O1-RAG][source_id=" not in report_text
    unrelated = "fixture-unrelated" in report_text
    reasons = ["missing_citation"] if missing else (["unsupported_citation"] if unrelated else [])
    return {
        "method": "body_claim_evidence_v1",
        "processing": {
            "complete": True,
            "claims_extracted": 1,
            "claims_evaluated": 1,
            "claims_omitted": 0,
            "max_claims": 1,
        },
        "claims": [
            {
                "claim_id": "synthetic-1",
                "claim": "Residents prepare a household emergency kit before fire season.",
                "section": "Preparedness",
                "block_type": "prose",
                "span": {"start": 0, "end": 1},
                "citation_required": True,
                "citation_status": "missing" if missing else "cited",
                "support_status": "no_lexical_match" if unrelated else "lexical_match",
                "reasons": reasons,
                "source_checks": [],
            }
        ],
    }


def test_synthetic_sdk_mock_runner_reports_gate_and_no_live_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "evaluate_body_claim_evidence", _evaluator)
    report = runner.evaluate_fixture(
        _fixture(tmp_path, [_case("clear"), _case("missing", state="missing", expected="required")])
    )

    assert report["gate"]["passed"] is True
    assert report["provenance"] == "synthetic_sdk_mock"
    assert report["evaluation_phase"] == "seen_case_regression"
    assert report["model_calls"] == report["retrieval_calls"] == report["embedding_calls"] == 0
    assert report["confusion_matrix"]["true_negative"] == 1
    assert report["confusion_matrix"]["true_positive"] == 1
    assert report["false_accept_ids"] == []
    assert report["extraction_misses"] == []


def test_actual_public_evaluator_accepts_synthetic_sdk_capture():
    outcome = runner._case_result(_case("actual-public-api"))

    assert outcome["status"] == "clear"
    assert outcome["snapshot_status"] == "captured"
    assert outcome["provenance"] == "synthetic_sdk_mock"


def test_script_help_runs_from_repository_root_without_reading_fixture():
    completed = subprocess.run(
        [sys.executable, "scripts/evaluate_content_quality.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--fixture" in completed.stdout


def test_target_claim_extraction_miss_fails_closed(monkeypatch, tmp_path):
    def omitted(*_args, **_kwargs):
        return {"method": "body_claim_evidence_v1", "processing": {"complete": True}, "claims": []}

    monkeypatch.setattr(runner, "evaluate_body_claim_evidence", omitted)
    report = runner.evaluate_fixture(_fixture(tmp_path, [_case("omitted", layout="table")]))

    assert report["gate"]["passed"] is False
    assert report["counts"]["extraction_misses"] == 1
    assert report["extraction_misses"][0]["id"] == "omitted"


def test_existing_explicit_output_is_never_overwritten(tmp_path):
    existing = tmp_path / "already.json"
    existing.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError):
        runner._unique_output(existing)


def test_correct_citation_identity_does_not_imply_supported_claim(monkeypatch):
    def contradicted(*args, **kwargs):
        result = _evaluator(*args, **kwargs)
        result["claims"][0].update(support_status="no_lexical_match", reasons=["possible_negation_mismatch"])
        return result

    monkeypatch.setattr(runner, "evaluate_body_claim_evidence", contradicted)
    result = runner._case_result(_case("contradicted", expected="required"))
    assert result["status"] == "review_required"
    assert result["support_statuses"] == ["no_lexical_match"]
    assert result["expectation_mismatches"] == []


def test_synthetic_citation_annotation_is_translated_in_place_without_changing_prose():
    case = _case("annotation")
    prose = case["claim_text"]
    case["claim_text"] += " [SYN-TEST-01]"
    case["evidence_text"] = "[SYN-TEST-01] " + case["evidence_text"]
    report, analysis, _assembly = runner._case_report(case)
    assert "[SYN-TEST-01]" not in report
    assert prose in report
    assert analysis["knowledge"]["retrieved_chunks"][0]["text"] == prose
    result = runner._case_result(case)
    assert result["status"] == "clear"
    assert result["citation_statuses"] == ["cited"]


def _existing_table_case():
    case = _case("existing-table", layout="table", expected="required")
    case["claim_text"] = (
        "| Place | Detail |\n| --- | --- |\n"
        "| Northbank Library | Residents prepare a household emergency kit before fire season. [SYN-UNIT-01] |"
    )
    return case


@pytest.mark.parametrize("outer", [True, False])
def test_existing_table_preserves_structure_and_includes_uncited_entity_cell(outer):
    case = _existing_table_case()
    if not outer:
        case["claim_text"] = "\n".join(line.strip("|").strip() for line in case["claim_text"].splitlines())
    report, _analysis, _assembly = runner._case_report(case)
    assert len(report.splitlines()) == 3
    assert "| Target |" not in report
    assert "Northbank Library" in report
    outcome = runner._case_result(case)
    assert outcome["claim_count"] == 2
    assert outcome["citation_statuses"] == ["cited", "missing"]
    assert outcome["status"] == "review_required"


def test_existing_table_retains_multiple_rows_and_all_sentences_in_one_cell():
    case = _existing_table_case()
    case["claim_text"] = (
        "| First action | Second action |\n| --- | --- |\n"
        "| Prepare emergency supplies. [SYN-UNIT-01] Drink clean water. [SYN-UNIT-01] "
        "| Stay informed. [SYN-UNIT-01] |\n"
        "| Drink clean water. [SYN-UNIT-01] | Prepare emergency supplies. [SYN-UNIT-01] |"
    )
    outcome = runner._case_result(case)
    assert outcome["claim_count"] == 5
    assert outcome["citation_statuses"] == ["cited"]


@pytest.mark.parametrize("omission", ["uncited_cell", "sentence"])
def test_existing_table_never_silently_drops_a_cell_or_sentence(monkeypatch, tmp_path, omission):
    case = _existing_table_case()
    case["claim_text"] = case["claim_text"].replace(
        "before fire season. [SYN-UNIT-01]", "before fire season. [SYN-UNIT-01] Stay informed. [SYN-UNIT-01]"
    )
    actual_evaluator = runner.evaluate_body_claim_evidence

    def incomplete(*args, **kwargs):
        result = actual_evaluator(*args, **kwargs)
        if omission == "uncited_cell":
            result["claims"] = [claim for claim in result["claims"] if claim["table_column"] != 1]
        else:
            result["claims"] = [claim for claim in result["claims"] if not claim["claim"].startswith("Stay informed.")]
        return result

    monkeypatch.setattr(runner, "evaluate_body_claim_evidence", incomplete)
    report = runner.evaluate_fixture(_fixture(tmp_path, [case]))
    assert report["gate"]["passed"] is False
    assert report["counts"]["evaluated_cases"] == 0
    assert report["counts"]["extraction_misses"] == 1


def test_plain_statement_with_table_format_still_gets_one_table_wrapper():
    case = _case("plain-table", layout="table")
    report, _analysis, _assembly = runner._case_report(case)
    assert report.startswith("| Action | Detail |\n| --- | --- |\n| Target |")
    outcome = runner._case_result(case)
    assert outcome["claim_count"] == 1
    assert outcome["status"] == "clear"
