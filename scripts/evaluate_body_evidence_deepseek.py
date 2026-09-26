"""Explicit, finite DeepSeek comparison against the unchanged two-case seen pilot.

No retrieval, deployment, holdout evaluation, or automatic production activation.
The journal is a durable one-run claim for these exact prepared-file bytes; using
a different output filename cannot restart their external-call allowance.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_body_evidence_ab import (  # noqa: E402
    PREPARED_SCHEMA,
    VARIANTS,
    BudgetClient,
    CallBudget,
    _summaries,
    validate_prepared,
)
from scripts.evaluation_artifacts import git_provenance, sha256_file  # noqa: E402

RESULT_SCHEMA = "body-evidence-deepseek-comparison-v1"
JOURNAL_SCHEMA = "body-evidence-deepseek-calls-v1"
PILOT_PATH = Path("data_australia/rag/body_evidence_pilot_v1.json")
MAX_CALLS = 12
_ENDPOINTS = {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
_JOURNAL_FIELDS = {
    "schema",
    "event",
    "at_utc",
    "sequence",
    "case_index",
    "variant",
    "attempt_number",
    "outcome",
    "max_calls",
    "prepared_file_sha256",
    "model",
}


class ExperimentBlocked(ValueError):
    """Only fixed reason codes may cross the CLI error-reporting boundary."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _inactive():
    return {"production_enabled": False, "release_gate": {"active": False}, "semantic_accuracy": None}


def _settings(model_arg=None):
    if os.environ.get("LLM_PROVIDER", "").lower() != "deepseek":
        raise ExperimentBlocked("explicit_deepseek_provider_required")
    if os.environ.get("BUSHFIRE_ALLOW_EXTERNAL_MODEL", "").strip().lower() != "true":
        raise ExperimentBlocked("external_model_acknowledgement_required")
    endpoint = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    endpoint = endpoint[:-1] if endpoint.endswith("/") else endpoint
    if endpoint not in _ENDPOINTS:
        raise ExperimentBlocked("endpoint_not_allowlisted")
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        raise ExperimentBlocked("deepseek_credential_missing")
    selected = model_arg if model_arg is not None else os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash"
    if not isinstance(selected, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", selected):
        raise ExperimentBlocked("invalid_model_name")
    try:
        maximum = int(os.environ.get("BUSHFIRE_MODEL_MAX_TOKENS", "2300"))
        temperature = float(os.environ.get("BUSHFIRE_MODEL_TEMPERATURE", "0.2"))
        timeout = float(os.environ.get("BUSHFIRE_MODEL_TIMEOUT_SECONDS", "180"))
    except ValueError as error:
        raise ExperimentBlocked("invalid_model_configuration") from error
    if (
        maximum != 2300
        or not math.isfinite(temperature)
        or temperature < 0
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ExperimentBlocked("invalid_model_configuration")
    return {
        "provider": "deepseek",
        "endpoint": endpoint,
        "model": selected,
        "model_selection_source": "cli"
        if model_arg is not None
        else "environment"
        if os.environ.get("DEEPSEEK_MODEL")
        else "repository_default",
        "max_tokens": maximum,
        "temperature": temperature,
        "timeout_seconds": timeout,
        "sdk_max_retries": 0,
        "follow_redirects": False,
        "trust_env": False,
        "verify_tls": True,
        "top_p_submitted": 0.8,
        "thinking": "disabled",
        "seed_sent": False,
        "immutable_model_digest": None,
        "usage": None,
        "top_p_documentation_note": "Provider documentation describes effective top_p=1.0 in non-thinking mode; this is not a server attestation.",
    }


def admit_environment(*, run_model, allow_external_deepseek, model_arg=None, dotenv_loader=None):
    if not run_model or not allow_external_deepseek:
        raise ExperimentBlocked("explicit_external_run_flags_required")
    if dotenv_loader is None:
        from dotenv import load_dotenv

        dotenv_loader = load_dotenv
    dotenv_loader(PROJECT_ROOT / ".env", override=False)
    return _settings(model_arg)


def _source_hashes(root):
    paths = list((root / "src").rglob("*.py"))
    paths += [root / "scripts/body_evidence_experiment.py", root / "scripts/evaluate_body_evidence_ab.py"]
    return {path.relative_to(root).as_posix(): sha256_file(path) for path in sorted(paths)}


def load_seen_pilot(path, expected_sha256, *, root=PROJECT_ROOT):
    """Check scope before any legacy validator can read a scenario path."""
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ExperimentBlocked("expected_prepared_hash_required")
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256.lower():
        raise ExperimentBlocked("prepared_file_hash_mismatch")
    bundle = json.loads(raw)
    if (
        not isinstance(bundle, dict)
        or bundle.get("schema") != PREPARED_SCHEMA
        or bundle.get("phase") != "seen_pilot"
        or len(bundle.get("cases", [])) != 2
    ):
        raise ExperimentBlocked("only_two_case_seen_pilot_allowed")
    origin = bundle.get("provenance_end") or {}
    if Path(str(origin.get("scenario_path", ""))).resolve() != (root / PILOT_PATH).resolve():
        raise ExperimentBlocked("fixed_pilot_path_required")
    validate_prepared(bundle)
    pilot = json.loads((root / PILOT_PATH).read_bytes())
    if [case["scenario"] for case in bundle["cases"]] != pilot["cases"]:
        raise ExperimentBlocked("fixed_pilot_cases_mismatch")
    current = _source_hashes(root)
    recorded = origin.get("source_files_sha256") or {}
    old_keys = {key for key in recorded if key.startswith("src/")} | {
        "scripts/body_evidence_experiment.py",
        "scripts/evaluate_body_evidence_ab.py",
    }
    if set(current) != old_keys or any(recorded.get(key) != value for key, value in current.items()):
        raise ExperimentBlocked("historical_source_binding_mismatch")
    return bundle


def dependency_identity(root):
    return {
        "python": sys.version,
        "openai": importlib.metadata.version("openai"),
        "httpx": importlib.metadata.version("httpx"),
        "definition_files_sha256": {
            name: sha256_file(root / name)
            for name in ("pyproject.toml", "poetry.lock", "requirements.txt")
            if (root / name).is_file()
        },
    }


def execution_provenance(path, expected_sha256, settings, *, model_arg=None, root=PROJECT_ROOT):
    bundle = load_seen_pilot(path, expected_sha256, root=root)
    current_settings = _settings(model_arg)
    if current_settings != settings:
        raise ExperimentBlocked("execution_configuration_drift")
    from src.report_generation_quality import quality_policy_metadata

    policy = quality_policy_metadata()
    if policy != bundle["provenance_end"]["quality_policy"]:
        raise ExperimentBlocked("quality_policy_drift")
    return {
        "git": git_provenance(root),
        "dependencies": dependency_identity(root),
        "runner_sha256": sha256_file(Path(__file__)),
        "source_files_sha256": _source_hashes(root),
        "execution_configuration": current_settings,
        "prepared_file_sha256": expected_sha256.lower(),
        "quality_policy": policy,
        "frozen_dataset_and_index": "Retained as historical input origin; no retrieval or local-model probe is performed.",
    }


def build_client(settings, *, sdk_factory=None, http_factory=None, runtime_factory=None, config=None):
    """Independent TLS client; never reuse the production SDK's retry or proxy defaults."""
    if config is None:
        from src import config
    if (
        config.LLM_PROVIDER != "deepseek"
        or config.MODEL_MAX_TOKENS != 2300
        or config.MODEL_TEMPERATURE != settings["temperature"]
        or config.MODEL_TIMEOUT_SECONDS != settings["timeout_seconds"]
        or str(config.MODEL_ENDPOINT).rstrip("/") != settings["endpoint"]
    ):
        raise ExperimentBlocked("effective_runtime_configuration_mismatch")
    if sdk_factory is None:
        from openai import OpenAI

        sdk_factory = OpenAI
    if http_factory is None:
        import httpx

        http_factory = httpx.Client
    if runtime_factory is None:
        from src.model_runtime import GovernedModelClient

        runtime_factory = GovernedModelClient
    transport = http_factory(verify=True, follow_redirects=False, trust_env=False)
    sdk = sdk_factory(
        base_url=settings["endpoint"],
        api_key=os.environ["DEEPSEEK_API_KEY"],
        max_retries=0,
        timeout=settings["timeout_seconds"],
        http_client=transport,
    )
    runtime = runtime_factory(
        completion_client=sdk,
        model_name=settings["model"],
        provider="deepseek",
        is_local=False,
        timeout_seconds=settings["timeout_seconds"],
    )
    return runtime, sdk


class CallJournal:
    def __init__(self, handle):
        self.handle = handle
        self.entries = []

    def append(self, **entry):
        if set(entry) - _JOURNAL_FIELDS:
            raise ExperimentBlocked("journal_field_not_allowlisted")
        entry = {"schema": JOURNAL_SCHEMA, "at_utc": _now(), **entry}
        self.handle.write(json.dumps(entry, sort_keys=True) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.entries.append(entry)


def fatal_reason(error):
    """Classify types/causes only; never copy provider errors, URLs, or request text."""
    from src.model_response import ModelResponseError

    if isinstance(error, ModelResponseError):
        return None if error.retryable else "protocol_rejected"
    from openai import APIConnectionError, APITimeoutError, AuthenticationError, PermissionDeniedError, RateLimitError

    current = error
    for _ in range(8):
        if isinstance(current, (AuthenticationError, PermissionDeniedError)):
            return "authentication_or_permission"
        if isinstance(current, RateLimitError):
            return "quota_or_rate_limit"
        if isinstance(current, (APITimeoutError, TimeoutError)):
            return "timeout"
        if isinstance(current, (APIConnectionError, ConnectionError)):
            return "transport"
        current = getattr(current, "__cause__", None)
        if current is None:
            break
    return "service_or_deadline_failure"


class FatalClient:
    def __init__(self, client, budget, journal, state, case_index, variant, check):
        self.client = BudgetClient(client, budget)
        self.budget, self.journal, self.state = budget, journal, state
        self.case_index, self.variant, self.check = case_index, variant, check
        self.attempt = 0

    @property
    def last_request_capture(self):
        return self.client.last_request_capture

    def generate(self, prompt):
        if self.state.get("fatal") or not self.check("before_call"):
            raise ExperimentBlocked("batch_stopped")
        self.attempt += 1
        if self.attempt > 3 or self.budget.used >= self.budget.maximum:
            self.state["fatal"] = "call_budget_exhausted"
            raise ExperimentBlocked("call_budget_exhausted")
        entry = {
            "sequence": self.budget.used + 1,
            "case_index": self.case_index,
            "variant": self.variant,
            "attempt_number": self.attempt,
        }
        try:
            self.journal.append(event="before_call", **entry)
        except Exception:
            self.state["fatal"] = "journal_write_failed"
            raise
        try:
            response = self.client.generate(prompt)
        except Exception as error:
            reason = fatal_reason(error)
            if reason:
                self.state["fatal"] = reason
            try:
                self.journal.append(event="after_call", outcome=reason or "retryable_protocol_rejection", **entry)
            except Exception:
                self.state["fatal"] = "journal_write_failed"
                raise
            raise
        try:
            self.journal.append(event="after_call", outcome="client_admitted", **entry)
        except Exception:
            self.state["fatal"] = "journal_write_failed"
            raise
        return response


def _not_run(case, variant, reason):
    return {
        "case_id": case["scenario"]["id"],
        "variant": variant,
        "status": "not_run",
        "error_code": reason,
        "analysis_sha256": case["analysis_sha256"],
        "assembly_sha256": case["assembly_sha256"],
        "initial": None,
        "final": None,
        "attempts": [],
        "model_calls": 0,
        "governed_gate_passed": False,
    }


def run_comparison(bundle, settings, journal, *, max_calls=MAX_CALLS, provenance, client_factory=None, arm_runner=None):
    from scripts.body_evidence_experiment import run_arm

    if type(max_calls) is not int or not 1 <= max_calls <= MAX_CALLS:
        raise ExperimentBlocked("invalid_call_budget")
    arm_runner = arm_runner or run_arm
    client_factory = client_factory or (lambda: build_client(settings))
    budget, state = CallBudget(max_calls), {"fatal": None}
    result = {
        "schema": RESULT_SCHEMA,
        **_inactive(),
        "started_at_utc": _now(),
        "phase": "seen_pilot",
        "candidate": bundle["candidate"],
        "rows": [],
        "max_calls": max_calls,
        "historical_input_origin": copy.deepcopy(bundle),
        "execution_configuration": copy.deepcopy(settings),
        "execution_provenance_checks": [],
        "valid": True,
        "call_count_boundary": "Attempted governed-client invocations, including ambiguous timeout outcomes; not provider receipts.",
        "capture_limitations": "SDK capture does not attest model attention, server truncation, or immutable remote weights.",
        "semantic_review": "not_performed",
    }
    baseline = None

    def check(label):
        nonlocal baseline
        try:
            current = provenance()
            if baseline is None:
                baseline = current
            stable = current == baseline
        except Exception:
            current, stable = {"error_code": "provenance_validation_failed"}, False
        result["execution_provenance_checks"].append({"at": label, "stable": stable, "provenance": current})
        if not stable:
            result["valid"] = False
            state["fatal"] = "provenance_drift"
        return stable

    check("start")
    for index, case in enumerate(bundle["cases"]):
        order = VARIANTS if index % 2 == 0 else tuple(reversed(VARIANTS))
        for variant in order:
            if budget.used >= max_calls and not state["fatal"]:
                state["fatal"] = "call_budget_exhausted"
            row = _not_run(case, variant, state["fatal"])
            if not state["fatal"]:
                closeable = None
                try:
                    client, closeable = client_factory()
                    guarded = FatalClient(client, budget, journal, state, index, variant, check)
                    row = arm_runner(copy.deepcopy(case["scenario"]), copy.deepcopy(case["analysis"]), variant, guarded)
                except Exception as error:
                    state["fatal"] = fatal_reason(error) or "protocol_rejected"
                    row.update(status="failed", error_code=state["fatal"])
                finally:
                    if closeable is not None and not state["fatal"]:
                        try:
                            closeable.close()
                        except Exception:
                            state["fatal"] = "client_cleanup_failed"
                if (
                    row["analysis_sha256"] != case["analysis_sha256"]
                    or row["assembly_sha256"] != case["assembly_sha256"]
                ):
                    state["fatal"] = "frozen_binding_drift"
                    result["valid"] = False
            result["rows"].append(row)
            check(f"after_{index}_{variant}")
    check("end")
    result.update(
        completed_at_utc=_now(),
        fatal_stop_reason=state["fatal"],
        attempted_calls=budget.used,
        not_run_arms=sum(row["status"] == "not_run" for row in result["rows"]),
        summaries=_summaries(result["rows"]),
        journal=copy.deepcopy(journal.entries),
    )
    if state["fatal"]:
        result["valid"] = False
    return result


def journal_path(prepared_sha256, *, root=PROJECT_ROOT):
    return root / "output" / f"body-evidence-deepseek-{prepared_sha256.lower()}.calls.jsonl"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--expected-prepared-file-sha256", required=True)
    parser.add_argument("--run-model", action="store_true")
    parser.add_argument("--allow-external-deepseek", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.max_calls <= MAX_CALLS:
            raise ExperimentBlocked("invalid_call_budget")
        settings = admit_environment(
            run_model=args.run_model,
            allow_external_deepseek=args.allow_external_deepseek,
            model_arg=args.model,
        )
        bundle = load_seen_pilot(args.prepared, args.expected_prepared_file_sha256)
        ledger = journal_path(args.expected_prepared_file_sha256)
        if args.output.resolve() in {args.prepared.resolve(), ledger.resolve()}:
            raise ExperimentBlocked("output_path_collision")
        with args.output.open("x", encoding="utf-8") as output:
            try:
                with ledger.open("x", encoding="utf-8") as handle:
                    journal = CallJournal(handle)
                    journal.append(
                        event="run_claim",
                        prepared_file_sha256=args.expected_prepared_file_sha256.lower(),
                        max_calls=args.max_calls,
                        model=settings["model"],
                    )
                    result = run_comparison(
                        bundle,
                        settings,
                        journal,
                        max_calls=args.max_calls,
                        provenance=lambda: execution_provenance(
                            args.prepared,
                            args.expected_prepared_file_sha256,
                            settings,
                            model_arg=args.model,
                        ),
                    )
                    result["journal_path"] = str(ledger)
            except Exception as error:
                result = {
                    "schema": RESULT_SCHEMA,
                    **_inactive(),
                    "valid": False,
                    "error_code": error.code if isinstance(error, ExperimentBlocked) else "run_or_journal_failed",
                }
            json.dump(result, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    except Exception as error:
        code = error.code if isinstance(error, ExperimentBlocked) else "preflight_or_output_failed"
        print(f"DeepSeek experiment stopped: {code}", file=sys.stderr)
        return 2
    print(f"DeepSeek experiment recorded; valid={result['valid']}; production_enabled=false")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
