"""One guarded six-request execution of the fixed citation/criteria comparison.

Compose the existing raw-first recorder and cancellation/deadline implementation.
Never reopen the old campaign or change its globals. Only this campaign's fixed
claim can be created; it survives every outcome, including incomplete recording.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import secrets
import sys
from dataclasses import asdict, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import citation_criteria_comparison as preparation  # noqa: E402
from scripts import run_scoped_basis_comparison as engine  # noqa: E402

CAMPAIGN = preparation.CAMPAIGN
RunStopped = engine.RunStopped
_client = engine._client
_LIMIT_KEYS = ("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "BUSHFIRE_MODEL_MAX_CONCURRENT")


def _paths():
    directory = PROJECT_ROOT / "output" / CAMPAIGN
    output, claim = directory / "execution-v1", directory / "campaign.calls.jsonl"
    if directory.resolve() != PROJECT_ROOT.resolve() / "output" / CAMPAIGN or any(
        path.is_symlink() for path in (directory.parent, directory, output, claim)
    ):
        raise RunStopped("frozen_binding_failed")
    return directory, output, claim


def _load_bundle(expected):
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise RunStopped("frozen_binding_failed")
    try:
        return preparation.validate_prepared(expected)
    except Exception:
        raise RunStopped("frozen_binding_failed") from None


def _ready_usage(day, limits):
    from src.model_limits import read_model_usage

    usage = read_model_usage(day, limits=limits)
    if usage.get("status") != "ready" or type(usage.get("calls")) is not int or usage["calls"] < 0:
        raise RunStopped("quota_unavailable")
    if usage.get("day") != day:
        raise RunStopped("quota_day_changed")
    return usage


class QuotaOverlay:
    """Tighten disabled local limits in this process; never raise a positive cap."""

    def __init__(self):
        from src.model_limits import load_model_limits

        self.day = engine._today()
        self.original = load_model_limits()
        if self.original.cloud or self.original.database != PROJECT_ROOT.resolve() / "chat_history/model-usage.sqlite3":
            raise RunStopped("quota_configuration")
        usage = _ready_usage(self.day, self.original)
        self.start = usage["calls"]
        if self.original.daily_calls and self.original.daily_calls - self.start < 6:
            raise RunStopped("quota_configuration")
        self.effective = replace(self.original, daily_calls=self.start + 6, concurrency=1)
        self.previous = {key: os.environ.get(key) for key in _LIMIT_KEYS}
        self.values = dict(zip(_LIMIT_KEYS, (str(self.effective.daily_calls), "1")))
        self.active, self.keep_until_exit = False, False

    def apply(self):
        from src.model_limits import load_model_limits

        if (
            engine._today() != self.day
            or load_model_limits() != self.original
            or {key: os.environ.get(key) for key in _LIMIT_KEYS} != self.previous
        ):
            raise RunStopped("quota_configuration")
        if _ready_usage(self.day, self.original)["calls"] != self.start:
            raise RunStopped("quota_count_changed")
        os.environ.update(self.values)
        self.active = True

    def restore(self):
        # A timed-out worker may still reach allowance consumption. The dedicated
        # CLI must exit with its finite overlay intact, never restoring unlimited.
        if self.active and not self.keep_until_exit:
            for key, value in self.previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            self.active = False

    def snapshot(self):
        return {
            "utc_day": self.day,
            "starting_sqlite_count": self.start,
            "original_policy": {**asdict(self.original), "database": "project_default_model_usage_sqlite"},
            "effective_policy": {**asdict(self.effective), "database": "project_default_model_usage_sqlite"},
            "process_only_overlay": True,
            "count_interpretation": "SQLite counter, not complete request history while daily accounting was disabled.",
        }


class ExecutionGuard(engine.ExecutionGuard):
    """Reuse only identity collection; replace the old zero-based quota/packet guard."""

    def __init__(self, settings, bundle, expected, quota):
        self.settings = copy.deepcopy(settings)
        self.day, self.quota = quota.day, quota
        self.bundle, self.expected = bundle, expected
        self.packet = engine._json_bytes(bundle)
        self._credential = os.environ.get("DEEPSEEK_API_KEY", "")
        if not self._credential:
            raise RunStopped("environment_rejected")
        self.identity = self._identity()
        directory, _, _ = _paths()
        frozen = (directory / "prepared.json").read_bytes()
        if engine._sha(frozen) != expected or engine._json_bytes(json.loads(frozen)) != self.packet:
            raise RunStopped("frozen_binding_failed")
        recorded = bundle["source_identity"]
        actual = {**self.identity["sources"], **self.identity["new_experiment_files"]}
        if {path: digest for path, digest in actual.items() if path.startswith("src/")} != recorded[
            "current_python_source_sha256"
        ] or any(actual.get(path) != digest for path, digest in recorded["experiment_and_helper_sha256"].items()):
            raise RunStopped("source_drift")
        self.check(0)

    def _identity(self):
        identity = super()._identity()
        settings = identity["settings"]
        if (
            settings["timeout_seconds"] != 180
            or settings["top_p_submitted"] != 0.8
            or settings["thinking"] != "disabled"
            or settings["seed_sent"] is not False
        ):
            raise RunStopped("configuration_drift")
        identity["new_experiment_files"] = {
            path: engine._sha((PROJECT_ROOT / path).read_bytes()) for path in preparation.EXPERIMENT_FILES
        }
        return identity

    def check(self, expected_calls):
        from src.model_limits import load_model_limits

        if type(expected_calls) is not int or not 0 <= expected_calls <= 6:
            raise RunStopped("quota_count_changed")
        if not secrets.compare_digest(self._credential.encode(), os.environ.get("DEEPSEEK_API_KEY", "").encode()):
            raise RunStopped("credential_drift")
        if engine._today() != self.day:
            raise RunStopped("quota_day_changed")
        current = self._identity()
        for field, reason in (
            ("sources", "source_drift"),
            ("new_experiment_files", "source_drift"),
            ("dependencies", "dependency_drift"),
            ("settings", "configuration_drift"),
            ("effective", "configuration_drift"),
        ):
            if current[field] != self.identity[field]:
                raise RunStopped(reason)
        directory, _, _ = _paths()
        if (
            engine._sha((directory / "prepared.json").read_bytes()) != self.expected
            or engine._json_bytes(self.bundle) != self.packet
        ):
            raise RunStopped("frozen_binding_failed")
        limits = load_model_limits()
        if (
            limits != self.quota.effective
            or not self.quota.active
            or {key: os.environ.get(key) for key in _LIMIT_KEYS} != self.quota.values
        ):
            raise RunStopped("quota_configuration")
        usage = _ready_usage(self.day, limits)
        if usage["calls"] != self.quota.start + expected_calls:
            raise RunStopped("quota_count_changed")
        return {
            "day": self.day,
            "calls": usage["calls"],
            "starting_sqlite_count": self.quota.start,
            "campaign_allowances": expected_calls,
            "campaign_remaining": 6 - expected_calls,
            "remaining": limits.daily_calls - usage["calls"],
            "daily_limit": limits.daily_calls,
            "concurrency": 1,
        }


def execute(bundle, settings, guard, *, factory=None):
    """Admitted execution only; the CLI validates flags, bundle and policy first."""
    factory = factory or _client
    if engine._json_bytes(bundle) != guard.packet:
        raise RunStopped("frozen_binding_failed")
    guard.check(0)
    _, output, claim = _paths()
    try:
        handle = claim.open("xb")
    except FileExistsError:
        raise RunStopped("campaign_already_claimed") from None
    journal = engine.Journal(handle)
    state = engine.CampaignState(bundle, settings, guard, output, journal)
    quota_end = None
    try:
        output.mkdir(exist_ok=False)
        state.event(
            "campaign_claimed", prepared_file_sha256=guard.expected, planned_cells=state.rows, maximum_sdk_dispatches=6
        )
        state.artifact(
            "snapshot.json",
            {
                "prepared_file_sha256": guard.expected,
                "source_dependency_configuration": guard.identity,
                "quota_policy": guard.quota.snapshot(),
                "quota_initial": guard.check(0),
                "frozen_plan": bundle["execution_plan"],
                "rows": state.rows,
            },
        )
        for row in state.rows:
            if state.cancelled.is_set():
                row["reason"] = state.stop_reason
                continue
            engine._run_cell(state, row, factory)
            state.artifact(f"result-{row['sequence']:02}.json", copy.deepcopy(row))
            state.event("cell_finished", sequence=row["sequence"], status=row["status"], reason=row["reason"])
        quota_end = guard.check(state.allowances)
        state.event("campaign_finished", stop_reason=state.stop_reason, quota=quota_end)
    except (Exception, KeyboardInterrupt) as error:
        state.stop(engine._reason(error))
    finally:
        guard.quota.keep_until_exit = any(row["worker_pending"] for row in state.rows)
        if guard.quota.keep_until_exit:
            state.cancelled.set()
        try:
            journal.close()
        except Exception:
            state.stop("journal_close_failed", secondary=True)
    for row in state.rows:
        if row["status"] == "not_run":
            row["reason"] = state.stop_reason
    result = {
        "schema": "citation-criteria-execution-v1",
        "campaign": CAMPAIGN,
        "prepared_file_sha256": guard.expected,
        "rows": copy.deepcopy(state.rows),
        "stop_reason": state.stop_reason,
        "secondary_errors": list(state.secondary),
        "recording_incomplete": state.recording_incomplete,
        "quota_policy": guard.quota.snapshot(),
        "quota_end": quota_end,
        "sdk_dispatches_committed": sum(row["sdk_started"] for row in state.rows),
        "allowances_observed": state.allowances,
        "overlay_retained_until_cli_exit": guard.quota.keep_until_exit,
        "late_evidence_note": "Pending workers may add evidence only; stopped rows and results cannot become generated.",
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
    quota = None
    try:
        if not args.run_model or not args.allow_external_deepseek:
            raise RunStopped("flags_required")
        bundle = _load_bundle(args.expected_prepared_file_sha256)
        from scripts.evaluate_body_evidence_deepseek import admit_environment

        settings = admit_environment(run_model=True, allow_external_deepseek=True)
        # No config/runtime/SDK import until original policy and ready usage were
        # admitted and the finite process-only overlay has been applied.
        quota = QuotaOverlay()
        quota.apply()
        guard = ExecutionGuard(settings, bundle, args.expected_prepared_file_sha256, quota)
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
                        "overlay_retained_until_cli_exit",
                    )
                }
            )
        )
        return 2 if result["stop_reason"] or result["recording_incomplete"] else 0
    except (Exception, KeyboardInterrupt) as error:
        code = error.code if isinstance(error, RunStopped) else "environment_rejected"
        print(json.dumps({"status": "stopped", "reason": code, "no_automatic_retry": True}))
        return 2
    finally:
        if quota is not None:
            quota.restore()


if __name__ == "__main__":
    raise SystemExit(main())
