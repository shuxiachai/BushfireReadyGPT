"""Opt-in, local-only two-stage A/B diagnostic. This is never a release gate."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluation_artifacts import (  # noqa: E402
    git_provenance,
    ollama_model_identity,
    rag_index_provenance,
    sha256_file,
)
from src.model_evidence import json_sha256  # noqa: E402

SCENARIO_SCHEMA = "body-evidence-ab-scenarios-v1"
PREPARED_SCHEMA = "body-evidence-ab-prepared-v1"
RESULT_SCHEMA = "body-evidence-ab-results-v1"
TARGET_SECTIONS = [7, 11, 12]
VARIANTS = ("baseline", "claim_pair_v1")
MAX_CALLS = 36


def validate_scenarios(payload):
    if not isinstance(payload, dict) or payload.get("schema") != SCENARIO_SCHEMA:
        raise ValueError("Unsupported scenario schema.")
    if payload.get("phase") not in {"seen_pilot", "sealed_holdout"}:
        raise ValueError("Invalid experiment phase.")
    if payload.get("candidate") != "claim_pair_v1" or payload.get("target_sections") != TARGET_SECTIONS:
        raise ValueError("Candidate and target sections must match the fixed experiment.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 6:
        raise ValueError("The experiment requires between one and six cases.")
    ids = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each case must be an object.")
        for field in ("id", "location", "audience", "scenario", "timeframe"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                raise ValueError(f"Case field {field} must be non-empty text.")
        if case["id"] in ids:
            raise ValueError("Duplicate case id.")
        ids.add(case["id"])
        if not isinstance(case.get("concerns"), list) or any(not isinstance(x, str) for x in case["concerns"]):
            raise ValueError("concerns must be a list of strings.")
        if not isinstance(case.get("extra_context", ""), str) or case.get("rag_enabled") is not True:
            raise ValueError("Each case requires text extra_context and rag_enabled=true.")
    return payload


def require_local_runtime():
    """Reject external endpoints before importing provider configuration."""
    endpoint = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    parsed = urlsplit(endpoint)
    if (
        os.environ.get("LLM_PROVIDER", "ollama").lower() != "ollama"
        or parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("This experiment accepts only an explicit local Ollama loopback endpoint.")
    from src import config
    from src.rag.settings import RagSettings

    settings = RagSettings.from_env()
    if config.LLM_PROVIDER != "ollama" or config.MODEL_ENDPOINT != endpoint:
        raise ValueError("Imported model settings differ from the checked local endpoint.")
    if config.MODEL_MAX_TOKENS != 2300:
        raise ValueError("The unchanged 2300-token production limit is required.")
    if not settings.enabled:
        raise ValueError("RAG must be enabled for the experiment.")
    if settings.embedding_provider != "fastembed" or not settings.embedding_local_files_only:
        raise ValueError("Prepare requires the cached, local-files-only CPU embedding profile.")
    return config, settings


def collect_provenance(scenario_path):
    from src.data_artifacts import build_data_provenance
    from src.data_paths import get_data_paths
    from src.report_generation_quality import quality_policy_metadata

    config, settings = require_local_runtime()
    code_paths = list((PROJECT_ROOT / "src").rglob("*.py")) + [
        Path(__file__).resolve(),
        PROJECT_ROOT / "scripts/body_evidence_experiment.py",
        PROJECT_ROOT / "scripts/evaluation_artifacts.py",
        PROJECT_ROOT / "pyproject.toml",
    ]
    code_paths += [p for p in (PROJECT_ROOT / "poetry.lock", PROJECT_ROOT / "requirements.txt") if p.is_file()]
    source_hashes = {p.relative_to(PROJECT_ROOT).as_posix(): sha256_file(p) for p in sorted(code_paths)}
    identity = ollama_model_identity(config.MODEL_ENDPOINT, config.model)
    index = rag_index_provenance(settings)
    if identity["digest_status"] != "resolved" or index["status"] != "verified":
        raise ValueError("Resolved local model digest and verified RAG index are required.")
    return {
        "scenario_path": str(Path(scenario_path).resolve()),
        "scenario_sha256": sha256_file(scenario_path),
        "git": git_provenance(PROJECT_ROOT),
        "source_files_sha256": source_hashes,
        "dataset": build_data_provenance(get_data_paths()),
        "rag_index": index,
        "rag_settings": json.loads(json.dumps(asdict(settings), default=str)),
        "model": {
            "provider": "ollama",
            "endpoint": config.MODEL_ENDPOINT,
            **identity,
            "max_tokens": config.MODEL_MAX_TOKENS,
            "temperature": config.MODEL_TEMPERATURE,
            "seed": config.MODEL_SEED,
            "timeout_seconds": config.MODEL_TIMEOUT_SECONDS,
            "sdk_max_retries": 0,
            "context_window_tokens": None,
            "usage": None,
        },
        "quality_policy": quality_policy_metadata(),
    }


def _now():
    return datetime.now(timezone.utc).isoformat()


def _inactive():
    return {"release_gate": {"active": False}, "production_enabled": False, "semantic_accuracy": None}


def _binding(case):
    return json_sha256({key: case[key] for key in ("scenario", "analysis", "rag_context_assembly")})


def prepare_bundle(payload, scenario_path, *, analyse=None, provenance=None):
    """Exactly one retrieval per case; freeze before independent rubric authoring."""
    validate_scenarios(payload)
    if analyse is None:
        from src.agents import run_analysis_pipeline

        analyse = run_analysis_pipeline
    provenance = provenance or collect_provenance
    before = provenance(scenario_path)
    prepared = {
        "schema": PREPARED_SCHEMA,
        **_inactive(),
        "phase": payload["phase"],
        "candidate": payload["candidate"],
        "target_sections": TARGET_SECTIONS,
        "created_at_utc": _now(),
        "provenance_start": before,
        "cases": [],
    }
    for scenario in payload["cases"]:
        analysis = analyse(
            scenario["location"],
            scenario["audience"],
            scenario["scenario"],
            scenario["concerns"],
            scenario["timeframe"],
            scenario.get("extra_context", ""),
        )
        from src.model_evidence import validate_recorded_assembly

        assembly = analysis.get("rag_context_assembly")
        validate_recorded_assembly(assembly, analysis)
        case = {
            "scenario": copy.deepcopy(scenario),
            "analysis": copy.deepcopy(analysis),
            "rag_context_assembly": copy.deepcopy(assembly),
            "analysis_sha256": json_sha256(analysis),
            "assembly_sha256": json_sha256(assembly),
        }
        case["binding_sha256"] = _binding(case)
        prepared["cases"].append(case)
    prepared["provenance_end"] = provenance(scenario_path)
    prepared["valid"] = before == prepared["provenance_end"]
    prepared["invalid_reason"] = None if prepared["valid"] else "provenance_changed_during_prepare"
    prepared["bundle_sha256"] = json_sha256(prepared)
    return prepared


def _validate_scenario_binding(bundle, payload):
    """Bind frozen inputs to the external scenario artifact, not only self-hashes."""
    provenance = bundle["provenance_end"]
    try:
        raw = Path(provenance["scenario_path"]).read_bytes()
    except (KeyError, TypeError, OSError) as error:
        raise ValueError("Actual scenario payload is unavailable.") from error
    if hashlib.sha256(raw).hexdigest() != provenance.get("scenario_sha256"):
        raise ValueError("Actual scenario payload hash differs from the prepared provenance.")
    actual = validate_scenarios(json.loads(raw))
    if any(actual.get(key) != payload[key] for key in ("schema", "phase", "candidate", "target_sections", "cases")):
        raise ValueError("Prepared inputs, order, or metadata differ from the actual scenario payload.")


def validate_prepared(bundle):
    from src.model_evidence import validate_recorded_assembly

    if not isinstance(bundle, dict) or bundle.get("schema") != PREPARED_SCHEMA:
        raise ValueError("Unsupported prepared bundle.")
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    if bundle.get("bundle_sha256") != json_sha256(unsigned):
        raise ValueError("Prepared bundle hash mismatch.")
    if bundle.get("valid") is not True or bundle["provenance_start"] != bundle["provenance_end"]:
        raise ValueError("Prepared bundle has invalid provenance.")
    if bundle.get("production_enabled") is not False or bundle.get("release_gate") != {"active": False}:
        raise ValueError("Experimental artifacts cannot enable production.")
    payload = validate_scenarios(
        {
            "schema": SCENARIO_SCHEMA,
            "phase": bundle["phase"],
            "candidate": bundle["candidate"],
            "target_sections": bundle["target_sections"],
            "cases": [case["scenario"] for case in bundle["cases"]],
        }
    )
    _validate_scenario_binding(bundle, payload)
    for case in bundle["cases"]:
        if (
            case.get("analysis_sha256") != json_sha256(case["analysis"])
            or case.get("assembly_sha256") != json_sha256(case["rag_context_assembly"])
            or case["rag_context_assembly"] != case["analysis"].get("rag_context_assembly")
            or case.get("binding_sha256") != _binding(case)
        ):
            raise ValueError("Frozen case binding mismatch.")
        validate_recorded_assembly(case["rag_context_assembly"], case["analysis"])
    return payload


class CallBudget:
    def __init__(self, maximum):
        if type(maximum) is not int or not 1 <= maximum <= MAX_CALLS:
            raise ValueError("Total call budget must be between 1 and 36.")
        self.maximum = maximum
        self.used = 0


class BudgetClient:
    """One shared budget across independent governed clients and repair loops."""

    def __init__(self, client, budget):
        self.client, self.budget = client, budget

    @property
    def last_request_capture(self):
        return self.client.last_request_capture

    def generate(self, prompt):
        if self.budget.used >= self.budget.maximum:
            raise RuntimeError("experiment_call_budget_exhausted")
        self.budget.used += 1
        return self.client.generate(prompt)


def new_local_client():
    from src.model_runtime import GovernedModelClient

    config, _ = require_local_runtime()
    return GovernedModelClient(
        completion_client=config.client.with_options(max_retries=0),
        provider="ollama",
        is_local=True,
        model_name=config.model,
        timeout_seconds=config.MODEL_TIMEOUT_SECONDS,
    )


def _summaries(rows):
    summaries = {}
    for variant in VARIANTS:
        selected = [row for row in rows if row["variant"] == variant]
        finals = [row["final"] for row in selected if row.get("final")]
        metrics = [final["body_claim_evidence"]["metrics"] for final in finals]
        required = sum(item["claims_requiring_citation"] for item in metrics)
        missing = sum(item["missing_citations"] for item in metrics)
        summaries[variant] = {
            "arms_denominator": len(selected),
            "total_arms": len(selected),
            "attempted_arms": sum(row.get("model_calls", 0) > 0 for row in selected),
            "completed_arms": len(finals),
            "evaluable_reports": len(finals),
            "valid_final_capture_arms": sum(row.get("capture_valid", False) for row in selected),
            "budget_exhausted_arms": sum(
                any(a.get("error_code") == "experiment_call_budget_exhausted" for a in row.get("attempts", []))
                for row in selected
            ),
            "failed_or_invalid_arms": sum(row["status"] != "completed" for row in selected),
            "governed_passing_arms": sum(row["governed_gate_passed"] for row in selected),
            "governed_failing_or_unavailable_arms": sum(not row["governed_gate_passed"] for row in selected),
            "governed_and_body_cited_arms": sum(
                row["governed_gate_passed"]
                and row.get("capture_valid", False)
                and row["final"]["body_claim_evidence"]["metrics"]["claims_requiring_citation"]
                > row["final"]["body_claim_evidence"]["metrics"]["missing_citations"]
                for row in selected
            ),
            "pair_completeness_rate": sum(f["claim_pairs"]["complete_pairs"] for f in finals) / (3 * len(selected)),
            "abstained_pairs": sum(f["claim_pairs"]["abstained_pairs"] for f in finals),
            "claims_requiring_citation": required if finals else None,
            "missing_citations": missing if finals else None,
            "citation_coverage_rate": (required - missing) / required if required else None,
            "lexical_match_claims": sum(item["lexical_match_claims"] for item in metrics) if finals else None,
            "no_lexical_match_claims": sum(item["no_lexical_match_claims"] for item in metrics) if finals else None,
            "unknown_support_claims": sum(item["unknown_support_claims"] for item in metrics) if finals else None,
            "semantic_accuracy": None,
            "content_metrics_scope": "available_final_reports_only; all failed arms remain in arms_denominator",
        }
    return summaries


def run_prepared(bundle, *, max_calls=MAX_CALLS, client_factory=None, provenance=None, arm_runner=None):
    from scripts.body_evidence_experiment import run_arm

    validate_prepared(bundle)
    provenance = provenance or collect_provenance
    client_factory = client_factory or new_local_client
    arm_runner = arm_runner or run_arm
    budget = CallBudget(max_calls)
    result = {
        "schema": RESULT_SCHEMA,
        **_inactive(),
        "prepared_bundle_sha256": bundle["bundle_sha256"],
        "phase": bundle["phase"],
        "candidate": bundle["candidate"],
        "started_at_utc": _now(),
        "valid": True,
        "invalid_reasons": [],
        "rows": [],
        "max_calls": max_calls,
        "capture_limitations": "SDK submission does not prove provider receipt, absence of server truncation, or attention.",
        "call_count_boundary": "Attempted governed client invocations, not independently attested provider receipt.",
        "drift_check_scope": "Start, after each arm, and end snapshots; changes restored between checks are not excluded.",
        "rubric_review_status": "not_scored_here",
        "human_semantic_review": "not_performed",
    }
    expected = bundle["provenance_end"]
    scenario_path = expected["scenario_path"]

    def check(label):
        try:
            current = provenance(scenario_path)
            stable = current == expected
        except Exception as error:
            current, stable = {"error_code": type(error).__name__}, False
        result.setdefault("provenance_checks", []).append({"at": label, "stable": stable, "provenance": current})
        if not stable:
            result["valid"] = False
            result["invalid_reasons"].append("provenance_drift_at_" + label)

    check("start")
    for index, case in enumerate(bundle["cases"]):
        order = VARIANTS if index % 2 == 0 else tuple(reversed(VARIANTS))
        for variant in order:
            if result["valid"]:
                try:
                    row = arm_runner(
                        copy.deepcopy(case["scenario"]),
                        copy.deepcopy(case["analysis"]),
                        variant,
                        BudgetClient(client_factory(), budget),
                    )
                except Exception as error:
                    row = {
                        "case_id": case["scenario"]["id"],
                        "variant": variant,
                        "status": "failed",
                        "error_code": type(error).__name__,
                        "governed_gate_passed": False,
                        "final": None,
                        "initial": None,
                        "attempts": [],
                        "model_calls": 0,
                        "analysis_sha256": case["analysis_sha256"],
                        "assembly_sha256": case["assembly_sha256"],
                    }
            else:
                row = {
                    "case_id": case["scenario"]["id"],
                    "variant": variant,
                    "status": "invalid",
                    "error_code": "provenance_drift",
                    "governed_gate_passed": False,
                    "final": None,
                    "analysis_sha256": case["analysis_sha256"],
                    "assembly_sha256": case["assembly_sha256"],
                }
            result["rows"].append(row)
            if row.get("analysis_sha256") != case["analysis_sha256"]:
                result["valid"] = False
                result["invalid_reasons"].append("arm_analysis_binding_mismatch")
            check(f"after_{index}_{variant}")
    check("end")
    result.update(completed_at_utc=_now(), actual_model_calls=budget.used, summaries=_summaries(result["rows"]))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--prepare-only", action="store_true", help="Retrieve once; freeze without LLM generation.")
    action.add_argument("--prepared", type=Path, help="Use an independently reviewable frozen bundle.")
    parser.add_argument("--scenarios", type=Path)
    parser.add_argument("--output", type=Path, help="Required new private JSON path; never overwritten.")
    parser.add_argument("--run-model", action="store_true", help="Explicitly allow bounded local model generation.")
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS)
    args = parser.parse_args(argv)
    if not args.prepare_only and args.prepared is None:
        parser.print_help()
        return 0
    if args.output is None:
        parser.error("--output is required and must be a new path")
    if args.prepare_only and (args.scenarios is None or args.run_model):
        parser.error("--prepare-only requires --scenarios and excludes --run-model")
    if args.prepared and (not args.run_model or args.scenarios is not None):
        parser.error("--prepared requires --run-model and excludes --scenarios")
    if not 1 <= args.max_calls <= MAX_CALLS:
        parser.error("--max-calls must be between 1 and 36")
    require_local_runtime()
    # Exclusive reservation precedes retrieval/generation; pre-existing paths are never modified.
    with args.output.open("x", encoding="utf-8") as handle:
        try:
            if args.prepare_only:
                payload = json.loads(args.scenarios.read_text(encoding="utf-8"))
                result = prepare_bundle(payload, args.scenarios)
            else:
                bundle = json.loads(args.prepared.read_text(encoding="utf-8"))
                result = run_prepared(bundle, max_calls=args.max_calls)
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        except Exception as error:
            json.dump(
                {"schema": RESULT_SCHEMA, **_inactive(), "valid": False, "error_code": type(error).__name__}, handle
            )
            print(f"Experiment failed: {type(error).__name__}. Diagnostic artifact: {args.output}", file=sys.stderr)
            return 2
    print(f"Wrote {result['schema']}: {args.output}; valid={result['valid']}; production_enabled=false")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
