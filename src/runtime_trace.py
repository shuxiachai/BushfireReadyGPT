"""Privacy-minimised local operational traces, separate from governance audit records."""

from __future__ import annotations

import json
import math
import os
import re
import stat
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.data_artifacts import atomic_write_json
from src.runtime_paths import runtime_path

TRACE_SCHEMA = "bushfire-runtime-trace-v1"
MAX_TRACE_FILE_BYTES = 128 * 1024
MAX_TRACE_SCAN_ENTRIES = 5000
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE_DIR = PROJECT_ROOT / "chat_history" / "traces"
_ACTIVE_TRACE = ContextVar("bushfire_active_runtime_trace", default=None)

_OPERATIONS = {"report.generate", "report.revise"}
_STAGES = {
    "analysis_pipeline",
    "data_integrity",
    "profile_agent",
    "australian_data_agent",
    "community_vulnerability_agent",
    "official_knowledge_agent",
    "risk_context_agent",
    "planner_agent",
    "report_agent",
    "evidence_confidence",
    "prompt_build",
    "model_generation",
    "model_repair",
    "model_response_validation",
    "grounding_evaluation",
    "governance_finalize",
    "audit_write",
    "session_persist",
}
_BOOLEAN_METRICS = {
    "artifact_core_ready",
    "audit_written",
    "map_selection_present",
    "repair_required",
    "session_persisted",
    "structural_gate_passed",
}
_INTEGER_METRICS = {
    "attempt",
    "claims_evaluated",
    "generation_attempts",
    "jurisdiction_conflicts",
    "prompt_characters",
    "report_characters",
    "report_version",
    "response_characters",
    "retrieved_chunks",
}
_RATE_METRICS = {
    "citation_coverage_rate",
    "numeric_consistency_rate",
    "support_rate",
}
_STRING_METRICS = {
    "error_code": re.compile(r"[a-z][a-z0-9_]{0,63}\Z"),
    "grounding_status": re.compile(r"(?:pass|review_required|not_applicable|error|unknown)\Z"),
    "knowledge_status": re.compile(
        r"(?:ready|unavailable|disabled|not_installed|not_built|no_match|out_of_scope|invalid|error|unknown)\Z"
    ),
    "model_boundary": re.compile(r"(?:local_loopback|external)\Z"),
    "model_finish_reason": re.compile(
        r"(?:stop|length|content_filter|tool_calls|function_call|missing|invalid|"
        r"incomplete_narrative|unsafe_operational_direction)\Z"
    ),
    "report_source": re.compile(r"(?:generated|revised)\Z"),
}
_PRIVACY_EXCLUDED = [
    "prompts",
    "model responses",
    "report text",
    "retrieved passages",
    "locations and audiences",
    "reviewer identity",
    "free-text user input",
]


class TracePrivacyError(ValueError):
    """Raised when instrumentation attempts to record non-allowlisted content."""


class RuntimeTrace:
    def __init__(self, operation, **metrics):
        if operation not in _OPERATIONS:
            raise ValueError(f"Unsupported trace operation: {operation}")
        self.operation = operation
        self.trace_id = uuid4().hex
        self.enabled = _trace_enabled()
        self.started_at_utc = _utc_now()
        self._started = time.perf_counter()
        self._metrics = _safe_metrics(metrics)
        self._stages = []
        self._outcome = None
        self._error_code = None
        self._token = None
        self.path = None
        self.write_error = False

    def __enter__(self):
        self._token = _ACTIVE_TRACE.set(self)
        return self

    def __exit__(self, error_type, error, _traceback):
        if error is not None:
            self.set_outcome("failed", _safe_error_code(error))
        elif self._outcome is None:
            self.set_outcome("success")
        self._write()
        if self._token is not None:
            _ACTIVE_TRACE.reset(self._token)
            self._token = None
        return False

    def add_metrics(self, **metrics):
        self._metrics.update(_safe_metrics(metrics))

    def set_outcome(self, status, error_code=None):
        if status not in {"success", "failed", "cancelled"}:
            raise ValueError("Trace status must be success, failed or cancelled.")
        self._outcome = status
        self._error_code = _safe_error_code(error_code) if error_code else None

    @contextmanager
    def stage(self, name, **metrics):
        if name not in _STAGES:
            raise ValueError(f"Unsupported trace stage: {name}")
        span = TraceStage(name, metrics)
        try:
            yield span
        except Exception as error:
            span.status = "error"
            span.error_code = _safe_error_code(error)
            raise
        finally:
            span.finish()
            if len(self._stages) < 50:
                self._stages.append(span.as_record())

    def _write(self):
        if not self.enabled:
            return
        duration_ms = max(0, round((time.perf_counter() - self._started) * 1000, 2))
        payload = {
            "schema": TRACE_SCHEMA,
            "trace_id": self.trace_id,
            "operation": self.operation,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": _utc_now(),
            "status": self._outcome or "failed",
            "error_code": self._error_code,
            "duration_ms": duration_ms,
            "metrics": self._metrics,
            "stages": self._stages,
            "privacy": {
                "content_stored": False,
                "excluded": list(_PRIVACY_EXCLUDED),
            },
        }
        try:
            directory = _trace_dir()
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"trace_{self.trace_id}.json"
            atomic_write_json(target, payload)
            try:
                target.chmod(0o600)
            except OSError:
                pass
            self.path = str(target)
        except (OSError, TypeError, ValueError):
            self.write_error = True


class TraceStage:
    def __init__(self, name, metrics):
        self.name = name
        self.metrics = _safe_metrics(metrics)
        self.status = "success"
        self.error_code = None
        self._started = time.perf_counter()
        self.duration_ms = 0.0

    def add_metrics(self, **metrics):
        self.metrics.update(_safe_metrics(metrics))

    def finish(self):
        self.duration_ms = max(0, round((time.perf_counter() - self._started) * 1000, 2))

    def as_record(self):
        return {
            "name": self.name,
            "status": self.status,
            "error_code": self.error_code,
            "duration_ms": self.duration_ms,
            "metrics": self.metrics,
        }


class _NoopStage:
    def add_metrics(self, **_metrics):
        return None


@contextmanager
def trace_stage(name, **metrics):
    trace = get_active_trace()
    if trace is None:
        yield _NoopStage()
        return
    with trace.stage(name, **metrics) as span:
        yield span


def get_active_trace():
    return _ACTIVE_TRACE.get()


def load_trace_summary(*, trace_dir=None, limit=200):
    """Summarise recent valid traces in a bounded directory sample.

    A truncated scan is not the globally newest set. The returned scan counters
    explicitly distinguish known unselected files from an unknown remainder.
    """

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("Trace summary limit must be an integer from 1 to 1000.")
    directory = Path(trace_dir).resolve() if trace_dir is not None else _trace_dir()
    if not directory.is_dir():
        return _empty_summary()
    paths, scan_status, invalid_files = _scan_trace_candidates(directory, limit)
    records = []
    for path in paths:
        try:
            scan_status["files_read"] += 1
            if path.stat().st_size > MAX_TRACE_FILE_BYTES:
                raise ValueError("oversized trace")
            with path.open("rb") as file:
                raw = file.read(MAX_TRACE_FILE_BYTES + 1)
            if len(raw) > MAX_TRACE_FILE_BYTES:
                raise ValueError("oversized trace")
            record = json.loads(raw.decode("utf-8"))
            if not _valid_trace_record(record):
                raise ValueError("invalid trace")
            records.append(record)
        except (OSError, UnicodeError, ValueError, RecursionError):
            invalid_files += 1
    if not records:
        summary = _empty_summary()
        summary["invalid_files"] = invalid_files
        summary.update(scan_status)
        return summary

    durations = [float(record["duration_ms"]) for record in records]
    stage_durations = defaultdict(list)
    stage_errors = Counter()
    for record in records:
        for stage in record["stages"]:
            stage_durations[stage["name"]].append(float(stage["duration_ms"]))
            if stage.get("error_code"):
                stage_errors[f"{stage['name']}:{stage['error_code']}"] += 1
    successes = sum(1 for record in records if record["status"] == "success")
    return {
        "schema": TRACE_SCHEMA,
        **scan_status,
        "traces": len(records),
        "invalid_files": invalid_files,
        "success_rate": round(successes / len(records), 4),
        "duration_ms": {"p50": _percentile(durations, 0.5), "p95": _percentile(durations, 0.95)},
        "operations": dict(sorted(Counter(record["operation"] for record in records).items())),
        "failure_codes": dict(
            sorted(Counter(record.get("error_code") for record in records if record.get("error_code")).items())
        ),
        "stage_errors": dict(sorted(stage_errors.items())),
        "stage_duration_ms": {
            name: {"p50": _percentile(values, 0.5), "p95": _percentile(values, 0.95)}
            for name, values in sorted(stage_durations.items())
        },
        "repair_rate": round(
            sum(1 for record in records if record["metrics"].get("repair_required") is True) / len(records), 4
        ),
        "grounding_review_rate": round(
            sum(1 for record in records if record["metrics"].get("grounding_status") == "review_required")
            / len(records),
            4,
        ),
        "recent": [
            {
                "trace_id": record["trace_id"],
                "completed_at_utc": record["completed_at_utc"],
                "operation": record["operation"],
                "status": record["status"],
                "error_code": record.get("error_code"),
                "duration_ms": record["duration_ms"],
                "stage_count": len(record["stages"]),
            }
            for record in records[:10]
        ],
    }


def _scan_trace_candidates(directory, limit):
    candidates = []
    scan_status = _empty_scan_status()
    invalid_files = 0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if scan_status["scanned_entries"] >= MAX_TRACE_SCAN_ENTRIES:
                    scan_status["scan_truncated"] = True
                    break
                scan_status["scanned_entries"] += 1
                if not entry.name.startswith("trace_") or not entry.name.endswith(".json"):
                    continue
                try:
                    metadata = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & getattr(
                        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
                    ):
                        raise ValueError("trace is not a regular file")
                    candidates.append((metadata.st_mtime_ns, entry.name, Path(entry.path)))
                except (OSError, ValueError):
                    invalid_files += 1
                    scan_status["scan_errors"] += 1
    except OSError:
        scan_status["scan_errors"] += 1
        scan_status["scan_truncated"] = True
    scan_status["candidate_files"] = len(candidates)
    scan_status["unread_candidate_files"] = max(0, len(candidates) - limit)
    return [item[2] for item in sorted(candidates, reverse=True)[:limit]], scan_status, invalid_files


def _empty_scan_status():
    return {
        "scanned_entries": 0,
        "scan_limit": MAX_TRACE_SCAN_ENTRIES,
        "scan_truncated": False,
        "scan_errors": 0,
        "candidate_files": 0,
        "files_read": 0,
        # This count covers discovered files only. When scan_truncated is true,
        # the number of additional files outside the sample is unknown.
        "unread_candidate_files": 0,
    }


def _safe_metrics(metrics):
    if not isinstance(metrics, dict):
        raise TracePrivacyError("Trace metrics must be an object.")
    result = {}
    for key, value in metrics.items():
        if key in _BOOLEAN_METRICS:
            if not isinstance(value, bool):
                raise TracePrivacyError(f"Trace metric {key} must be boolean.")
            result[key] = value
        elif key in _INTEGER_METRICS:
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000_000:
                raise TracePrivacyError(f"Trace metric {key} must be a bounded non-negative integer.")
            result[key] = value
        elif key in _RATE_METRICS:
            if value is None:
                result[key] = None
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TracePrivacyError(f"Trace metric {key} must be a finite rate.")
            elif not 0 <= value <= 1:
                raise TracePrivacyError(f"Trace metric {key} must be between zero and one.")
            else:
                result[key] = round(float(value), 4)
        elif key in _STRING_METRICS:
            text = str(value or "")
            if not _STRING_METRICS[key].fullmatch(text):
                raise TracePrivacyError(f"Trace metric {key} contains an unsupported value.")
            result[key] = text
        else:
            raise TracePrivacyError(f"Trace metric {key} is not allowlisted for storage.")
    return result


def _safe_error_code(value):
    if isinstance(value, str):
        candidate = value.strip().lower()
    else:
        candidate = re.sub(r"(?<!^)(?=[A-Z])", "_", value.__class__.__name__).lower()
        explicit = getattr(value, "code", None)
        if explicit:
            candidate = str(explicit).strip().lower()
    candidate = re.sub(r"[^a-z0-9_]+", "_", candidate).strip("_")[:64]
    return candidate if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", candidate) else "runtime_error"


def _trace_enabled():
    return os.environ.get("BUSHFIRE_TRACE_ENABLED", "true").strip().lower() not in {"false", "0", "no"}


def _trace_dir():
    configured = os.environ.get("BUSHFIRE_TRACE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.environ.get("BUSHFIRE_RUNTIME_DIR", "").strip():
        return runtime_path("traces")
    return DEFAULT_TRACE_DIR.resolve()


def _valid_trace_record(record):
    if not isinstance(record, dict) or record.get("schema") != TRACE_SCHEMA:
        return False
    if set(record) != {
        "schema",
        "trace_id",
        "operation",
        "started_at_utc",
        "completed_at_utc",
        "status",
        "error_code",
        "duration_ms",
        "metrics",
        "stages",
        "privacy",
    }:
        return False
    if (
        not isinstance(record["operation"], str)
        or record["operation"] not in _OPERATIONS
        or not isinstance(record["status"], str)
        or record["status"] not in {"success", "failed", "cancelled"}
    ):
        return False
    if not isinstance(record["trace_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", record["trace_id"]):
        return False
    if not _valid_duration(record["duration_ms"]):
        return False
    if not _valid_timestamp(record["started_at_utc"]) or not _valid_timestamp(record["completed_at_utc"]):
        return False
    if not isinstance(record["metrics"], dict) or not isinstance(record["stages"], list) or len(record["stages"]) > 50:
        return False
    try:
        if _safe_metrics(record["metrics"]) != record["metrics"]:
            return False
        if not _valid_error_code(record["error_code"]):
            return False
        for stage in record["stages"]:
            if (
                not isinstance(stage, dict)
                or set(stage) != {"name", "status", "error_code", "duration_ms", "metrics"}
                or not isinstance(stage["name"], str)
                or stage["name"] not in _STAGES
            ):
                return False
            if not isinstance(stage["status"], str) or stage["status"] not in {"success", "error"}:
                return False
            if not _valid_duration(stage["duration_ms"]):
                return False
            if not _valid_error_code(stage["error_code"]):
                return False
            if _safe_metrics(stage["metrics"]) != stage["metrics"]:
                return False
    except TracePrivacyError:
        return False
    return (
        isinstance(record["privacy"], dict)
        and record["privacy"].get("content_stored") is False
        and set(record["privacy"]) == {"content_stored", "excluded"}
        and record["privacy"].get("excluded") == _PRIVACY_EXCLUDED
    )


def _valid_error_code(value):
    return value is None or isinstance(value, str) and bool(_STRING_METRICS["error_code"].fullmatch(value))


def _valid_duration(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _valid_timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _empty_summary():
    return {
        "schema": TRACE_SCHEMA,
        **_empty_scan_status(),
        "traces": 0,
        "invalid_files": 0,
        "success_rate": None,
        "duration_ms": {"p50": None, "p95": None},
        "operations": {},
        "failure_codes": {},
        "stage_errors": {},
        "stage_duration_ms": {},
        "repair_rate": None,
        "grounding_review_rate": None,
        "recent": [],
    }


def _percentile(values, percentile):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 2)


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
