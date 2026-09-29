"""One fixed, six-call synthetic development comparison; never a release gate.

Prepare is offline. Run requires explicit external-call flags and a prepared-file
hash. A fixed, exclusively created journal permanently claims this campaign.
There is no retrieval, holdout access, retry, revision, or structural repair.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess  # nosec B404
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_body_evidence_deepseek import (  # noqa: E402
    ExperimentBlocked,
    admit_environment,
    build_client,
    dependency_identity,
    fatal_reason,
)
from scripts.evaluation_artifacts import sha256_file  # noqa: E402
from src.model_evidence import EvidencePrompt, capture_model_evidence, json_sha256, text_sha256  # noqa: E402

CAMPAIGN = "section-scope-comparison-20260929"
BASELINE = "3a00f3c"
CURRENT = "f4ae47c"
MAX_CALLS = 6
OUTPUT = PROJECT_ROOT / "output" / CAMPAIGN
LIMITATIONS = (
    "Synthetic evidence copied from development prompt-contract tests; not real official excerpts, "
    "independent generalisation evidence, statistical significance, or a production acceptance gate. "
    "Initial generation only. SDK submission does not prove provider receipt, attention, or immutable weights."
)
PASSAGES = (
    ("maintenance-only", ("Inspect roofing and gutters; remove debris from underfloor spaces.",)),
    (
        "mixed-first-aid-maintenance",
        (
            "Inspect roofing and gutters; remove debris from underfloor spaces.",
            "During a first-aid exercise, staff practise contacting the first-aid coordinator and record a debrief.",
        ),
    ),
    ("no-related-evidence", ()),
)


def _git(*args):
    # Only fixed local Git provenance arguments are supplied by this script.
    result = subprocess.run(  # nosec B603 B607
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, check=False, timeout=10
    )
    if result.returncode:
        raise ExperimentBlocked("git_provenance_unavailable")
    return result.stdout.decode("utf-8")


def _write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _journal(handle, event, **fields):
    handle.write(json.dumps({"event": event, "at_utc": datetime.now(timezone.utc).isoformat(), **fields}) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _source_identity():
    paths = sorted((PROJECT_ROOT / "src").rglob("*.py"))
    paths += [
        Path(__file__),
        PROJECT_ROOT / "tests/test_section_scope_comparison.py",
        PROJECT_ROOT / "tests/test_report_prompt_contract.py",
        PROJECT_ROOT / "scripts/evaluate_body_evidence_deepseek.py",
        PROJECT_ROOT / "scripts/evaluate_body_evidence_ab.py",
        PROJECT_ROOT / "scripts/evaluation_artifacts.py",
    ]
    return {path.relative_to(PROJECT_ROOT).as_posix(): sha256_file(path) for path in paths}


def prepare_bundle():
    """Generate only fixed synthetic inputs; do not import config or load dotenv."""
    from src.agents.report_agent import ReportAgent
    from src.rag.service import assemble_retrieved_context
    from src.report_template import SECTION_PURPOSE_GUIDANCE, build_report_prompt
    from src.source_attribution import format_rag_citation_token

    old_source = _git("show", f"{BASELINE}:src/report_template.py")
    current_source = _git("show", f"{CURRENT}:src/report_template.py")
    if (PROJECT_ROOT / "src/report_template.py").read_text(encoding="utf-8") != current_source:
        raise ExperimentBlocked("current_prompt_source_drift")
    # These are the old template's complete direct imports. Their unchanged Git
    # bytes, and frozen current tree, bind the old builder to the same helpers.
    shared = ("evidence_confidence", "focus_coverage", "governance", "source_attribution")
    for name in shared:
        shared_source = _git("show", f"{CURRENT}:src/{name}.py")
        if (
            _git("show", f"{BASELINE}:src/{name}.py") != shared_source
            or (PROJECT_ROOT / f"src/{name}.py").read_text(encoding="utf-8") != shared_source
        ):
            raise ExperimentBlocked("baseline_shared_dependency_drift")
    historical = {"__name__": "section_scope_historical_template"}
    exec(compile(old_source, f"git:{BASELINE}:src/report_template.py", "exec"), historical)  # nosec B102
    cases = []
    for case_id, passages in PASSAGES:
        chunks = [
            {
                "source_id": f"synthetic-scope-{index}",
                "chunk_id": f"scope-chunk-{index}",
                "title": f"Synthetic section-purpose passage {index}",
                "chunk_sha256": text_sha256(passage),
                "text": passage,
            }
            for index, passage in enumerate(passages)
        ]
        knowledge = {
            "status_label": "Synthetic development evidence; not official excerpts",
            "retrieved_chunks": chunks,
        }
        data = {"sources": [], "data_limitations": ["Synthetic fixture only; no real official evidence supplied."]}
        assembly = assemble_retrieved_context(knowledge)
        analysis = {
            "data": data,
            "knowledge": knowledge,
            "rag_context_assembly": assembly,
            "prompt_context": ReportAgent().run(
                {"state": "Queensland", "setting_type": "community"},
                data,
                {"risk_points": [], "assumptions": []},
                {"planning_priorities": []},
                knowledge_result=knowledge,
                rag_assembly=assembly,
            ),
        }
        inputs = {
            "location": "Cairns, Queensland",
            "audience": "Council resilience officers",
            "scenario": "Pre-season planning",
            "concerns": ["Evacuation", "Communications"],
            "timeframe": "Before the next fire season",
            "extra_context": "Synthetic development scenario. Confirm local arrangements.",
            "analysis": analysis,
            "area_selection": {"type": "FeatureCollection", "features": []},
            "governance_context": "Synthetic development comparison. No real official excerpts or local arrangements supplied.",
        }
        baseline, current = historical["build_report_prompt"](**inputs), build_report_prompt(**inputs)
        insertion = SECTION_PURPOSE_GUIDANCE + "\n\n"
        if current.count(insertion) != 1 or current.replace(insertion, "", 1) != baseline:
            raise ExperimentBlocked("baseline_prompt_equivalence_failed")
        cases.append(
            {
                "case_id": case_id,
                "inputs": inputs,
                "analysis_sha256": json_sha256(analysis),
                "synthetic_evidence": [
                    {**chunk, "citation_token": format_rag_citation_token(chunk)} for chunk in chunks
                ],
                "prompts": {"baseline": baseline, "current": current},
                "prompt_sha256": {"baseline": text_sha256(baseline), "current": text_sha256(current)},
            }
        )
    return {
        "schema": "section-scope-prepared-v1",
        "campaign": CAMPAIGN,
        "limitations": LIMITATIONS,
        "max_calls": MAX_CALLS,
        "baseline_commit": _git("rev-parse", BASELINE).strip(),
        "current_commit": _git("rev-parse", CURRENT).strip(),
        "baseline_template_sha256": text_sha256(old_source),
        "current_template_sha256": text_sha256(current_source),
        "baseline_equivalence": "Old Git builder equals current minus exact SECTION_PURPOSE_GUIDANCE and two newlines, for all three inputs.",
        "source_sha256": _source_identity(),
        "cases": cases,
    }


def _load_prepared(expected):
    raw = (OUTPUT / "prepared.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ExperimentBlocked("prepared_file_hash_mismatch")
    bundle = json.loads(raw)
    if bundle != prepare_bundle():
        raise ExperimentBlocked("frozen_input_or_source_drift")
    return bundle


def quota_preflight():
    """Inspect the existing shared allowance. Never change settings or counters."""
    from src.model_limits import load_model_limits, read_model_usage

    limits = load_model_limits()
    if limits.concurrency != 1 or not 0 < limits.daily_calls <= MAX_CALLS:
        raise ExperimentBlocked("bounded_shared_quota_required")
    if limits.database != (PROJECT_ROOT / "chat_history/model-usage.sqlite3").resolve():
        raise ExperimentBlocked("default_shared_quota_database_required")
    usage = read_model_usage(limits=limits)
    if usage["status"] == "unavailable":
        raise ExperimentBlocked("shared_quota_unavailable")
    # A new default database may be initialized normally by consume_call. We do
    # not claim an absent DB proves zero historical use, nor create another DB.
    remaining = limits.daily_calls - usage["calls"] if usage["status"] == "ready" else None
    return {
        "daily_limit": limits.daily_calls,
        "concurrency": limits.concurrency,
        "usage": usage,
        "remaining": remaining,
    }


class RecordingSDK:
    """Observe the real SDK boundary without replacing the governed runtime."""

    def __init__(self, sdk, directory, sequence, journal, state=None):
        self.sdk, self.directory, self.sequence = sdk, directory, sequence
        self.journal = journal
        self.state = state if state is not None else {"submitted": False}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        if kwargs != {"max_retries": 0}:
            raise ExperimentBlocked("sdk_retry_configuration_rejected")
        return RecordingSDK(self.sdk.with_options(**kwargs), self.directory, self.sequence, self.journal, self.state)

    def create(self, **kwargs):
        if self.state["submitted"]:
            raise ExperimentBlocked("duplicate_sdk_submission_rejected")
        self.state["submitted"] = True
        request = copy.deepcopy(kwargs)
        _write(
            self.directory / f"request-{self.sequence:02}.json",
            {
                "capture_boundary": "application_sdk_submission_not_provider_receipt",
                "request": request,
                "messages_sha256": json_sha256(request["messages"]),
                "user_prompt_sha256": text_sha256(request["messages"][1]["content"]),
            },
        )
        _journal(
            self.journal, "sdk_submission", sequence=self.sequence, messages_sha256=json_sha256(request["messages"])
        )
        started = time.monotonic()
        try:
            response = self.sdk.chat.completions.create(**kwargs)
        except Exception as error:
            _write(
                self.directory / f"response-{self.sequence:02}.json",
                {
                    "elapsed_seconds": time.monotonic() - started,
                    "raw_response": None,
                    "error_code": fatal_reason(error),
                    "provider_outcome": "unknown",
                },
            )
            raise
        _write(
            self.directory / f"response-{self.sequence:02}.json",
            {
                "elapsed_seconds": time.monotonic() - started,
                "raw_response": response.model_dump(mode="json"),
                "error_code": None,
            },
        )
        return response

    def close(self):
        self.sdk.close()


def _client(settings, sequence, handle):
    from openai import OpenAI

    return build_client(settings, sdk_factory=lambda **kwargs: RecordingSDK(OpenAI(**kwargs), OUTPUT, sequence, handle))


def run_comparison(bundle, settings, handle, *, factory=_client, check=None):
    """At most six initial generations; every failure stops the whole campaign."""
    rows, stopped = [], None
    for index, case in enumerate(bundle["cases"]):
        order = ("baseline", "current") if index % 2 == 0 else ("current", "baseline")
        for variant in order:
            sequence = len(rows) + 1
            row = {
                "sequence": sequence,
                "case_id": case["case_id"],
                "variant": variant,
                "status": "not_run",
                "error_code": stopped,
                "attempts": 0,
            }
            if not stopped:
                client = closeable = None
                try:
                    if check is not None:
                        check()
                    client, closeable = factory(settings, sequence, handle)
                    _journal(handle, "before_call", sequence=sequence, case_id=case["case_id"], variant=variant)
                    row["attempts"] = 1
                    prompt = EvidencePrompt(
                        case["prompts"][variant], assembly=case["inputs"]["analysis"]["rag_context_assembly"]
                    )
                    started = time.monotonic()
                    response = client.generate(prompt)
                    row.update(
                        status="generated",
                        cleaned_response=response,
                        elapsed_seconds=time.monotonic() - started,
                        model_evidence=capture_model_evidence(prompt, client, response, attempt_number=1),
                    )
                except Exception as error:
                    code = (
                        error.code
                        if isinstance(error, ExperimentBlocked)
                        else fatal_reason(error) or "protocol_rejected"
                    )
                    row.update(status="failed", error_code=code)
                    stopped = code
                finally:
                    # A timed-out SDK worker may still own the transport. The
                    # fixed journal remains spent; no subsequent request runs.
                    if closeable is not None and not stopped:
                        try:
                            closeable.close()
                        except Exception:
                            stopped = "client_cleanup_failed"
                _write(OUTPUT / f"result-{sequence:02}.json", row)
                _journal(handle, "after_call", sequence=sequence, status=row["status"], error_code=row["error_code"])
            rows.append(row)
    return {
        "schema": "section-scope-results-v1",
        "campaign": CAMPAIGN,
        "limitations": LIMITATIONS,
        "execution_configuration": settings,
        "rows": rows,
        "stop_reason": stopped,
        "attempted_governed_calls": sum(row["attempts"] for row in rows),
        "semantic_review": "pending_ai_assisted_review",
        "production_enabled": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--expected-prepared-file-sha256")
    parser.add_argument("--run-model", action="store_true")
    parser.add_argument("--allow-external-deepseek", action="store_true")
    args = parser.parse_args(argv)
    try:
        if OUTPUT.resolve() != PROJECT_ROOT.resolve() / "output" / CAMPAIGN:
            raise ExperimentBlocked("output_path_redirected")
        if args.command == "prepare":
            bundle = prepare_bundle()
            OUTPUT.mkdir(parents=True, exist_ok=True)
            _write(OUTPUT / "prepared.json", bundle)
            print(
                json.dumps(
                    {"status": "prepared_offline", "prepared_file_sha256": sha256_file(OUTPUT / "prepared.json")}
                )
            )
            return 0
        bundle = _load_prepared(args.expected_prepared_file_sha256)
        settings = admit_environment(run_model=args.run_model, allow_external_deepseek=args.allow_external_deepseek)
        quota = quota_preflight()
        if quota["remaining"] is not None and quota["remaining"] < MAX_CALLS:
            print(json.dumps({"status": "blocked", "error_code": "insufficient_shared_allowance", "quota": quota}))
            return 2
        if quota["daily_limit"] < MAX_CALLS:
            raise ExperimentBlocked("insufficient_shared_allowance")
        with (OUTPUT / "campaign.calls.jsonl").open("x", encoding="utf-8") as handle:
            _journal(
                handle,
                "campaign_claim",
                campaign=CAMPAIGN,
                max_calls=MAX_CALLS,
                prepared_file_sha256=args.expected_prepared_file_sha256,
            )

            def check():
                _load_prepared(args.expected_prepared_file_sha256)
                current = admit_environment(
                    run_model=True, allow_external_deepseek=True, dotenv_loader=lambda *a, **k: None
                )
                if current != settings:
                    raise ExperimentBlocked("execution_configuration_drift")
                quota_preflight()

            result = run_comparison(bundle, settings, handle, check=check)
            result.update(
                quota_before=quota, quota_after=quota_preflight(), dependencies=dependency_identity(PROJECT_ROOT)
            )
            _write(OUTPUT / "results.json", result)
            _journal(handle, "campaign_closed", attempted_governed_calls=result["attempted_governed_calls"])
        print(
            json.dumps(
                {
                    "status": "recorded",
                    "attempted_governed_calls": result["attempted_governed_calls"],
                    "stop_reason": result["stop_reason"],
                }
            )
        )
        return 0 if all(row["status"] == "generated" for row in result["rows"]) else 1
    except Exception as error:
        code = error.code if isinstance(error, ExperimentBlocked) else "campaign_io_or_configuration_failure"
        print(json.dumps({"status": "blocked", "error_code": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
