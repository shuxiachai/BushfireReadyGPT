"""Offline, deterministic challenge runner for body-claim evidence evaluation.

This runner deliberately performs no retrieval, embedding, or provider request.  Each
fixture case is supplied as a synthetic SDK response and a synthetic retrieved passage;
the governed client is used only to exercise the same submission-capture boundary as
the application tests.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluation_artifacts import _git  # noqa: E402
from src.markdown_tables import is_markdown_table_separator, parse_markdown_table_row
from src.model_evidence import (
    EvidencePrompt,
    bind_normalized_narrative,
    capture_model_evidence,
)  # noqa: E402
from src.model_runtime import GovernedModelClient  # noqa: E402
from src.rag.service import assemble_retrieved_context  # noqa: E402
from src.report_claim_evidence import evaluate_body_claim_evidence  # noqa: E402
from src.source_attribution import format_rag_attribution, strip_known_attribution_labels  # noqa: E402

METHOD = "body_claim_evidence_v1"
DEFAULT_FIXTURE = Path("data_australia/rag/content_holdout_v1.json")
DEFAULT_OUTPUT_DIRECTORY = Path("output/diagnostics")
_REQUIRED_CASE_KEYS = {
    "id",
    "category",
    "region",
    "scenario",
    "evidence_text",
    "claim_text",
    "citation_state",
    "format",
    "expected_review",
    "expected_reason_tags",
}
_CASE_STATES = {"correct", "missing", "wrong"}
_FORMATS = {"prose", "table", "long_sentence"}
_REVIEWS = {"required", "not_required"}
_FIXTURE_CITATION = re.compile(r"\[SYN-[A-Z0-9-]+\]")


def _natural_claim(case):
    """Fixture source labels are annotations, not part of the asserted prose."""
    return _FIXTURE_CITATION.sub("", case["claim_text"]).strip()


class FixtureError(ValueError):
    """A frozen challenge fixture was malformed or could not be evaluated safely."""


def _outer_table_row(line: str) -> str:
    line = line.strip()
    if not line.startswith("|"):
        line = "|" + line
    trailing_slashes = len(line[:-1]) - len(line[:-1].rstrip("\\"))
    if not line.endswith("|") or trailing_slashes % 2:
        line += "|"
    return line


def _table_body_cells(case: dict) -> dict[tuple[int, int], str] | None:
    """Inventory every nonempty cell independently of evaluator extraction."""
    if case["format"] != "table":
        return None
    lines = _natural_claim(case).splitlines()
    if len(lines) < 2 or not is_markdown_table_separator(_outer_table_row(lines[1])):
        return None
    header = parse_markdown_table_row(_outer_table_row(lines[0]))
    separator = parse_markdown_table_row(_outer_table_row(lines[1]))
    if not header or len(header) != len(separator):
        raise FixtureError("existing table has an invalid header")
    cells = {}
    for row, line in enumerate(lines[2:], 1):
        values = parse_markdown_table_row(_outer_table_row(line))
        if not values or len(values) != len(header):
            raise FixtureError("existing table has an invalid body row")
        for column, value in enumerate(values, 1):
            if value.strip():
                cells[row, column] = value.strip()
    if not cells:
        raise FixtureError("existing table contains no nonempty body cells")
    return cells


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_sha() -> str | None:
    path = PROJECT_ROOT / "src/report_claim_evidence.py"
    return _sha256_bytes(path.read_bytes()) if path.is_file() else None


def _git_context() -> dict[str, object]:
    revision = _git(PROJECT_ROOT, "rev-parse", "HEAD")
    status = _git(PROJECT_ROOT, "status", "--porcelain")
    return {"revision": revision, "dirty": bool(status) if status is not None else None}


def _load_fixture(path: Path) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FixtureError("fixture is not valid UTF-8 JSON") from error
    cases = document.get("cases") if isinstance(document, dict) else None
    if not isinstance(cases, list) or not cases:
        raise FixtureError("fixture root must contain a non-empty cases list")
    validated = []
    seen = set()
    for item in cases:
        if not isinstance(item, dict) or not _REQUIRED_CASE_KEYS <= set(item):
            raise FixtureError("every fixture case must contain the required challenge fields")
        if not isinstance(item["id"], str) or not item["id"] or item["id"] in seen:
            raise FixtureError("fixture case ids must be unique non-empty strings")
        if item["citation_state"] not in _CASE_STATES or item["format"] not in _FORMATS:
            raise FixtureError("fixture case has an unsupported citation_state or format")
        if item["expected_review"] not in _REVIEWS or not isinstance(item["expected_reason_tags"], list):
            raise FixtureError("fixture case has invalid expected review metadata")
        if not all(isinstance(item[key], str) and item[key].strip() for key in ("evidence_text", "claim_text")):
            raise FixtureError("fixture evidence_text and claim_text must be non-empty strings")
        seen.add(item["id"])
        validated.append(copy.deepcopy(item))
    return validated, _sha256_bytes(raw)


def _synthetic_runtime(response: str) -> GovernedModelClient:
    def create(**_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response), finish_reason="stop")]
        )

    return GovernedModelClient(
        completion_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="synthetic_sdk_mock",
        is_local=False,
    )


def _case_report(case: dict) -> tuple[str, dict, dict]:
    source = {
        "source_id": "fixture-support",
        "chunk_id": "fixture-support-1",
        "title": "Synthetic fixture support",
        "agency": "Synthetic test authority",
        "text": _FIXTURE_CITATION.sub("", case["evidence_text"]).strip(),
        "jurisdictions": [case["region"]],
    }
    unrelated = {
        "source_id": "fixture-unrelated",
        "chunk_id": "fixture-unrelated-1",
        "title": "Synthetic unrelated fixture passage",
        "agency": "Synthetic test authority",
        "text": "Archive catalogue numbering and office stationery procedures.",
        "jurisdictions": [case["region"]],
    }
    citation = ""
    if case["citation_state"] == "correct":
        # Challenge fixtures test the human-visible canonical label, not an
        # opaque request token. The identity and title must both match.
        citation = " " + format_rag_attribution(source)
    elif case["citation_state"] == "wrong":
        citation = " " + format_rag_attribution(unrelated)
    if _FIXTURE_CITATION.search(case["claim_text"]):
        # Translate synthetic source annotations at their original locations;
        # do not append an application citation behind an unknown marker.
        claim = _FIXTURE_CITATION.sub(lambda _match: citation.strip(), case["claim_text"]).strip()
    else:
        claim = case["claim_text"] + citation
    if _table_body_cells(case) is not None:
        report = claim
    elif case["format"] == "table":
        report = "| Action | Detail |\n| --- | --- |\n| Target | " + claim + " |"
    elif case["format"] == "long_sentence":
        # The fixture itself owns the sentence boundary and its classification.
        # Do not prepend or append narrative that changes the frozen claim.
        report = claim
    else:
        report = "## Preparedness\n\n" + claim
    assembly = assemble_retrieved_context({"retrieved_chunks": [source, unrelated]})
    analysis = {
        "profile": {"state": case["region"]},
        "knowledge": {"status": "ready", "retrieved_chunks": [source, unrelated]},
    }
    return report, analysis, assembly


def _capture_snapshot(report: str, assembly: dict) -> dict:
    runtime = _synthetic_runtime(report)
    prompt = EvidencePrompt("Synthetic offline evaluation\n" + assembly["context"], assembly=assembly)
    response = runtime.generate(prompt)
    snapshot = capture_model_evidence(prompt, runtime, response, attempt_number=1)
    bound = bind_normalized_narrative(snapshot, response)
    if bound.get("status") != "captured":
        raise FixtureError("synthetic SDK mock did not produce a captured submission snapshot")
    return bound


def _claim_entries(result: dict) -> list[dict]:
    claims = result.get("claims")
    processing = result.get("processing")
    if not isinstance(processing, dict) or processing.get("complete") is not True:
        raise FixtureError("evaluator returned incomplete processing")
    if not isinstance(claims, list):
        raise FixtureError("evaluator returned no claims list")
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str):
            raise FixtureError("evaluator returned an invalid claim record")
        required = {"citation_required", "citation_status", "support_status", "reasons", "source_checks"}
        if not required <= set(claim) or not isinstance(claim["reasons"], list):
            raise FixtureError("evaluator claim record lacks required evidence fields")
    return claims


def _target_claims(case: dict, claims: list[dict], *, analysis: dict | None = None) -> list[dict]:
    cells = _table_body_cells(case)
    if cells is not None:
        matches = [claim for claim in claims if claim.get("block_type") == "table_cell"]
        grouped = {}
        for claim in matches:
            coordinate = (claim.get("table_row"), claim.get("table_column"))
            grouped.setdefault(coordinate, []).append(claim)
        if set(grouped) != set(cells):
            raise FixtureError("target table body cells were not completely extracted")
        sources = ((analysis or {}).get("knowledge") or {}).get("retrieved_chunks", [])
        for coordinate, expected in cells.items():
            extracted = " ".join(str(claim.get("claim", "")) for claim in grouped[coordinate])
            extracted = strip_known_attribution_labels(extracted, rag_sources=sources)
            # The shared row parser unescapes a literal cell pipe. All other
            # asserted text, including every sentence, must still be present.
            extracted = extracted.replace("\\|", "|")
            if " ".join(extracted.split()) != " ".join(expected.split()):
                raise FixtureError("target table cell text was not completely extracted")
        return matches
    target = _natural_claim(case)
    matches = [claim for claim in claims if target in str(claim.get("claim", ""))]
    if not matches:
        raise FixtureError("target claim was not extracted; it cannot be silently omitted")
    return matches


def _reason_codes(claims: list[dict]) -> list[str]:
    return sorted({str(reason) for claim in claims for reason in claim["reasons"]})


def _review_required(claims: list[dict]) -> bool:
    return any(
        bool(claim["reasons"])
        or claim.get("citation_status") == "missing"
        or claim.get("support_status") in {"no_lexical_match", "unknown"}
        for claim in claims
    )


def _case_result(case: dict) -> dict:
    report, analysis, assembly = _case_report(case)
    started = time.perf_counter()
    snapshot = _capture_snapshot(report, assembly)
    result = evaluate_body_claim_evidence(report, analysis, snapshot=snapshot)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    if not isinstance(result, dict) or result.get("method") != METHOD:
        raise FixtureError("evaluator returned an unsupported result schema")
    claims = _target_claims(case, _claim_entries(result), analysis=analysis)
    actual_review = _review_required(claims)
    expected_review = case["expected_review"] == "required"
    expected_citation = "missing" if case["citation_state"] == "missing" else "cited"
    actual_citations = sorted({claim["citation_status"] for claim in claims})
    actual_support = sorted({claim["support_status"] for claim in claims})
    expectation_mismatches = []
    # Citation identity does not tell us whether the cited claim is supported.
    # In particular, a correct source can be quoted with reversed meaning, and
    # an explicitly unknown/procedural statement may require no citation.
    if expected_citation not in actual_citations and not (
        case["citation_state"] == "missing" and "not_required" in actual_citations
    ):
        expectation_mismatches.append("citation_status")
    return {
        "id": case["id"],
        "status": "review_required" if actual_review else "clear",
        "expected_review": case["expected_review"],
        "reason_codes": _reason_codes(claims),
        # Fixture tags remain descriptive coverage metadata: evaluator reason
        # labels need not be identical unless a separately frozen mapping exists.
        "reason_tag_coverage": {
            "expected_tags": sorted(str(tag) for tag in case["expected_reason_tags"]),
            "actual_reason_codes": _reason_codes(claims),
            "comparison": "descriptive_not_exact_label_assertion",
        },
        "citation_statuses": actual_citations,
        "support_statuses": actual_support,
        "expectation_mismatches": expectation_mismatches,
        "claim_count": len(claims),
        "latency_ms": elapsed_ms,
        "false_accept": expected_review and not actual_review,
        "unnecessary_review": not expected_review and actual_review,
        "snapshot_status": snapshot["status"],
        "provenance": "synthetic_sdk_mock",
        "fixture_adapter": "synthetic_citation_annotations_and_complete_table_cells_v2",
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    return round(values[lower] + (values[upper] - values[lower]) * (position - lower), 3)


def evaluate_fixture(path: Path) -> dict:
    cases, fixture_sha = _load_fixture(path)
    outcomes, extraction_misses = [], []
    started = time.perf_counter()
    for case in cases:
        try:
            outcomes.append(_case_result(case))
        except FixtureError as error:
            extraction_misses.append({"id": case["id"], "reason_code": str(error)})
    latencies = sorted(item["latency_ms"] for item in outcomes)
    false_accepts = [item["id"] for item in outcomes if item["false_accept"]]
    unnecessary = [item["id"] for item in outcomes if item["unnecessary_review"]]
    expectation_mismatches = [
        {"id": item["id"], "checks": item["expectation_mismatches"]}
        for item in outcomes
        if item["expectation_mismatches"]
    ]
    expected_required = sum(case["expected_review"] == "required" for case in cases)
    actual_required = sum(item["status"] == "review_required" for item in outcomes)
    return {
        "method": METHOD,
        "scope": "final_sdk_submitted_rag_passages_only",
        "provenance": "synthetic_sdk_mock",
        "evaluation_phase": "seen_case_regression",
        "interpretation": "Post-inspection diagnostic regression; not unseen performance or semantic accuracy.",
        "fixture_byte_sha256": fixture_sha,
        "evaluated_source_sha256": _source_sha(),
        "git": _git_context(),
        "model_calls": 0,
        "retrieval_calls": 0,
        "embedding_calls": 0,
        "cost_note": "not a live cost benchmark",
        "counts": {"cases": len(cases), "evaluated_cases": len(outcomes), "extraction_misses": len(extraction_misses)},
        "confusion_matrix": {
            "true_positive": sum(
                item["expected_review"] == "required" and item["status"] == "review_required" for item in outcomes
            ),
            "true_negative": sum(
                item["expected_review"] == "not_required" and item["status"] == "clear" for item in outcomes
            ),
            "false_positive": len(unnecessary),
            "false_negative": len(false_accepts),
            "expected_review_required": expected_required,
            "actual_review_required": actual_required,
        },
        "false_accept_ids": false_accepts,
        "unnecessary_review_ids": unnecessary,
        "expectation_mismatches": expectation_mismatches,
        "extraction_misses": extraction_misses,
        "cases": outcomes,
        "latency_ms": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "total": round((time.perf_counter() - started) * 1000, 3),
        },
        "gate": {
            "passed": not false_accepts and not extraction_misses,
            "failure_reasons": (["false_accepts"] if false_accepts else [])
            + (["extraction_misses"] if extraction_misses else []),
        },
    }


def _unique_output(path: Path | None) -> Path:
    if path is not None:
        if path.exists():
            raise FileExistsError("refusing to overwrite an existing output file")
        return path
    DEFAULT_OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return DEFAULT_OUTPUT_DIRECTORY / f"content-quality-{stamp}-{os.getpid()}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        output = _unique_output(args.output)
        report = evaluate_fixture(args.fixture)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    except (OSError, FixtureError, FileExistsError) as error:
        print(f"content evaluation failed: {error}", file=sys.stderr)
        return 2
    print(output)
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
