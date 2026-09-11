"""Diagnose real form-to-query retrieval and initial-prompt visible evidence.

This is a separate diagnostic, not the historical question-set release gate.
It runs the deterministic application pipeline and builds (but never sends) the
initial report prompt. Only hashes, identities, offsets and scores are exported.
Literal phrase coverage is not semantic relevance, groundedness or answer quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_rag import build_run_metadata  # noqa: E402
from scripts.evaluation_artifacts import (  # noqa: E402
    _validate_index_provenance,
    canonical_sha256,
    require_stable_release_provenance,
)
from src.agents.official_knowledge_agent import OFFICIAL_QUERY_SCHEMA, build_official_query  # noqa: E402
from src.agents.pipeline import run_analysis_pipeline  # noqa: E402
from src.agents.planner_agent import PlannerAgent  # noqa: E402
from src.app_catalog import CONCERN_OPTIONS, SCENARIO_OPTIONS, TIMEFRAME_OPTIONS  # noqa: E402
from src.rag.service import (  # noqa: E402
    CONTEXT_ASSEMBLY_SCHEMA,
    DEFAULT_CHUNK_CHARACTERS,
    DEFAULT_CONTEXT_CHARACTERS,
    RagService,
    assemble_retrieved_context,
    normalise_retrieval_query,
)
from src.report_template import build_report_prompt  # noqa: E402

SUITE_SCHEMA = "rag-form-context-suite-v1"
ARTIFACT_SCHEMA = "rag-form-context-diagnostic-v1"
FORM_FIELDS = {"location", "audience", "scenario", "concerns", "timeframe", "extra_context"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_STABILITY_FIELDS = ("questions_sha256", "git", "rag_index", "embedding_model")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require(condition, detail):
    if not condition:
        raise ValueError("Invalid form RAG diagnostic: " + detail)


def validate_form_suite(payload):
    _require(isinstance(payload, dict) and payload.get("schema") == SUITE_SCHEMA, "suite schema")
    cases = payload.get("cases")
    _require(isinstance(cases, list) and 0 < len(cases) <= 100, "case count")
    case_ids = set()
    for case in cases:
        _require(isinstance(case, dict), "case mapping")
        case_id = case.get("id")
        _require(isinstance(case_id, str) and re.fullmatch(r"[a-z0-9_-]{1,80}", case_id), "case id")
        _require(case_id not in case_ids, "duplicate case id")
        case_ids.add(case_id)
        form = case.get("form")
        _require(isinstance(form, dict) and set(form) == FORM_FIELDS, "actual form fields required")
        for name in FORM_FIELDS - {"concerns"}:
            value = form[name]
            _require(isinstance(value, str) and len(value) <= 4000, "bounded form text")
            _require(name == "extra_context" or bool(value.strip()), "empty form field")
        _require(form["scenario"] in SCENARIO_OPTIONS, "application scenario")
        _require(form["timeframe"] in TIMEFRAME_OPTIONS, "application timeframe")
        concerns = form["concerns"]
        _require(isinstance(concerns, list) and 0 < len(concerns) <= len(CONCERN_OPTIONS), "concern list")
        _require(all(isinstance(item, str) and item in CONCERN_OPTIONS for item in concerns), "application concerns")
        _require(len(set(concerns)) == len(concerns), "duplicate concern")
        selected = {item["id"] for item in PlannerAgent._resolve_focus_areas(concerns)[0]}
        targets = case.get("targets")
        _require(isinstance(targets, list) and 0 < len(targets) <= 30, "target count")
        target_ids = set()
        for target in targets:
            _require(isinstance(target, dict), "target mapping")
            target_id = target.get("id")
            _require(isinstance(target_id, str) and re.fullmatch(r"[a-z0-9_-]{1,80}", target_id), "target id")
            _require(target_id not in target_ids, "duplicate target id")
            target_ids.add(target_id)
            _require(target.get("focus_id") in selected, "target is not a selected focus")
            for field in ("expected_source_ids", "expected_terms"):
                values = target.get(field)
                _require(isinstance(values, list) and 0 < len(values) <= 12, "nonempty target sources and phrases")
                _require(
                    all(isinstance(value, str) and value.strip() and len(value) <= 200 for value in values),
                    "bounded target text",
                )
                _require(len({value.casefold() for value in values}) == len(values), "duplicate target value")
    return cases


def _span(text, term):
    match = re.search(re.escape(term), text, flags=re.IGNORECASE)
    return list(match.span()) if match else None


def _score_target(target, chunks, assembly):
    visible = {chunk["retrieved_rank"]: chunk["text"] for chunk in assembly["visible_chunks"]}
    witnesses = []
    for rank, chunk in enumerate(chunks, 1):
        if chunk["source_id"] not in target["expected_source_ids"]:
            continue
        witnesses.append(
            {
                "retrieved_rank": rank,
                "terms": [
                    {
                        "term_index": index,
                        "raw_span": _span(chunk["text"], term),
                        "visible_span": _span(visible[rank], term) if rank in visible else None,
                    }
                    for index, term in enumerate(target["expected_terms"])
                ],
            }
        )
    return {"id": target["id"], "focus_id": target["focus_id"], "witnesses": witnesses, **_witness_scores(witnesses)}


def _witness_scores(witnesses):
    raw = [row["retrieved_rank"] for row in witnesses if all(term["raw_span"] is not None for term in row["terms"])]
    visible = [
        row["retrieved_rank"]
        for row in witnesses
        if row["retrieved_rank"] in raw and all(term["visible_span"] is not None for term in row["terms"])
    ]
    return {
        "retrieved_source_ranks": [row["retrieved_rank"] for row in witnesses],
        "retrieved_passage_ranks": raw,
        "visible_passage_ranks": visible,
    }


def _summary(rows):
    targets = [target for row in rows for target in row["targets"]]
    source = sum(bool(target["retrieved_source_ranks"]) for target in targets)
    retrieved = sum(bool(target["retrieved_passage_ranks"]) for target in targets)
    visible = sum(bool(target["visible_passage_ranks"]) for target in targets)
    selected_focus_count = sum(len(row["profile"]["focus_ids"]) for row in rows)
    assessed_focus_count = sum(len({target["focus_id"] for target in row["targets"]}) for row in rows)
    covered_focus_count = sum(
        all(target["visible_passage_ranks"] for target in row["targets"] if target["focus_id"] == focus)
        for row in rows
        for focus in {target["focus_id"] for target in row["targets"]}
    )
    return {
        "case_count": len(rows),
        "target_count": len(targets),
        "retrieved_source_hit_count": source,
        "retrieved_source_hit_rate": round(source / len(targets), 6),
        "retrieved_passage_hit_count": retrieved,
        "retrieved_passage_hit_rate": round(retrieved / len(targets), 6),
        "visible_passage_hit_count": visible,
        "visible_passage_hit_rate": round(visible / len(targets), 6),
        "retrieved_passage_hit_but_not_visible_count": retrieved - visible,
        "selected_focus_count": selected_focus_count,
        "assessed_focus_count": assessed_focus_count,
        "unassessed_focus_count": selected_focus_count - assessed_focus_count,
        "fully_visible_assessed_focus_count": covered_focus_count,
        "fully_visible_assessed_focus_rate": round(covered_focus_count / assessed_focus_count, 6),
        "all_targets_visible_case_count": sum(
            all(target["visible_passage_ranks"] for target in row["targets"]) for row in rows
        ),
        "retrieved_chunk_count": sum(row["assembly"]["retrieved_count"] for row in rows),
        "visible_chunk_count": sum(row["assembly"]["included_count"] for row in rows),
        "per_chunk_truncated_count": sum(
            entry["reason"] == "per_chunk_character_budget" for row in rows for entry in row["assembly"]["chunks"]
        ),
        "total_budget_dropped_count": sum(not entry["included"] for row in rows for entry in row["assembly"]["chunks"]),
    }


def run_form_evaluation(payload, service, *, data_paths=None, run_metadata=None, provenance_check=None):
    cases = validate_form_suite(payload)
    rows = []
    for case in cases:
        if provenance_check:
            provenance_check(case["id"] + ":before")
        form = case["form"]
        analysis = run_analysis_pipeline(**form, data_paths=data_paths, knowledge_service=service)
        knowledge = analysis["knowledge"]
        _require(
            knowledge.get("status") in {"ready", "no_match", "out_of_scope"}, "retrieval unavailable: " + case["id"]
        )
        if provenance_check:
            provenance_check(case["id"] + ":after", knowledge)
        query, components = build_official_query(
            analysis["profile"], form["scenario"], form["concerns"], form["timeframe"]
        )
        query = normalise_retrieval_query(query)
        _require(knowledge.get("query_sha256") == _sha(query), "retrieved query differs from application query")
        _require(knowledge.get("query_components") == components, "query components differ")
        chunks = knowledge.get("retrieved_chunks", [])
        _require(knowledge["status"] == "ready" or not chunks, "unready result has passages")
        assembly = assemble_retrieved_context(knowledge)
        for entry in assembly["manifest"]["chunks"]:
            _require(entry["declared_chunk_sha256"] == entry["raw_text_sha256"], "retrieved chunk hash mismatch")
        prompt = build_report_prompt(
            **form, analysis=analysis, governance_context="Diagnostic draft; responsible human review required."
        ).strip()
        context = assembly["context"]
        _require(prompt.count(context) == 1, "assembled evidence differs from the actual initial prompt")
        profile = analysis["profile"]
        rows.append(
            {
                "id": case["id"],
                "form_sha256": canonical_sha256(form),
                "query": {
                    "schema": OFFICIAL_QUERY_SCHEMA,
                    "sha256": _sha(query),
                    "components_sha256": canonical_sha256(components),
                },
                "profile": {
                    "state": profile["state"],
                    "locality": profile["locality"],
                    "setting_type": profile["setting_type"],
                    "scenario_id": profile["scenario_concept"]["id"],
                    "timeframe_id": profile["timeframe_concept"]["id"],
                    "focus_ids": [item["id"] for item in analysis["plan"]["focus_area_concepts"]],
                },
                "status": knowledge["status"],
                "retrieval_configuration": knowledge.get("retrieval_configuration", {}),
                "index_manifest_sha256": knowledge.get("index_manifest_sha256", ""),
                "data_provenance_sha256": canonical_sha256(analysis["data_provenance"]),
                "initial_prompt": {
                    "sha256": _sha(prompt),
                    "characters": len(prompt),
                    "context_start": prompt.index(context),
                    "context_end": prompt.index(context) + len(context),
                },
                "assembly": assembly["manifest"],
                "targets": [_score_target(target, chunks, assembly) for target in case["targets"]],
            }
        )
    output = {
        "artifact_schema": ARTIFACT_SCHEMA,
        "suite_schema": SUITE_SCHEMA,
        "suite_sha256": canonical_sha256(payload),
        "prompt_stage": "initial_generation",
        "prompt_boundary": "governed_model_client_user_message_after_strip",
        "matching_rule": "case_insensitive_literal_phrases_in_one_expected_source_chunk; visible_requires_raw_match",
        "release_gate": {"active": False, "passed": None},
        "run": dict(run_metadata or {"provenance": "not_collected_test_or_in_memory_run"}),
        "rows": rows,
        "summary": _summary(rows),
    }
    validate_form_evaluation_artifact(output, payload)
    return output


def _check_span(span, text_length, term_length):
    if span is not None:
        _require(isinstance(span, list) and len(span) == 2 and all(type(value) is int for value in span), "term span")
        _require(0 <= span[0] < span[1] <= text_length and span[1] - span[0] == term_length, "term span bounds")


def _validate_run_bindings(output, payload, suite_bytes):
    run = output.get("run")
    _require(isinstance(run, dict), "run provenance mapping")
    if run == {"provenance": "not_collected_test_or_in_memory_run"}:
        _require(suite_bytes is None, "run provenance required to verify exact suite bytes")
        return

    _require(run.get("questions_hash_basis") == "exact_file_bytes", "suite file hash basis")
    _require(
        isinstance(run.get("questions_sha256"), str) and _HASH.fullmatch(run["questions_sha256"]),
        "suite file hash",
    )
    _require(run.get("questions_schema_version") == payload.get("schema_version"), "suite schema version binding")
    if suite_bytes is not None:
        _require(isinstance(suite_bytes, bytes), "suite_bytes must be original bytes, not serialised JSON text")
        try:
            supplied = json.loads(suite_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("Invalid form RAG diagnostic: suite bytes are not valid UTF-8 JSON") from error
        _require(canonical_sha256(supplied) == canonical_sha256(payload), "suite bytes and parsed fixture differ")
        _require(hashlib.sha256(suite_bytes).hexdigest() == run["questions_sha256"], "exact suite bytes hash binding")

    index = run.get("rag_index")
    _require(isinstance(index, dict) and index.get("status") == "verified", "verified run index required")
    _require(index.get("schema") in {"bushfire-rag-index-v3", "bushfire-rag-index-v4"}, "digest-bound index schema")
    try:
        _validate_index_provenance(index)
    except ValueError as error:
        raise ValueError("Invalid form RAG diagnostic: run index identity is inconsistent") from error
    for field in ("source_count", "chunk_count", "embedding_dimension"):
        _require(type(index.get(field)) is int and index[field] > 0, "positive run index " + field)
    identity = index["embedding_identity"]
    model = run.get("embedding_model")
    _require(
        isinstance(model, dict) and model.get("digest_status") == "resolved", "resolved run model identity required"
    )
    _require(
        isinstance(model.get("digest"), str)
        and _HASH.fullmatch(model["digest"])
        and model["digest"] == identity.get("digest"),
        "run model digest differs from index identity",
    )
    _require(
        model.get("provider") == index.get("embedding_provider") == identity.get("provider"),
        "run model provider differs from index",
    )
    _require(
        isinstance(model.get("name"), str) and bool(model["name"]) and model["name"] == identity.get("model"),
        "run model name differs from index",
    )
    _require(
        type(model.get("dimension")) is int and model["dimension"] == index["embedding_dimension"],
        "run model dimension differs from index",
    )
    distinct_chunks = set()
    distinct_sources = set()
    for row in output["rows"]:
        _require(row["index_manifest_sha256"] == index["manifest_sha256"], "row index differs from run index")
        for entry in row["assembly"]["chunks"]:
            distinct_chunks.add(entry["chunk_id"])
            distinct_sources.add(entry["source_id"])
    _require(len(distinct_chunks) <= index["chunk_count"], "retrieved chunks exceed run index count")
    _require(len(distinct_sources) <= index["source_count"], "retrieved sources exceed run index count")


def validate_form_evaluation_artifact(output, payload, *, suite_bytes=None):
    """Check suite binding and recompute scores from bounded phrase witnesses.

    Run/index/model identities and row bindings are checked offline. The parsed
    fixture binds canonical JSON content only: its exact-file hash is verified
    ONLY when the caller supplies original ``suite_bytes``. No file is opened
    based on an artifact path. Without bytes, exact-file hash verification has
    not occurred; reserialising the parsed fixture cannot establish it.

    This verifies consistency, not truth of unauthenticated JSON. Source/model
    files and the claimed Git revision still need independent replay. Explicit
    in-memory runs without collected provenance validate scores only.
    """
    cases = validate_form_suite(payload)
    _require(
        output.get("artifact_schema") == ARTIFACT_SCHEMA and output.get("suite_schema") == SUITE_SCHEMA,
        "artifact schema",
    )
    _require(output.get("suite_sha256") == canonical_sha256(payload), "suite binding")
    _require(output.get("prompt_stage") == "initial_generation", "prompt stage")
    _require(output.get("prompt_boundary") == "governed_model_client_user_message_after_strip", "prompt boundary")
    _require(output.get("release_gate") == {"active": False, "passed": None}, "diagnostic is not a release gate")
    rows = output.get("rows")
    _require(isinstance(rows, list) and len(rows) == len(cases), "row count")
    for row, case in zip(rows, cases, strict=True):
        _require(
            row.get("id") == case["id"] and row.get("form_sha256") == canonical_sha256(case["form"]), "case binding"
        )
        focus_ids = [item["id"] for item in PlannerAgent._resolve_focus_areas(case["form"]["concerns"])[0]]
        _require(row["profile"]["focus_ids"] == focus_ids, "selected focus binding")
        query, components = build_official_query(
            row["profile"], case["form"]["scenario"], case["form"]["concerns"], case["form"]["timeframe"]
        )
        query = normalise_retrieval_query(query)
        _require(
            row["query"]
            == {
                "schema": OFFICIAL_QUERY_SCHEMA,
                "sha256": _sha(query),
                "components_sha256": canonical_sha256(components),
            },
            "query identity",
        )
        manifest = row["assembly"]
        _require(
            manifest["schema"] == CONTEXT_ASSEMBLY_SCHEMA and manifest["length_unit"] == "unicode_code_points",
            "assembly schema",
        )
        _require(
            manifest["max_characters"] == DEFAULT_CONTEXT_CHARACTERS
            and manifest["max_chunk_characters"] == DEFAULT_CHUNK_CHARACTERS,
            "production context budgets",
        )
        entries = manifest["chunks"]
        _require(
            manifest["retrieved_count"] == len(entries)
            and manifest["included_count"] == sum(entry["included"] is True for entry in entries),
            "assembly counts",
        )
        _require(
            row["status"] in {"ready", "no_match", "out_of_scope"} and (row["status"] == "ready" or not entries),
            "retrieval status",
        )
        _require(0 < manifest["context_characters"] <= DEFAULT_CONTEXT_CHARACTERS, "context length")
        initial = row["initial_prompt"]
        _require(
            0 <= initial["context_start"] < initial["context_end"] <= initial["characters"], "initial prompt bounds"
        )
        _require(
            initial["context_end"] - initial["context_start"] == manifest["context_characters"],
            "initial prompt context length",
        )
        for digest in (
            initial["sha256"],
            manifest["context_sha256"],
            row["data_provenance_sha256"],
            row["index_manifest_sha256"],
        ):
            _require(isinstance(digest, str) and _HASH.fullmatch(digest), "provenance hash")
        exhausted = False
        previous_end = -1
        for rank, entry in enumerate(entries, 1):
            _require(
                entry["retrieved_rank"] == rank
                and isinstance(entry["source_id"], str)
                and isinstance(entry["chunk_id"], str),
                "chunk identity",
            )
            _require(entry["declared_chunk_sha256"] == entry["raw_text_sha256"], "chunk hash binding")
            for field in ("raw_text_sha256", "sanitised_text_sha256"):
                _require(isinstance(entry[field], str) and _HASH.fullmatch(entry[field]), "text hash")
            _require(
                type(entry["included"]) is bool
                and type(entry["raw_characters"]) is int
                and entry["raw_characters"] >= 0,
                "chunk fields",
            )
            _require(
                type(entry["sanitised_characters"]) is int and entry["sanitised_characters"] >= 0, "sanitised length"
            )
            if entry["included"]:
                size = min(entry["sanitised_characters"], DEFAULT_CHUNK_CHARACTERS)
                _require(
                    not exhausted and entry["visible_start"] == 0 and entry["visible_end"] == size, "visible prefix"
                )
                _require(
                    previous_end < entry["context_start"] <= entry["context_end"] <= manifest["context_characters"],
                    "visible context bounds",
                )
                _require(entry["context_end"] - entry["context_start"] == size, "visible context size")
                _require(
                    entry["reason"]
                    == ("per_chunk_character_budget" if size < entry["sanitised_characters"] else "complete"),
                    "truncation reason",
                )
                _require(
                    isinstance(entry["visible_text_sha256"], str) and _HASH.fullmatch(entry["visible_text_sha256"]),
                    "visible hash",
                )
                previous_end = entry["context_end"]
            else:
                _require(
                    entry["reason"] == ("after_total_budget_stop" if exhausted else "total_character_budget"),
                    "drop reason",
                )
                _require(
                    all(
                        entry[field] is None
                        for field in (
                            "visible_start",
                            "visible_end",
                            "visible_text_sha256",
                            "context_start",
                            "context_end",
                        )
                    ),
                    "omitted bytes cannot be visible",
                )
                exhausted = True
        _require(len(row["targets"]) == len(case["targets"]), "target count")
        for observed, target in zip(row["targets"], case["targets"], strict=True):
            _require(observed["id"] == target["id"] and observed["focus_id"] == target["focus_id"], "target binding")
            expected_ranks = [
                entry["retrieved_rank"] for entry in entries if entry["source_id"] in target["expected_source_ids"]
            ]
            witnesses = observed["witnesses"]
            _require([item["retrieved_rank"] for item in witnesses] == expected_ranks, "source witness ranks")
            for witness in witnesses:
                entry = entries[witness["retrieved_rank"] - 1]
                _require(len(witness["terms"]) == len(target["expected_terms"]), "phrase count")
                for index, (term, expected) in enumerate(zip(witness["terms"], target["expected_terms"], strict=True)):
                    _require(term["term_index"] == index, "phrase identity")
                    _check_span(term["raw_span"], entry["raw_characters"], len(expected))
                    _check_span(term["visible_span"], entry["visible_end"] or 0, len(expected))
            _require(
                all(observed.get(field) == value for field, value in _witness_scores(witnesses).items()),
                "target scores do not match witnesses",
            )
    _require(output.get("summary") == _summary(rows), "summary does not match rows")
    _validate_run_bindings(output, payload, suite_bytes)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite", type=Path, default=PROJECT_ROOT / "data_australia" / "rag" / "form_evaluation_v1.json"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New diagnostic JSON path; existing files are never replaced."
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; use a new diagnostic artifact path.")
    suite_bytes = args.suite.read_bytes()
    payload = json.loads(suite_bytes.decode("utf-8"))
    validate_form_suite(payload)
    service = RagService()
    baseline = build_run_metadata(payload, args.suite, service)

    def check(label, result=None):
        current = build_run_metadata(payload, args.suite, service)
        require_stable_release_provenance(
            baseline, current, _STABILITY_FIELDS, label=label, artifact_name="Form RAG diagnostic"
        )
        if result is not None:
            _require(
                result.get("index_manifest_sha256") == baseline["rag_index"].get("manifest_sha256"),
                "index identity changed during retrieval",
            )

    output = run_form_evaluation(payload, service, run_metadata=baseline, provenance_check=check)
    check("completion")
    output["run"]["provenance_stability"] = {"checked": True, "stable": True, "drift_fields": []}
    output["run"]["completed_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    validate_form_evaluation_artifact(output, payload, suite_bytes=suite_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(
        json.dumps(
            {"artifact_schema": ARTIFACT_SCHEMA, "release_gate": output["release_gate"], "summary": output["summary"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
