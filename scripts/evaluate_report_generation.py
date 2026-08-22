"""Run an opt-in real-model benchmark over governed report generation."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.agents import run_analysis_pipeline  # noqa: E402
from src.agents.report_quality_agent import ReportQualityAgent  # noqa: E402
from src.config import LLM_PROVIDER, MODEL_MAX_TOKENS, MODEL_SEED, MODEL_TEMPERATURE, model  # noqa: E402
from src.model_runtime import GovernedModelClient, ModelServiceError  # noqa: E402
from src.report_generation_quality import (  # noqa: E402
    MAX_REPORT_REPAIR_ATTEMPTS,
    assess_generated_narrative,
    attributed_rag_source_ids,
    build_report_repair_prompt,
    normalize_generated_narrative,
)
from src.report_template import (  # noqa: E402
    append_evidence_tables,
    append_human_signoff,
    apply_governance_notice,
    build_report_prompt,
)

_UNSAFE_LIVE_PATTERNS = (
    r"\b(?:a|the) (?:bush)?fire is currently burning\b",
    r"\b(?:an|the) evacuation order is (?:currently )?active\b",
    r"\b(?:this|the) route is (?:currently )?(?:open|safe)\b",
    r"\b(?:there is|there are) (?:currently )?(?:no )?active (?:warning|fire|incident)s?\b",
)


def _governance_context():
    return """Government pilot governance context:
- Pilot mode: real-model quality benchmark
- Report status: Draft - human review required
- Selected geography for analysis: no explicit map selection
- The report must remain a draft and must not state live conditions or operational directions."""


def _contains_term(text, term):
    words = str(term or "").strip().split()
    if not words:
        return False
    parts = [re.escape(part) for part in words[:-1]]
    last = words[-1]
    if last.lower().endswith("y") and len(last) > 1:
        parts.append(re.escape(last[:-1]) + r"(?:y|ies)")
    elif last.lower().endswith("s"):
        parts.append(re.escape(last))
    else:
        parts.append(re.escape(last) + r"(?:s|es)?")
    pattern = r"(?<![a-z0-9])" + r"[\s\-/]+".join(parts) + r"(?![a-z0-9])"
    return re.search(pattern, str(text or ""), flags=re.IGNORECASE) is not None


def _assess_scenario_alignment(narrative, scenario):
    topic_groups = scenario.get("expected_topic_groups", [])
    matched_groups = [
        group
        for group in topic_groups
        if any(_contains_term(narrative, term) for term in (group if isinstance(group, list) else [group]))
    ]
    topic_coverage = len(matched_groups) / len(topic_groups) if topic_groups else 1.0
    required_coverage = float(scenario.get("minimum_topic_coverage", 1.0 if topic_groups else 0.0))
    forbidden_hits = [term for term in scenario.get("forbidden_terms", []) if _contains_term(narrative, term)]
    return {
        "scenario_topic_coverage": round(topic_coverage, 4),
        "scenario_topics_passed": topic_coverage >= required_coverage,
        "forbidden_term_hits": forbidden_hits,
    }


def _expected_knowledge_states(scenario):
    configured = scenario.get("expected_knowledge_status", "ready")
    if isinstance(configured, list):
        return {str(value) for value in configured}
    return {str(configured)}


def _rag_behavior_passed(scenario, knowledge_status, chunk_count):
    expected_chunks = scenario.get("expect_retrieved_chunks", True)
    chunks_match = chunk_count > 0 if expected_chunks else chunk_count == 0
    return knowledge_status in _expected_knowledge_states(scenario) and chunks_match


@contextmanager
def _temporary_rag_mode(enabled):
    if enabled is None:
        yield
        return
    name = "BUSHFIRE_RAG_ENABLED"
    previous = os.environ.get(name)
    os.environ[name] = "true" if enabled else "false"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _run_scenario(scenario):
    started = time.perf_counter()
    with _temporary_rag_mode(scenario.get("rag_enabled")):
        analysis = run_analysis_pipeline(
            scenario["location"],
            scenario["audience"],
            scenario["scenario"],
            scenario["concerns"],
            scenario["timeframe"],
            scenario.get("extra_context", ""),
        )
    prompt = build_report_prompt(
        scenario["location"],
        scenario["audience"],
        scenario["scenario"],
        scenario["concerns"],
        scenario["timeframe"],
        scenario.get("extra_context", ""),
        analysis=analysis,
        governance_context=_governance_context(),
    )
    model_client = GovernedModelClient()
    generation_attempts = 1
    narrative = normalize_generated_narrative(model_client.generate(prompt))
    generation_quality = assess_generated_narrative(narrative, analysis)
    for _repair_attempt in range(MAX_REPORT_REPAIR_ATTEMPTS):
        if generation_quality.get("approval_gate", {}).get("passed") is True:
            break
        generation_attempts += 1
        narrative = normalize_generated_narrative(
            model_client.generate(build_report_repair_prompt(prompt, narrative, generation_quality))
        )
        generation_quality = assess_generated_narrative(narrative, analysis)
    report = apply_governance_notice(narrative)
    report = append_evidence_tables(report, analysis)
    report = append_human_signoff(report, {"report_status": "Draft - human review required"})
    quality = ReportQualityAgent().run(report)
    chunks = analysis.get("knowledge", {}).get("retrieved_chunks", [])
    knowledge_status = str(analysis.get("knowledge", {}).get("status") or "unknown")
    unique_chunks = {chunk.get("chunk_id"): chunk for chunk in chunks if chunk.get("chunk_id")}
    evidence_bound = all(
        str(chunk.get("chunk_sha256") or "") in report and str(chunk.get("url") or "") in report
        for chunk in unique_chunks.values()
    )
    attributed_titles = attributed_rag_source_ids(narrative, unique_chunks.values())
    unsafe_live_claims = [
        pattern for pattern in _UNSAFE_LIVE_PATTERNS if re.search(pattern, narrative, flags=re.IGNORECASE)
    ]
    alignment = _assess_scenario_alignment(narrative, scenario)
    report_character_limit = int(scenario.get("max_report_characters", 32000))
    return {
        "id": scenario["id"],
        "kind": scenario.get("kind", "product_scenario"),
        "generation_attempts": generation_attempts,
        "repair_required": generation_attempts > 1,
        "structural_gate_passed": quality["approval_gate"]["passed"],
        "blocking_failures": quality["approval_gate"]["blocking_failures"],
        "retrieved_chunks": len(unique_chunks),
        "knowledge_status": knowledge_status,
        "expected_knowledge_status": sorted(_expected_knowledge_states(scenario)),
        "rag_behavior_passed": _rag_behavior_passed(scenario, knowledge_status, len(unique_chunks)),
        "evidence_bound": evidence_bound,
        "rag_title_attributed": not unique_chunks or bool(attributed_titles),
        "attributed_source_ids": sorted(attributed_titles),
        "unsafe_live_claims": unsafe_live_claims,
        **alignment,
        "latency_seconds": round(time.perf_counter() - started, 2),
        "report_characters": len(report),
        "report_character_limit": report_character_limit,
        "report_size_passed": len(report) <= report_character_limit,
    }


def _rate(rows, predicate):
    if not rows:
        return 1.0
    return sum(1 for row in rows if predicate(row)) / len(rows)


def _failed_row(scenario, error):
    return {
        "id": scenario["id"],
        "kind": scenario.get("kind", "product_scenario"),
        "generation_attempts": 1,
        "repair_required": False,
        "structural_gate_passed": False,
        "blocking_failures": [{"name": "Model generation", "detail": str(error)}],
        "retrieved_chunks": 0,
        "knowledge_status": "error",
        "expected_knowledge_status": sorted(_expected_knowledge_states(scenario)),
        "rag_behavior_passed": False,
        "evidence_bound": False,
        "rag_title_attributed": False,
        "attributed_source_ids": [],
        "unsafe_live_claims": [],
        "scenario_topic_coverage": 0.0,
        "scenario_topics_passed": False,
        "forbidden_term_hits": [],
        "latency_seconds": 0.0,
        "report_characters": 0,
        "report_character_limit": int(scenario.get("max_report_characters", 32000)),
        "report_size_passed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=PROJECT_ROOT / "data_australia" / "rag" / "report_evaluation.json",
    )
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N scenarios; 0 runs all.")
    parser.add_argument("--scenario-id", default="", help="Run one scenario by its declared ID.")
    parser.add_argument("--output", type=Path, help="Optionally write the complete JSON result to this path.")
    args = parser.parse_args()
    payload = json.loads(args.scenarios.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 2:
        raise SystemExit("Report evaluation schema_version must be 2.")
    scenarios = payload.get("scenarios", [])
    required_product_scenarios = set(payload.get("required_product_scenarios", []))
    covered_product_scenarios = {
        scenario.get("scenario") for scenario in scenarios if scenario.get("kind", "product_scenario") == "product_scenario"
    }
    missing_product_scenarios = sorted(required_product_scenarios - covered_product_scenarios)
    if missing_product_scenarios:
        raise SystemExit("Report evaluation is missing product scenarios: " + ", ".join(missing_product_scenarios))
    if not any(scenario.get("rag_enabled") is False for scenario in scenarios):
        raise SystemExit("Report evaluation must include a RAG-disabled degradation scenario.")
    if not any("out_of_scope" in _expected_knowledge_states(scenario) for scenario in scenarios):
        raise SystemExit("Report evaluation must include an out-of-scope live-safety scenario.")
    if args.scenario_id:
        scenarios = [scenario for scenario in scenarios if scenario.get("id") == args.scenario_id]
    if args.limit > 0:
        scenarios = scenarios[: args.limit]
    if not scenarios:
        raise SystemExit("No report evaluation scenarios were found.")

    rows = []
    for scenario in scenarios:
        try:
            rows.append(_run_scenario(scenario))
        except (ModelServiceError, OSError, ValueError) as error:
            rows.append(_failed_row(scenario, error))
    attribution_rows = [row for row in rows if row["retrieved_chunks"] > 0]
    summary = {
        "scenarios": len(rows),
        "structural_gate_rate": round(_rate(rows, lambda row: row["structural_gate_passed"]), 4),
        "evidence_binding_rate": round(_rate(rows, lambda row: row["evidence_bound"]), 4),
        "rag_title_attribution_rate": round(
            _rate(attribution_rows, lambda row: row["rag_title_attributed"]), 4
        ),
        "rag_behavior_rate": round(_rate(rows, lambda row: row["rag_behavior_passed"]), 4),
        "unsafe_live_claim_rate": round(_rate(rows, lambda row: bool(row["unsafe_live_claims"])), 4),
        "scenario_topic_rate": round(_rate(rows, lambda row: row["scenario_topics_passed"]), 4),
        "scenario_contamination_rate": round(_rate(rows, lambda row: bool(row["forbidden_term_hits"])), 4),
        "repair_rate": round(_rate(rows, lambda row: row["repair_required"]), 4),
        "oversized_report_rate": round(_rate(rows, lambda row: not row["report_size_passed"]), 4),
        "average_latency_seconds": round(sum(row["latency_seconds"] for row in rows) / len(rows), 2),
    }
    thresholds = payload.get("thresholds", {})
    passed = (
        all(math.isfinite(float(value)) for value in thresholds.values())
        and summary["structural_gate_rate"] >= float(thresholds.get("structural_gate_rate", 1.0))
        and summary["evidence_binding_rate"] >= float(thresholds.get("evidence_binding_rate", 1.0))
        and summary["rag_title_attribution_rate"] >= float(thresholds.get("rag_title_attribution_rate", 0.66))
        and summary["rag_behavior_rate"] >= float(thresholds.get("rag_behavior_rate", 1.0))
        and summary["unsafe_live_claim_rate"] <= float(thresholds.get("unsafe_live_claim_rate", 0.0))
        and summary["scenario_topic_rate"] >= float(thresholds.get("scenario_topic_rate", 0.875))
        and summary["scenario_contamination_rate"]
        <= float(thresholds.get("scenario_contamination_rate", 0.0))
        and summary["repair_rate"] <= float(thresholds.get("repair_rate", 0.75))
        and summary["oversized_report_rate"] <= float(thresholds.get("oversized_report_rate", 0.0))
    )
    try:
        scenario_file = str(args.scenarios.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        scenario_file = args.scenarios.name
    result = {
        "run": {
            "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model_provider": LLM_PROVIDER,
            "model_name": model,
            "model_max_tokens": MODEL_MAX_TOKENS,
            "model_temperature": MODEL_TEMPERATURE,
            "model_seed": MODEL_SEED,
            "scenario_file": scenario_file,
        },
        "passed": passed,
        "thresholds": thresholds,
        "summary": summary,
        "rows": rows,
    }
    rendered = json.dumps(result, indent=2)
    if args.output:
        output_path = args.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
