"""One explicitly authorised execution of the frozen six-cell comparison.

No retries, repairs, revisions, replacement requests, model judge, or alternate
output/allowance database. The fixed claim survives every failure. Late workers
may preserve evidence, but cannot turn a stopped cell into a successful one.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CAMPAIGN = "scoped-basis-comparison-v1"
PREPARED_SHA256 = "6e5be79446840dba636451df8217ec79372dce0a8dde0992ad9cfdfbba2c8d7a"
_CODES = frozenset(
    "flags_required frozen_binding_failed plan_rejected environment_rejected configuration_drift credential_drift "
    "source_drift dependency_drift quota_unavailable quota_configuration quota_day_changed quota_count_changed "
    "campaign_already_claimed recording_failed journal_failed journal_close_failed capture_failed client_close_failed "
    "duplicate_dispatch wrong_cell request_parameters_changed cancelled length protocol_failure timeout transport "
    "authentication_or_permission quota_or_rate_limit service_or_deadline_failure interrupted unexpected_failure".split()
)


class RunStopped(RuntimeError):
    def __init__(self, code):
        self.code = code if code in _CODES else "unexpected_failure"
        super().__init__(self.code)


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write_once(path, value):
    content = _json_bytes(value)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _reason(error):
    if isinstance(error, RunStopped):
        return error.code
    if isinstance(error, KeyboardInterrupt):
        return "interrupted"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ConnectionError):
        return "transport"
    if isinstance(error, OSError):
        return "recording_failed"
    from scripts.evaluate_body_evidence_deepseek import fatal_reason
    from src.model_response import ModelResponseError

    if isinstance(error, ModelResponseError):
        return "length" if error.reason == "length" else "protocol_failure"
    code = fatal_reason(error)
    return code if code in _CODES else "protocol_failure"


def _paths():
    directory = PROJECT_ROOT / "output" / CAMPAIGN
    if directory.resolve() != PROJECT_ROOT.resolve() / "output" / CAMPAIGN:
        raise RunStopped("frozen_binding_failed")
    execution = directory / "execution-v1"
    claim = directory / "campaign.calls.jsonl"
    if execution.is_symlink() or claim.is_symlink():
        raise RunStopped("frozen_binding_failed")
    return directory, execution, claim


def _load_bundle(expected):
    from scripts.scoped_basis_comparison import validate_prepared

    if expected != PREPARED_SHA256:
        raise RunStopped("frozen_binding_failed")
    try:
        bundle = validate_prepared(expected)
    except Exception:
        raise RunStopped("frozen_binding_failed") from None
    plan = bundle["execution_plan"]
    expected_order = [
        {"case_id": case["case_id"], "arm": arm}
        for index, case in enumerate(bundle["cases"])
        for arm in (("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline"))
    ]
    if (
        len(bundle["cases"]) != 3
        or plan["request_order"] != expected_order
        or plan["max_requests"] != 6
        or plan["attempts_per_case_arm"] != 1
        or plan["parameters"]
        != {"temperature": 0.2, "max_output_tokens": 2300, "thinking": "disabled", "sdk_retries": 0}
        or plan["stop_on_first_request_failure"] is not True
        or any(
            plan[key] is not False for key in ("structural_repair", "revision", "model_judge", "replacement_requests")
        )
    ):
        raise RunStopped("plan_rejected")
    return bundle


def _source_identity():
    paths = [path for folder in ("src", "scripts") for path in (PROJECT_ROOT / folder).rglob("*.py")]
    paths.extend(
        PROJECT_ROOT / name
        for name in ("tests/test_scoped_basis_comparison.py", "tests/test_run_scoped_basis_comparison.py")
    )
    return {path.relative_to(PROJECT_ROOT).as_posix(): _sha(path.read_bytes()) for path in sorted(paths)}


def _safe_settings():
    from scripts.evaluate_body_evidence_deepseek import _settings

    try:
        result = _settings()
    except Exception:
        raise RunStopped("environment_rejected") from None
    if result["temperature"] != 0.2 or result["max_tokens"] != 2300 or result["sdk_max_retries"] != 0:
        raise RunStopped("configuration_drift")
    return result


class ExecutionGuard:
    """Read-only identity/quota checks; credential identity stays in memory only."""

    def __init__(self, settings):
        self.settings = copy.deepcopy(settings)
        self.day = _today()
        self._credential = os.environ.get("DEEPSEEK_API_KEY", "")
        if not self._credential:
            raise RunStopped("environment_rejected")
        self.identity = self._identity()
        self.check(0)

    def _identity(self):
        from scripts.evaluate_body_evidence_deepseek import dependency_identity
        from src import config, model_runtime

        configuration = _safe_settings()
        effective = {
            "provider": config.LLM_PROVIDER,
            "model": config.model,
            "endpoint": str(config.MODEL_ENDPOINT).rstrip("/"),
            "temperature": model_runtime.MODEL_TEMPERATURE,
            "max_tokens": model_runtime.MODEL_MAX_TOKENS,
            "timeout_seconds": config.MODEL_TIMEOUT_SECONDS,
            "is_local": config.IS_LOCAL_LLM,
        }
        if (
            effective
            != {
                "provider": "deepseek",
                "model": configuration["model"],
                "endpoint": configuration["endpoint"],
                "temperature": 0.2,
                "max_tokens": 2300,
                "timeout_seconds": configuration["timeout_seconds"],
                "is_local": False,
            }
            or configuration != self.settings
        ):
            raise RunStopped("configuration_drift")
        dependencies = dependency_identity(PROJECT_ROOT)
        dependencies["installed_distributions"] = sorted(
            (distribution.metadata["Name"], distribution.version) for distribution in importlib.metadata.distributions()
        )
        return {
            "sources": _source_identity(),
            "dependencies": dependencies,
            "settings": configuration,
            "effective": effective,
        }

    def check(self, expected_calls):
        from src.model_limits import load_model_limits, read_model_usage

        if not secrets.compare_digest(self._credential.encode(), os.environ.get("DEEPSEEK_API_KEY", "").encode()):
            raise RunStopped("credential_drift")
        if _today() != self.day:
            raise RunStopped("quota_day_changed")
        current = self._identity()
        for field, code in (
            ("sources", "source_drift"),
            ("dependencies", "dependency_drift"),
            ("settings", "configuration_drift"),
            ("effective", "configuration_drift"),
        ):
            if current[field] != self.identity[field]:
                raise RunStopped(code)
        directory, _, _ = _paths()
        if _sha((directory / "prepared.json").read_bytes()) != PREPARED_SHA256:
            raise RunStopped("frozen_binding_failed")
        limits = load_model_limits()
        if (
            limits.daily_calls != 6
            or limits.concurrency != 1
            or limits.database != PROJECT_ROOT.resolve() / "chat_history/model-usage.sqlite3"
        ):
            raise RunStopped("quota_configuration")
        usage = read_model_usage(self.day, limits=limits)
        if usage.get("status") != "ready" or type(usage.get("calls")) is not int:
            raise RunStopped("quota_unavailable")
        if usage.get("day") != self.day:
            raise RunStopped("quota_day_changed")
        if usage["calls"] != expected_calls:
            raise RunStopped("quota_count_changed")
        return {
            "day": self.day,
            "calls": usage["calls"],
            "remaining": 6 - usage["calls"],
            "daily_limit": 6,
            "concurrency": 1,
        }


class Journal:
    def __init__(self, handle):
        self.handle, self.closed = handle, False
        self.lock = threading.Lock()

    def append(self, event, **values):
        with self.lock:
            if self.closed:
                raise RunStopped("journal_failed")
            try:
                line = json.dumps(
                    {"event": event, "at_utc": datetime.now(timezone.utc).isoformat(), **values},
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
                self.handle.write((line + "\n").encode("utf-8"))
                self.handle.flush()
                os.fsync(self.handle.fileno())
            except Exception:
                raise RunStopped("journal_failed") from None

    def close(self):
        with self.lock:
            self.closed = True
            try:
                self.handle.close()
            except Exception:
                raise RunStopped("journal_close_failed") from None


class CampaignState:
    def __init__(self, bundle, settings, guard, directory, journal):
        self.bundle, self.settings, self.guard = bundle, settings, guard
        self.directory, self.journal = directory, journal
        self.cancelled, self.lock, self.stop_lock = threading.Event(), threading.RLock(), threading.Lock()
        self.stop_reason, self.secondary = None, []
        self.recording_incomplete, self.allowances = False, 0
        self.active_sequence = None
        self.rows = [
            {
                "sequence": index,
                **cell,
                "status": "not_run",
                "reason": None,
                "reserved": False,
                "allowance_consumed": False,
                "sdk_started": False,
                "worker_pending": False,
            }
            for index, cell in enumerate(bundle["execution_plan"]["request_order"], 1)
        ]

    def stop(self, code, *, secondary=False):
        code = code if code in _CODES else "unexpected_failure"
        # Cancellation must not wait for a worker performing guarded disk I/O.
        self.cancelled.set()
        with self.stop_lock:
            if self.stop_reason is None:
                self.stop_reason = code
            elif secondary or code != self.stop_reason:
                self.secondary.append(code)
            if code in {"recording_failed", "journal_failed", "journal_close_failed", "capture_failed"}:
                self.recording_incomplete = True

    def artifact(self, name, value):
        try:
            _write_once(self.directory / name, value)
        except Exception:
            self.stop("recording_failed")
            raise RunStopped("recording_failed") from None

    def event(self, event, **values):
        if self.cancelled.is_set() and self.journal.closed:
            raise RunStopped("cancelled")
        try:
            self.journal.append(event, **values)
        except Exception:
            self.stop("journal_failed")
            raise RunStopped("journal_failed") from None


class RecordingSDK:
    """Independent observer: with_options never drops the cancellation/once guard."""

    def __init__(self, sdk, state, row, prompt):
        self.sdk, self.state, self.row, self.prompt = sdk, state, row, prompt
        self.done, self.close_lock = threading.Event(), threading.Lock()
        self.seen, self.closed = False, False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        if kwargs != {"max_retries": 0}:
            self.state.stop("request_parameters_changed")
            if not self.seen:
                self.done.set()
                self._late_close()
            raise RunStopped("request_parameters_changed")
        if self.state.cancelled.is_set():
            if not self.seen or self.done.is_set():
                self.done.set()
                self._late_close()
            raise RunStopped("cancelled")
        # The independent backend was constructed with max_retries=0 already.
        return self

    def _request(self, kwargs):
        from src.model_evidence import json_sha256, text_sha256, validate_recorded_assembly
        from src.model_runtime import GOVERNED_MODEL_SYSTEM_PROMPT

        selected = {"case_id": self.row["case_id"], "arm": self.row["arm"]}
        if self.state.bundle["execution_plan"]["request_order"][self.row["sequence"] - 1] != selected:
            raise RunStopped("wrong_cell")
        case = next(case for case in self.state.bundle["cases"] if case["case_id"] == self.row["case_id"])
        frozen_prompt = case["arms"][self.row["arm"]]["prompt"]
        if str(self.prompt) != frozen_prompt or self.prompt.assembly != case["shared_rag"]:
            raise RunStopped("frozen_binding_failed")
        request = copy.deepcopy(kwargs)
        expected = {
            "model": self.state.settings["model"],
            "messages": [
                {"role": "system", "content": GOVERNED_MODEL_SYSTEM_PROMPT},
                {"role": "user", "content": frozen_prompt.strip()},
            ],
            "temperature": 0.2,
            "top_p": 0.8,
            "max_tokens": 2300,
            "stream": False,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if _json_bytes(request) != _json_bytes(expected):
            raise RunStopped("request_parameters_changed")
        binding = getattr(kwargs["messages"], "submitted_binding", None)
        if not isinstance(binding, dict) or binding.get("messages_sha256") != json_sha256(request["messages"]):
            raise RunStopped("capture_failed")
        assembly = self.prompt.assembly
        if (
            validate_recorded_assembly(assembly, case["arms"][self.row["arm"]]["analysis"])
            != assembly["visible_chunks"]
            or str(self.prompt).strip().count(assembly["context"]) != 1
        ):
            raise RunStopped("capture_failed")
        return {
            "boundary": "application_sdk_invocation_intent_not_provider_receipt",
            "request": request,
            "request_binding": binding,
            "frozen_prompt_sha256": text_sha256(frozen_prompt),
            "submitted_user_sha256": text_sha256(str(self.prompt).strip()),
            "rag_assembly": assembly,
        }

    def _raw_response(self, response, elapsed, binding):
        from src.model_evidence import capture_model_evidence, text_sha256
        from src.model_runtime import clean_model_output

        try:
            raw = response.model_dump(mode="json")
        except Exception:
            raise RunStopped("capture_failed") from None
        # Persist the provider object before inspecting any protocol/metadata
        # shape. A malformed but serialisable response is still audit evidence.
        self.state.artifact(
            f"response-{self.row['sequence']:02}.json",
            {
                "raw_response": raw,
                "raw_response_sha256": _sha(_json_bytes(raw)),
                "sdk_elapsed_seconds": elapsed,
                "after_stop": self.state.cancelled.is_set(),
            },
        )
        choices = raw.get("choices") if isinstance(raw, dict) else None
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise RunStopped("protocol_failure")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RunStopped("protocol_failure")
        if (
            any(raw.get(key) is not None and not isinstance(raw[key], str) for key in ("model", "system_fingerprint"))
            or raw.get("usage") is not None
            and not isinstance(raw["usage"], dict)
        ):
            raise RunStopped("capture_failed")
        content = message.get("content")
        preview = clean_model_output(content) if isinstance(content, str) else None
        capture = None
        if preview is not None:
            client = SimpleNamespace(last_request_capture={**binding, "response_sha256": text_sha256(preview)})
            capture = capture_model_evidence(self.prompt, client, preview, attempt_number=1)
        payload = {
            "raw_response_sha256": _sha(_json_bytes(raw)),
            "sdk_elapsed_seconds": elapsed,
            "cleaned_response_candidate": preview,
            "cleaned_sha256": text_sha256(preview) if preview is not None else None,
            "admission_status": "not_admitted_by_this_capture",
            "model_evidence": capture,
            "provider_returned_model": raw.get("model"),
            "system_fingerprint": raw.get("system_fingerprint"),
            "usage": raw.get("usage"),
            "after_stop": self.state.cancelled.is_set(),
            "provider_effective_parameters": None,
            "immutable_model_weights": None,
        }
        self.state.artifact(f"response-details-{self.row['sequence']:02}.json", payload)
        if capture is not None and capture["status"] != "captured":
            raise RunStopped("capture_failed")
        if len(choices) == 1 and choices[0].get("finish_reason") == "length":
            self.state.stop("length")

    def create(self, **kwargs):
        started = None
        owns_attempt = False
        try:
            with self.state.lock:
                if self.seen:
                    raise RunStopped("duplicate_dispatch")
                self.seen = True
                owns_attempt = True
                if self.state.cancelled.is_set():
                    raise RunStopped("cancelled")
                if self.state.active_sequence != self.row["sequence"] or not self.row["reserved"]:
                    raise RunStopped("wrong_cell")
                usage = self.state.guard.check(self.state.allowances + 1)
                self.state.allowances += 1
                self.row["allowance_consumed"] = True
                if self.state.cancelled.is_set():
                    self.state.artifact(
                        f"late-boundary-{self.row['sequence']:02}.json",
                        {"quota": usage, "sdk_started": False, "reason": "cancelled"},
                    )
                    raise RunStopped("cancelled")
                self.state.event("allowance_consumed", sequence=self.row["sequence"], quota=usage)
                request = self._request(kwargs)
                self.state.artifact(f"request-{self.row['sequence']:02}.json", request)
                if self.state.cancelled.is_set():
                    raise RunStopped("cancelled")
                self.state.event("sdk_started", sequence=self.row["sequence"], provider_receipt="unknown")
                if self.state.cancelled.is_set():
                    raise RunStopped("cancelled")
                self.row["sdk_started"] = True
                started = time.monotonic()
            response = self.sdk.chat.completions.create(**kwargs)
            self._raw_response(response, time.monotonic() - started, request["request_binding"])
            return response
        except (Exception, KeyboardInterrupt) as error:
            self.state.stop(_reason(error))
            if (
                started is not None
                and _reason(error) not in {"recording_failed", "capture_failed"}
                and not (self.state.directory / f"response-{self.row['sequence']:02}.json").exists()
            ):
                self.state.artifact(
                    f"response-{self.row['sequence']:02}.json",
                    {
                        "raw_response": None,
                        "reason": _reason(error),
                        "campaign_stop_reason": self.state.stop_reason,
                        "sdk_elapsed_seconds": time.monotonic() - started,
                        "provider_outcome": "unknown",
                        "after_stop": True,
                    },
                )
            raise
        finally:
            if owns_attempt:
                self.done.set()
                if self.state.cancelled.is_set():
                    self._late_close()

    def close(self):
        with self.close_lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.sdk.close()
            except Exception:
                self.state.stop("client_close_failed", secondary=True)
                raise RunStopped("client_close_failed") from None

    def _late_close(self):
        try:
            self.close()
        except Exception:
            # Never use a journal that the main thread may already have closed.
            try:
                self.state.artifact(
                    f"late-cleanup-{self.row['sequence']:02}.json",
                    {"reason": "client_close_failed", "does_not_change_stopped_result": True},
                )
            except Exception:
                self.state.recording_incomplete = True


def _client(settings, state, row, prompt):
    from openai import OpenAI

    from scripts.evaluate_body_evidence_deepseek import build_client

    owned = []

    def factory(**kwargs):
        try:
            if (
                kwargs["base_url"] != settings["endpoint"]
                or kwargs["max_retries"] != 0
                or not secrets.compare_digest(kwargs["api_key"].encode(), state.guard._credential.encode())
            ):
                raise RunStopped("configuration_drift")
            observer = RecordingSDK(OpenAI(**kwargs), state, row, prompt)
            owned.append(observer)
            return observer
        except Exception as error:
            state.stop(_reason(error))
            try:
                kwargs["http_client"].close()
            except Exception:
                state.stop("client_close_failed", secondary=True)
            raise

    try:
        return build_client(settings, sdk_factory=factory)
    except Exception as error:
        state.stop(_reason(error))
        for observer in owned:
            try:
                observer.close()
            except Exception:
                state.stop("client_close_failed", secondary=True)
        raise RunStopped(state.stop_reason) from None


def _run_cell(state, row, factory):
    from src.model_evidence import EvidencePrompt, capture_model_evidence, text_sha256

    client = observer = None
    started = time.monotonic()
    generation_started = None
    try:
        state.guard.check(state.allowances)
        case = next(case for case in state.bundle["cases"] if case["case_id"] == row["case_id"])
        arm = case["arms"][row["arm"]]
        prompt = EvidencePrompt(arm["prompt"], assembly=case["shared_rag"], request_kind="initial")
        state.active_sequence = row["sequence"]
        row["reserved"] = True
        state.event("reserved", sequence=row["sequence"], case_id=row["case_id"], arm=row["arm"])
        client, observer = factory(state.settings, state, row, prompt)
        row["allowance_consumed"] = None  # Unknown until the post-consumption counter is verified.
        generation_started = time.monotonic()
        response = client.generate(prompt)
        if state.cancelled.is_set():
            raise RunStopped(state.stop_reason)
        capture = capture_model_evidence(prompt, client, response, attempt_number=1)
        if capture["status"] != "captured" or not observer.done.is_set() or not row["sdk_started"]:
            raise RunStopped("capture_failed")
        state.guard.check(state.allowances)
        row.update(
            status="generated", cleaned_response=response, cleaned_sha256=text_sha256(response), model_evidence=capture
        )
    except (Exception, KeyboardInterrupt) as error:
        code = _reason(error)
        if (
            observer is not None
            and not observer.done.is_set()
            and not isinstance(error, RunStopped)
            and generation_started is not None
            and time.monotonic() - generation_started >= state.settings["timeout_seconds"]
        ):
            code = "timeout"
        state.stop(code)
        row.update(status="failed", reason=state.stop_reason)
    finally:
        row["governed_elapsed_seconds"] = (
            time.monotonic() - generation_started if generation_started is not None else None
        )
        row["cell_elapsed_seconds"] = time.monotonic() - started
        if observer is not None:
            row["worker_pending"] = not observer.done.is_set()
            if observer.done.is_set():
                try:
                    observer.close()
                except Exception:
                    state.stop("client_close_failed", secondary=True)
            # An unfinished worker owns its SDK. Its observer closes it after
            # returning or after cancellation rejects a delayed with_options.
        if state.stop_reason:
            row.update(status="failed", reason=state.stop_reason)
        try:
            state.guard.check(state.allowances)
        except Exception as error:
            state.stop(_reason(error), secondary=True)
            row.update(status="failed", reason=state.stop_reason)


def execute(bundle, settings, guard, *, factory=None):
    """Internal admitted execution; main performs flags/environment checks first."""
    factory = factory or _client
    directory, output, claim = _paths()
    try:
        handle = claim.open("xb")
    except FileExistsError:
        raise RunStopped("campaign_already_claimed") from None
    journal = Journal(handle)
    state = CampaignState(bundle, settings, guard, output, journal)
    quota_end = None
    try:
        output.mkdir(exist_ok=False)
        state.event(
            "campaign_claimed", prepared_file_sha256=PREPARED_SHA256, planned_cells=state.rows, maximum_sdk_dispatches=6
        )
        state.artifact(
            "snapshot.json",
            {
                "prepared_file_sha256": PREPARED_SHA256,
                "source_dependency_configuration": guard.identity,
                "quota_initial": guard.check(0),
                "frozen_plan": bundle["execution_plan"],
                "rows": state.rows,
            },
        )
        for row in state.rows:
            if state.cancelled.is_set():
                row["reason"] = state.stop_reason
                continue
            _run_cell(state, row, factory)
            state.artifact(f"result-{row['sequence']:02}.json", copy.deepcopy(row))
            state.event("cell_finished", sequence=row["sequence"], status=row["status"], reason=row["reason"])
        quota_end = guard.check(state.allowances)
        state.event("campaign_finished", stop_reason=state.stop_reason, quota=quota_end)
    except (Exception, KeyboardInterrupt) as error:
        state.stop(_reason(error))
    finally:
        if any(row["worker_pending"] for row in state.rows):
            state.cancelled.set()
        try:
            journal.close()
        except Exception:
            state.stop("journal_close_failed", secondary=True)
    for row in state.rows:
        if row["status"] == "not_run":
            row["reason"] = state.stop_reason
    result = {
        "schema": "scoped-basis-execution-v1",
        "campaign": CAMPAIGN,
        "prepared_file_sha256": PREPARED_SHA256,
        "rows": copy.deepcopy(state.rows),
        "stop_reason": state.stop_reason,
        "secondary_errors": list(state.secondary),
        "recording_incomplete": state.recording_incomplete,
        "quota_end": quota_end,
        "sdk_dispatches_committed": sum(row["sdk_started"] for row in state.rows),
        "allowances_observed": state.allowances,
        "late_evidence_note": "A pending worker may only add response/cleanup files; a stopped row cannot become generated.",
        "semantic_review": "not_performed",
        "semantic_accuracy": None,
        "production_enabled": False,
        "release_gate": "inactive",
    }
    try:
        state.artifact("results.json", result)
    except Exception:
        result.update(recording_incomplete=True, stop_reason=state.stop_reason, secondary_errors=list(state.secondary))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run",))
    parser.add_argument("--run-model", action="store_true")
    parser.add_argument("--allow-external-deepseek", action="store_true")
    parser.add_argument("--expected-prepared-file-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if not args.run_model or not args.allow_external_deepseek:
            raise RunStopped("flags_required")
        bundle = _load_bundle(args.expected_prepared_file_sha256)
        from scripts.evaluate_body_evidence_deepseek import admit_environment

        settings = admit_environment(run_model=True, allow_external_deepseek=True)
        guard = ExecutionGuard(settings)
        result = execute(bundle, settings, guard)
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "campaign",
                        "stop_reason",
                        "recording_incomplete",
                        "sdk_dispatches_committed",
                        "secondary_errors",
                    )
                }
            )
        )
        return 2 if result["stop_reason"] or result["recording_incomplete"] else 0
    except (Exception, KeyboardInterrupt) as error:
        code = error.code if isinstance(error, RunStopped) else "environment_rejected"
        print(json.dumps({"status": "stopped", "reason": code, "no_automatic_retry": True}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
