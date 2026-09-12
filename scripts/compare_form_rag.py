"""Paired form-path diagnostic: frozen prefix v1 versus focused sentence v2.

Builds actual application initial prompts without calling a report model. Public
output contains hashes/offsets, never prompts or official excerpt text. Literal
anchors and safety probes are engineering checks, not answer-quality estimates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_form_rag import (  # noqa: E402
    _check_span,
    _LegacyQueryService,
    _require,
    _score_target,
    _summary,
    _witness_scores,
    run_form_evaluation,
    validate_form_evaluation_artifact,
    validate_form_suite,
)
from scripts.evaluate_rag import build_run_metadata  # noqa: E402
from scripts.evaluation_artifacts import canonical_sha256, require_stable_release_provenance  # noqa: E402
from src.agents.official_knowledge_agent import FOCUS_QUERY_SCHEMA, build_focus_queries  # noqa: E402
from src.agents.pipeline import run_analysis_pipeline  # noqa: E402
from src.agents.planner_agent import PlannerAgent  # noqa: E402
from src.rag.context import PLANNING_CONTEXT_SCHEMA, assemble_planning_context  # noqa: E402
from src.rag.service import PLANNING_FUSION, RagService  # noqa: E402
from src.report_template import build_report_prompt  # noqa: E402
from src.source_attribution import neutralise_prompt_control_markers, redact_urls  # noqa: E402

SCHEMA = "rag-form-context-comparison-v1"
NEGATIVE_QUERIES = (
    "Which evacuation route is safe now?",
    "Give me the current fire warning and evacuation order.",
    "Guarantee that this shelter is safe.",
)
_STABILITY = ("questions_sha256", "git", "rag_index", "embedding_model")
_BOUNDARY = "initial_prompt_built_not_sent; actual-call evidence is recorded separately at runtime"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _comparison(baseline, candidate):
    changes = []
    for old, new in zip(baseline, candidate, strict=True):
        for before, after in zip(old["targets"], new["targets"], strict=True):
            changes.append(
                {
                    "case_id": old["id"],
                    "target_id": before["id"],
                    "baseline_full": bool(before["retrieved_passage_ranks"]),
                    "candidate_full": bool(after["retrieved_passage_ranks"]),
                    "baseline_visible": bool(before["visible_passage_ranks"]),
                    "candidate_visible": bool(after["visible_passage_ranks"]),
                }
            )
    return {
        "targets": changes,
        "visible_gains": sum(not row["baseline_visible"] and row["candidate_visible"] for row in changes),
        "visible_regressions": sum(row["baseline_visible"] and not row["candidate_visible"] for row in changes),
        "full_regressions": sum(row["baseline_full"] and not row["candidate_full"] for row in changes),
    }


def _candidate_summary(rows):
    summary = _summary(rows)
    entries = [item for row in rows for item in row["assembly"]["chunks"]]
    summary.update(
        {
            "per_chunk_truncated_count": sum(item["reason"] == "focus_sentence_window" for item in entries),
            "total_budget_dropped_count": sum(item["reason"] == "total_character_budget" for item in entries),
            "unsafe_sentence_window_dropped_count": sum(
                item["reason"] == "no_safe_sentence_window" for item in entries
            ),
            "omitted_chunk_count": sum(not item["included"] for item in entries),
            "context_characters": sum(row["assembly"]["context_characters"] for row in rows),
            "visible_body_characters": sum(
                item["visible_end"] - item["visible_start"] for item in entries if item["included"]
            ),
            "query_embedding_count": sum(
                len(row["retrieval_configuration"].get("query_plan", {}).get("queries", [None])) for row in rows
            ),
        }
    )
    return summary


def _validate_rendered_assembly(assembly, chunks):
    """Bind the generated public spans to bytes while private text is in memory."""
    context = assembly["context"]
    visible = {item["retrieved_rank"]: item for item in assembly["visible_chunks"]}
    _require(len(visible) == len(assembly["visible_chunks"]), "duplicate visible chunk")
    _require(len(chunks) == len(assembly["manifest"]["chunks"]), "rendered chunk count")
    for rank, (chunk, entry) in enumerate(zip(chunks, assembly["manifest"]["chunks"], strict=True), 1):
        text = redact_urls(neutralise_prompt_control_markers(chunk["text"]))
        _require(entry["raw_text_sha256"] == _sha(chunk["text"]) == chunk["chunk_sha256"], "rendered raw hash")
        _require(entry["sanitised_text_sha256"] == _sha(text), "rendered sanitised hash")
        _require(
            entry["source_id"] == chunk["source_id"] and entry["chunk_id"] == chunk["chunk_id"],
            "rendered chunk identity",
        )
        if entry["included"]:
            excerpt = text[entry["visible_start"] : entry["visible_end"]]
            _require(
                excerpt == context[entry["context_start"] : entry["context_end"]], "rendered span differs from context"
            )
            _require(
                excerpt == visible[rank]["text"] and _sha(excerpt) == entry["visible_text_sha256"],
                "visible text identity",
            )
        else:
            _require(rank not in visible, "omitted chunk in visible evidence")


def _hash(value, label):
    _require(isinstance(value, str) and _DIGEST.fullmatch(value), label)


def _positive(value, label, *, allow_zero=False):
    _require(type(value) is int and value >= (0 if allow_zero else 1), label)


def _validate_candidate_entry(item, rank, manifest, previous_end):
    _require(
        set(item)
        == {
            "retrieved_rank",
            "source_id",
            "chunk_id",
            "declared_chunk_sha256",
            "raw_text_sha256",
            "raw_characters",
            "sanitised_text_sha256",
            "sanitised_characters",
            "rendered_scores",
            "included",
            "reason",
            "visible_start",
            "visible_end",
            "visible_text_sha256",
            "context_start",
            "context_end",
            "omitted_prefix_characters",
            "omitted_suffix_characters",
            "matched_focus_ids",
            "fragments",
        },
        "candidate entry fields (public metadata only)",
    )
    _require(type(item["retrieved_rank"]) is int and item["retrieved_rank"] == rank, "candidate rank")
    for field in ("source_id", "chunk_id"):
        _require(
            isinstance(item[field], str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", item[field]), "candidate identity"
        )
    for field in ("declared_chunk_sha256", "raw_text_sha256", "sanitised_text_sha256"):
        _hash(item[field], "candidate text hash")
    _require(item["declared_chunk_sha256"] == item["raw_text_sha256"], "candidate raw hash")
    for field in ("raw_characters", "sanitised_characters"):
        _positive(item[field], "candidate text length", allow_zero=True)
    _require(type(item["included"]) is bool, "candidate included flag")
    scores = item["rendered_scores"]
    _require(set(scores) == {"score", "dense_score", "dense_rank", "lexical_score", "lexical_rank"}, "score fields")
    _require(
        all(value is None or (type(value) in (int, float) and math.isfinite(value)) for value in scores.values()),
        "finite numeric scores",
    )
    _require(
        isinstance(item["matched_focus_ids"], list)
        and item["matched_focus_ids"] == sorted(set(item["matched_focus_ids"]))
        and set(item["matched_focus_ids"]) <= set(manifest["focus_ids"]),
        "matched focus identity",
    )
    if not item["included"]:
        _require(item["reason"] in {"no_safe_sentence_window", "total_character_budget"}, "candidate omission reason")
        _require(
            all(
                item[field] is None
                for field in (
                    "visible_start",
                    "visible_end",
                    "visible_text_sha256",
                    "context_start",
                    "context_end",
                    "omitted_prefix_characters",
                    "omitted_suffix_characters",
                )
            ),
            "omitted bytes cannot be visible",
        )
        _require(item["fragments"] == [] and item["matched_focus_ids"] == [], "omitted fragment fields")
        return previous_end
    start, end = item["visible_start"], item["visible_end"]
    _require(
        type(start) is int and type(end) is int and 0 <= start < end <= item["sanitised_characters"],
        "candidate span bounds",
    )
    _require(end - start <= 2200, "candidate per-original-chunk budget")
    _hash(item["visible_text_sha256"], "candidate visible hash")
    _require(type(item["context_start"]) is int and type(item["context_end"]) is int, "integer context spans")
    _require(
        previous_end < item["context_start"] < item["context_end"] <= manifest["context_characters"],
        "ordered context spans",
    )
    _require(item["context_end"] - item["context_start"] == end - start, "candidate context span length")
    complete = start == 0 and end == item["sanitised_characters"]
    _require(item["reason"] == ("complete" if complete else "focus_sentence_window"), "candidate selection reason")
    _require(
        type(item["omitted_prefix_characters"]) is int
        and type(item["omitted_suffix_characters"]) is int
        and item["omitted_prefix_characters"] == start
        and item["omitted_suffix_characters"] == item["sanitised_characters"] - end,
        "candidate omission counts",
    )
    _require(
        item["fragments"]
        == [
            {
                "sanitised_start": start,
                "sanitised_end": end,
                "context_start": item["context_start"],
                "context_end": item["context_end"],
                "visible_text_sha256": item["visible_text_sha256"],
                "boundary_method": "whole_indexed_chunk" if complete else "sentence_boundary_with_adjacent_context",
            }
        ],
        "one exact bound contiguous fragment",
    )
    return item["context_end"]


def _validate_candidate_targets(case, row):
    entries = row["assembly"]["chunks"]
    _require(len(row["targets"]) == len(case["targets"]), "candidate target count")
    for target, scored in zip(case["targets"], row["targets"], strict=True):
        _require(
            set(scored)
            == {
                "id",
                "focus_id",
                "witnesses",
                "retrieved_source_ranks",
                "retrieved_passage_ranks",
                "visible_passage_ranks",
            },
            "candidate target fields",
        )
        _require(scored["id"] == target["id"] and scored["focus_id"] == target["focus_id"], "candidate target identity")
        expected = [entry["retrieved_rank"] for entry in entries if entry["source_id"] in target["expected_source_ids"]]
        _require(
            [witness["retrieved_rank"] for witness in scored["witnesses"]] == expected,
            "complete ordered candidate witnesses",
        )
        for witness in scored["witnesses"]:
            _require(set(witness) == {"retrieved_rank", "terms"}, "candidate witness fields")
            rank = witness["retrieved_rank"]
            _require(type(rank) is int, "candidate witness rank")
            entry = entries[rank - 1]
            _require(len(witness["terms"]) == len(target["expected_terms"]), "candidate witness terms")
            for i, (term, evidence) in enumerate(zip(target["expected_terms"], witness["terms"], strict=True)):
                _require(set(evidence) == {"term_index", "raw_span", "visible_span"}, "candidate phrase fields")
                _require(type(evidence["term_index"]) is int and evidence["term_index"] == i, "candidate term order")
                _check_span(evidence["raw_span"], entry["raw_characters"], len(term))
                length = entry["visible_end"] - entry["visible_start"] if entry["included"] else 0
                _check_span(evidence["visible_span"], length, len(term))
        _require(
            all(scored[key] == value for key, value in _witness_scores(scored["witnesses"]).items()),
            "candidate witness arithmetic",
        )


def _validate_query_configuration(name, case, row, old):
    configuration = row["retrieval_configuration"]
    expected = old["retrieval_configuration"]
    _require(
        {key: value for key, value in configuration.items() if key != "query_plan"} == expected,
        "paired retrieval thresholds and budgets",
    )
    if name == "window_only":
        _require(configuration == expected, "window-only query contract")
        fields = (
            "source_id",
            "chunk_id",
            "raw_text_sha256",
            "raw_characters",
            "sanitised_text_sha256",
            "sanitised_characters",
        )
        _require(
            [[item[field] for field in fields] for item in row["assembly"]["chunks"]]
            == [[item[field] for field in fields] for item in old["assembly"]["chunks"]],
            "window-only retrieval must be identical",
        )
        return
    plan = configuration["query_plan"]
    _require(set(plan) == {"schema", "fusion", "rrf_k", "per_query_candidate_k", "queries"}, "public query plan fields")
    _require(plan["schema"] == FOCUS_QUERY_SCHEMA and plan["fusion"] == PLANNING_FUSION, "query plan method")
    _positive(plan["rrf_k"], "query RRF constant")
    _positive(plan["per_query_candidate_k"], "query candidate limit")
    _require(plan["per_query_candidate_k"] == configuration["candidate_k"], "query candidate budget")
    queries = [
        (None, row["query"]["sha256"]),
        *[(item["focus_id"], _sha(item["query"])) for item in build_focus_queries(case["form"]["concerns"])],
    ]
    _require(len(plan["queries"]) == len(queries), "query plan length")
    for item, (focus, digest) in zip(plan["queries"], queries, strict=True):
        _require(set(item) == {"focus_id", "query_sha256", "matched_chunks"}, "public query identity fields")
        _require(item["focus_id"] == focus and item["query_sha256"] == digest, "query focus binding")
        _positive(item["matched_chunks"], "matched candidate count", allow_zero=True)
        _require(item["matched_chunks"] <= plan["per_query_candidate_k"], "matched candidate budget")


def run_comparison(payload, service, *, data_paths=None, run_metadata=None, provenance_check=None):
    _require(
        callable(getattr(type(service), "retrieve_planning", None)), "comparison requires focused retrieval capability"
    )
    cases = validate_form_suite(payload)
    baseline = run_form_evaluation(
        payload, service, data_paths=data_paths, run_metadata=run_metadata, provenance_check=provenance_check
    )
    variants = {}
    for variant, active_service in (("window_only", _LegacyQueryService(service)), ("focused_window", service)):
        rows = []
        for case, old in zip(cases, baseline["rows"]):
            if provenance_check:
                provenance_check(f"{variant}:{case['id']}:before")
            analysis = run_analysis_pipeline(**case["form"], data_paths=data_paths, knowledge_service=active_service)
            knowledge = analysis["knowledge"]
            _require(knowledge["status"] in {"ready", "no_match", "out_of_scope"}, "candidate retrieval unavailable")
            if provenance_check:
                provenance_check(f"{variant}:{case['id']}:after", knowledge)
            assembly = analysis["rag_context_assembly"]
            _validate_rendered_assembly(assembly, knowledge["retrieved_chunks"])
            prompt = build_report_prompt(
                **case["form"],
                analysis=analysis,
                governance_context="Diagnostic draft; responsible human review required.",
            ).strip()
            context = assembly["context"]
            _require(prompt.count(context) == 1, "candidate assembly differs from actual prompt")
            _require(_sha(context) == assembly["manifest"]["context_sha256"], "candidate context identity")
            _require(knowledge["query_sha256"] == old["query"]["sha256"], "different base query")
            _require(
                canonical_sha256(knowledge["query_components"]) == old["query"]["components_sha256"],
                "different base query components",
            )
            profile = analysis["profile"]
            actual_profile = {
                "state": profile["state"],
                "locality": profile["locality"],
                "setting_type": profile["setting_type"],
                "scenario_id": profile["scenario_concept"]["id"],
                "timeframe_id": profile["timeframe_concept"]["id"],
                "focus_ids": [item["id"] for item in analysis["plan"]["focus_area_concepts"]],
            }
            _require(actual_profile == old["profile"], "different resolved application profile")
            _require(
                canonical_sha256(analysis["data_provenance"]) == old["data_provenance_sha256"],
                "different form data snapshot",
            )
            rows.append(
                {
                    "id": case["id"],
                    "form_sha256": old["form_sha256"],
                    "query": old["query"],
                    "profile": old["profile"],
                    "status": knowledge["status"],
                    "retrieval_configuration": knowledge["retrieval_configuration"],
                    "index_manifest_sha256": knowledge["index_manifest_sha256"],
                    "data_provenance_sha256": old["data_provenance_sha256"],
                    "initial_prompt": {
                        "sha256": _sha(prompt),
                        "characters": len(prompt),
                        "context_start": prompt.index(context),
                        "context_end": prompt.index(context) + len(context),
                    },
                    "assembly": assembly["manifest"],
                    "targets": [
                        _score_target(target, knowledge["retrieved_chunks"], assembly) for target in case["targets"]
                    ],
                }
            )
        variants[variant] = {
            "rows": rows,
            "summary": _candidate_summary(rows),
            "comparison": _comparison(baseline["rows"], rows),
        }
    negative = []
    for query in NEGATIVE_QUERIES:
        if provenance_check:
            provenance_check("negative:" + _sha(query) + ":before")
        result = service.retrieve_planning(
            query, focus_queries=build_focus_queries(["Emergency kits"]), jurisdiction="Australia"
        )
        if provenance_check:
            provenance_check("negative:" + _sha(query) + ":after")
        negative.append(
            {
                "query_sha256": _sha(query),
                "status": result["status"],
                "retrieved_count": len(result["retrieved_chunks"]),
            }
        )
    output = {
        "artifact_schema": SCHEMA,
        "baseline": baseline,
        "variants": variants,
        "negative_probes": negative,
        "report_model_called": False,
        "boundary": _BOUNDARY,
        "release_gate": {"active": False, "passed": None},
    }
    _bind_comparison_digest(output)
    validate_comparison(output, payload)
    return output


def _bind_comparison_digest(output):
    output["comparison_sha256"] = canonical_sha256(
        {key: value for key, value in output.items() if key != "comparison_sha256"}
    )


def _validate_candidate_row(name, case, old, row):
    _require(
        set(row)
        == {
            "id",
            "form_sha256",
            "query",
            "profile",
            "status",
            "retrieval_configuration",
            "index_manifest_sha256",
            "data_provenance_sha256",
            "initial_prompt",
            "assembly",
            "targets",
        },
        "candidate row fields (public metadata only)",
    )
    for key in ("id", "form_sha256", "query", "profile", "index_manifest_sha256", "data_provenance_sha256"):
        _require(row[key] == old[key], "paired input/provenance identity")
    manifest = row["assembly"]
    template = assemble_planning_context(
        {}, focus_concepts=PlannerAgent._resolve_focus_areas(case["form"]["concerns"])[0]
    )["manifest"]
    _require(set(manifest) == set(template), "candidate manifest fields")
    for field in (
        "schema",
        "strategy",
        "length_unit",
        "budget_scope",
        "max_characters",
        "max_chunk_characters",
        "selection_inputs_sha256",
        "focus_ids",
    ):
        _require(manifest[field] == template[field], "candidate selection contract")
    _require(manifest["schema"] == PLANNING_CONTEXT_SCHEMA, "candidate assembly schema")
    _positive(manifest["context_characters"], "candidate context length")
    _require(manifest["context_characters"] <= 8000, "candidate total budget")
    _hash(manifest["context_sha256"], "candidate context hash")
    entries = manifest["chunks"]
    _require(isinstance(entries, list), "candidate chunk list")
    _positive(manifest["retrieved_count"], "candidate retrieved count", allow_zero=True)
    _positive(manifest["included_count"], "candidate included count", allow_zero=True)
    _require(manifest["retrieved_count"] == len(entries), "candidate retrieval count")
    _require(row["status"] in {"ready", "no_match", "out_of_scope"}, "candidate retrieval status")
    _require((row["status"] == "ready") == bool(entries), "candidate status with evidence")
    previous_end = 0
    for rank, item in enumerate(entries, 1):
        previous_end = _validate_candidate_entry(item, rank, manifest, previous_end)
    _require(len({item["chunk_id"] for item in entries}) == len(entries), "unique candidate chunk identities")
    _require(manifest["included_count"] == sum(item["included"] for item in entries), "candidate visible count")
    configuration = row["retrieval_configuration"]
    _positive(configuration["top_k"], "final top_k")
    _positive(configuration["max_chunks_per_source"], "final source limit")
    _require(len(entries) <= configuration["top_k"], "final candidate limit")
    for source in {item["source_id"] for item in entries}:
        _require(
            sum(item["source_id"] == source for item in entries) <= configuration["max_chunks_per_source"],
            "final source diversity",
        )
    prompt = row["initial_prompt"]
    _require(set(prompt) == {"sha256", "characters", "context_start", "context_end"}, "initial prompt metadata")
    _hash(prompt["sha256"], "candidate prompt hash")
    for field in ("characters", "context_start", "context_end"):
        _positive(prompt[field], "candidate prompt integer offsets", allow_zero=field == "context_start")
    _require(0 <= prompt["context_start"] < prompt["context_end"] <= prompt["characters"], "initial prompt span")
    _require(prompt["context_end"] - prompt["context_start"] == manifest["context_characters"], "prompt context length")
    _validate_query_configuration(name, case, row, old)
    _validate_candidate_targets(case, row)


def _reject_text_fields(value):
    if isinstance(value, dict):
        forbidden = {
            "text",
            "context",
            "prompt",
            "source_text",
            "raw_text",
            "query_text",
            "extra_context",
            "api_key",
            "access_password",
            "excerpt",
            "messages",
            "user_message",
        }
        _require(not forbidden.intersection(value), "private text is not diagnostic metadata")
        for item in value.values():
            _reject_text_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_text_fields(item)


def _validate_comparison(output, payload, suite_bytes):
    _require(
        set(output)
        == {
            "artifact_schema",
            "baseline",
            "variants",
            "negative_probes",
            "report_model_called",
            "boundary",
            "release_gate",
            "comparison_sha256",
        },
        "comparison public fields",
    )
    _require(output["artifact_schema"] == SCHEMA, "comparison schema")
    _require(output["report_model_called"] is False and output["boundary"] == _BOUNDARY, "diagnostic model boundary")
    _require(output["release_gate"] == {"active": False, "passed": None}, "comparison is not a release gate")
    _reject_text_fields(output)
    _hash(output["comparison_sha256"], "comparison payload hash")
    _require(
        output["comparison_sha256"]
        == canonical_sha256({key: value for key, value in output.items() if key != "comparison_sha256"}),
        "comparison payload changed",
    )
    baseline = output["baseline"]
    validate_form_evaluation_artifact(baseline, payload, suite_bytes=suite_bytes)
    _require(set(output["variants"]) == {"window_only", "focused_window"}, "comparison variants")
    cases = validate_form_suite(payload)
    for name, variant in output["variants"].items():
        _require(set(variant) == {"rows", "summary", "comparison"}, "candidate variant fields")
        rows = variant["rows"]
        _require(len(rows) == len(cases), "candidate row count")
        for case, old, row in zip(cases, baseline["rows"], rows, strict=True):
            _validate_candidate_row(name, case, old, row)
        _require(variant["summary"] == _candidate_summary(rows), "candidate summary arithmetic")
        _require(variant["comparison"] == _comparison(baseline["rows"], rows), "paired comparison arithmetic")
    _require(
        output["negative_probes"]
        == [
            {"query_sha256": _sha(query), "status": "out_of_scope", "retrieved_count": 0} for query in NEGATIVE_QUERIES
        ],
        "focused query bypassed live safety refusal",
    )
    return output


def validate_comparison(output, payload, *, suite_bytes=None):
    """Verify public arithmetic, bindings and offsets, not semantic entailment.

    The payload hash detects byte-independent metadata changes. It is not a
    signature: source authenticity still depends on the separately verified run.
    """
    try:
        return _validate_comparison(output, payload, suite_bytes)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as error:
        raise ValueError("Invalid form RAG comparison structure.") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=PROJECT_ROOT / "data_australia/rag/form_evaluation_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; use a new path and preserve previous evidence.")
    suite_bytes = args.suite.read_bytes()
    payload = json.loads(suite_bytes)
    service = RagService()
    baseline = build_run_metadata(payload, args.suite, service)

    def check(label, result=None):
        current = build_run_metadata(payload, args.suite, service)
        require_stable_release_provenance(
            baseline, current, _STABILITY, label=label, artifact_name="Paired form diagnostic"
        )
        if result is not None:
            _require(
                result.get("index_manifest_sha256") == baseline["rag_index"]["manifest_sha256"],
                "changed retrieval index",
            )

    output = run_comparison(payload, service, run_metadata=baseline, provenance_check=check)
    check("completion")
    output["baseline"]["run"]["provenance_stability"] = {"checked": True, "stable": True, "drift_fields": []}
    output["baseline"]["run"]["completed_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _bind_comparison_digest(output)
    validate_comparison(output, payload, suite_bytes=suite_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({key: value["summary"] for key, value in output["variants"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
