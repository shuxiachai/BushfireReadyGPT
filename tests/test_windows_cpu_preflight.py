"""The Windows CPU readiness probe must be offline and precede source downloads."""

import base64
import json
import os
import re
import subprocess
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import dotenv
import pytest

from src.data_paths import DataPaths
from src.rag import embeddings
from src.rag.settings import RagSettings

LAUNCHER = Path(__file__).resolve().parents[1] / "start_app.ps1"
_GUARD_CASES = [
    ("fastembed", True, False, False, 1, True),
    ("fastembed", True, False, True, 1, False),
    ("fastembed", False, False, False, 0, False),
    ("fastembed", True, True, False, 0, False),
    ("ollama", True, False, False, 0, False),
]
_GUARD_PHASES = [
    {"stage": "entered", "case_id": -1},
    {"stage": "parsed", "case_id": -1},
    {"stage": "order_verified", "case_id": -1},
    *[
        record
        for index in range(5)
        for record in ({"stage": "case_begin", "case_id": index}, {"stage": "case_end", "case_id": index})
    ],
    {"stage": "result_written", "case_id": -1},
    {"stage": "exit", "case_id": -1},
]


def _probe_source():
    source = LAUNCHER.read_text(encoding="utf-8")
    function = source.split("function Test-CpuEmbeddingPreflight {", 1)[1].split("function Open-AppBrowser", 1)[0]
    return re.search(r"\$check = @'\n(.*?)\n'@", function, flags=re.DOTALL).group(1)


@pytest.mark.parametrize(
    "state", ["prepared", "missing_package", "missing_identity", "changed_files", "wrong_provider"]
)
def test_cpu_probe_validates_existing_identity_without_network_or_writes(tmp_path, monkeypatch, capsys, state):
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_PROVIDER", "fastembed")
    monkeypatch.delenv("BUSHFIRE_RAG_EMBED_MODEL", raising=False)
    monkeypatch.setenv("BUSHFIRE_RAG_EMBED_CACHE_DIR", str(tmp_path / "models"))
    monkeypatch.setattr(embeddings, "version", lambda name: "fixture-runtime")
    settings = RagSettings.from_env(DataPaths.from_env(tmp_path))
    directory = embeddings._model_directory(settings)
    directory.mkdir(parents=True)
    for name in embeddings._MODEL_FILES:
        (directory / name).write_bytes(f"Synthetic model file: {name}".encode())
    identity = embeddings._model_identity(directory)
    (directory / "identity.json").write_text(json.dumps(identity), encoding="utf-8")

    if state == "missing_package":

        def missing_package(_name):
            raise PackageNotFoundError("synthetic-missing-cloud-dependency")

        monkeypatch.setattr(embeddings, "version", missing_package)
    elif state == "missing_identity":
        (directory / "identity.json").unlink()
    elif state == "changed_files":
        (directory / "tokenizer.json").write_bytes(b"Changed after preparation")
    elif state == "wrong_provider":
        settings = replace(settings, embedding_provider="ollama")

    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)
    monkeypatch.setattr(RagSettings, "from_env", lambda: settings)
    monkeypatch.setattr(embeddings.requests.sessions.Session, "request", lambda *a, **kw: pytest.fail("Network access"))
    monkeypatch.setattr(embeddings, "prepare_embedding_model", lambda *a: pytest.fail("Model download"))
    monkeypatch.setattr(embeddings.FastEmbedEmbeddingClient, "embed", lambda *a: pytest.fail("Model inference"))
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    if state == "prepared":
        exec(compile(_probe_source(), str(LAUNCHER), "exec"), {})
    else:
        with pytest.raises(SystemExit) as error:
            exec(compile(_probe_source(), str(LAUNCHER), "exec"), {})
        assert error.value.code == 1

    assert before == {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert capsys.readouterr() == ("", "")


def _guard_batch_script(directory):
    path = str(LAUNCHER).replace("'", "''")
    phase_path = str(directory / "phases.jsonl").replace("'", "''")
    result_path = str(directory / "results.json").replace("'", "''")
    # Only inputs reach PowerShell. Expected checks/errors remain Python assertions.
    cases = json.dumps(
        [
            {"case_id": index, "provider": provider, "enabled": enabled, "skip_rag": skip_rag, "ready": ready}
            for index, (provider, enabled, skip_rag, ready, _, _) in enumerate(_GUARD_CASES)
        ]
    )
    return rf"""
$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
function Write-Phase([string]$Stage, [int]$Case = -1) {{
    $line = '{{"stage":"' + $Stage + '","case_id":' + $Case + '}}' + "`n"
    [System.IO.File]::AppendAllText('{phase_path}', $line, $utf8)
}}
Write-Phase 'entered'
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$null, [ref]$null)
Write-Phase 'parsed'
$guard = $ast.Find({{
    param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text.Contains('Test-CpuEmbeddingPreflight -Python')
}}, $true)
$download = $ast.Find({{
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
    $node.GetCommandName() -eq 'Invoke-Checked' -and $node.Extent.Text.Contains('--download')
}}, $true)
if (-not $guard -or -not $download -or $guard.Extent.EndOffset -ge $download.Extent.StartOffset) {{
    throw 'CPU preflight must precede RAG source downloads.'
}}
Write-Phase 'order_verified'
$cases = ConvertFrom-Json @'
{cases}
'@
$results = @()
foreach ($case in $cases) {{
    Write-Phase 'case_begin' $case.case_id
    $observed = & {{
        param($case, [string]$guardText)
        # A new child scope and counter object for every case, including the stub.
        $ragProvider = $case.provider
        $ragEnabled = [bool]$case.enabled
        $skipRag = [bool]$case.skip_rag
        $virtualPython = 'unused-synthetic-python'
        $state = @{{ checks = 0; ready = [bool]$case.ready }}
        $failure = ''
        function Test-CpuEmbeddingPreflight {{
            param([string]$Python)
            $state.checks += 1
            return $state.ready
        }}
        try {{ Invoke-Expression $guardText }} catch {{ $failure = $_.Exception.Message }}
        @{{ case_id = [int]$case.case_id; checks = $state.checks; failure = $failure }}
    }} $case $guard.Extent.Text
    $results += $observed
    Write-Phase 'case_end' $case.case_id
}}
[System.IO.File]::WriteAllText('{result_path}', (ConvertTo-Json -InputObject $results -Compress), $utf8)
Write-Phase 'result_written'
Write-Phase 'exit'
exit 0
"""


def _bounded_read(path, limit, *, tail=False):
    try:
        with path.open("rb") as handle:
            if tail:
                handle.seek(max(0, path.stat().st_size - limit))
            return handle.read(limit)
    except FileNotFoundError:
        return b""


def _completed_phases(directory):
    content = _bounded_read(directory / "phases.jsonl", 4097)
    records = []
    for line in content.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break
        try:
            record = json.loads(line)
        except ValueError:
            break
        if len(records) >= len(_GUARD_PHASES) or record != _GUARD_PHASES[len(records)]:
            break
        records.append(record)
    return records


def _guard_diagnostics(directory):
    phases = _completed_phases(directory)
    phase = (
        f"Last complete phase: {phases[-1]} ({len(phases)} records)."
        if phases
        else ("No complete phase record persisted; failure stage unknown.")
    )
    tails = [
        f"{name}: {_bounded_read(directory / name, 2048, tail=True).decode('utf-8', errors='replace')!r}"
        for name in ("stdout.txt", "stderr.txt")
    ]
    return "\n".join([phase, *tails])


def _collect_guard_batch(directory):
    script = _guard_batch_script(directory)
    try:
        # File redirection avoids Windows communicate() PIPE-reader EOF waits.
        # This one unchanged deadline covers startup, AST parsing and all cases.
        with (directory / "stdout.txt").open("wb") as output, (directory / "stderr.txt").open("wb") as errors:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    base64.b64encode(script.encode("utf-16-le")).decode(),
                ],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=errors,
                timeout=20,
                check=False,
            )
    except subprocess.TimeoutExpired:
        pytest.fail("PowerShell guard batch exceeded 20 seconds.\n" + _guard_diagnostics(directory), pytrace=False)
    assert result.returncode == 0, _guard_diagnostics(directory)
    expected_phases = "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in _GUARD_PHASES).encode()
    assert _bounded_read(directory / "phases.jsonl", 4097) == expected_phases, _guard_diagnostics(directory)
    content = _bounded_read(directory / "results.json", 8193)
    assert len(content) <= 8192, "Guard result exceeded its bounded schema."
    try:
        observed = json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeError):
        pytest.fail("Missing or incomplete UTF-8 guard results.\n" + _guard_diagnostics(directory), pytrace=False)
    assert isinstance(observed, list) and len(observed) == len(_GUARD_CASES)
    assert all(
        isinstance(row, dict)
        and set(row) == {"case_id", "checks", "failure"}
        and type(row["case_id"]) is int
        and type(row["checks"]) is int
        and row["checks"] >= 0
        and isinstance(row["failure"], str)
        for row in observed
    ), "Invalid guard result schema."
    assert {row["case_id"] for row in observed} == set(range(len(_GUARD_CASES))), "Missing or duplicate case results."
    return {row["case_id"]: row for row in observed}


@pytest.fixture(scope="module")
def cpu_guard_results(tmp_path_factory):
    return _collect_guard_batch(tmp_path_factory.mktemp("windows-cpu-guard"))


@pytest.mark.skipif(os.name != "nt", reason="Tests the Windows launcher guard in isolation.")
@pytest.mark.parametrize(
    ("provider", "enabled", "skip_rag", "ready", "expected_checks", "blocked"),
    _GUARD_CASES,
)
def test_cpu_guard_precedes_download_and_keeps_ollama_and_skipped_paths_unchanged(
    cpu_guard_results, provider, enabled, skip_rag, ready, expected_checks, blocked
):
    case_id = _GUARD_CASES.index((provider, enabled, skip_rag, ready, expected_checks, blocked))
    observed = cpu_guard_results[case_id]
    assert observed["checks"] == expected_checks
    assert bool(observed["failure"]) is blocked
    if blocked:
        assert "poetry install --with dev,cloud --no-root" in observed["failure"]
        assert "--prepare-embedding-only" in observed["failure"]
        assert "No model or source downloads were started" in observed["failure"]


def _synthetic_guard_output(directory, *, phases=None, rows=None):
    if phases is None:
        phases = _GUARD_PHASES
    if rows is None:
        rows = [{"case_id": index, "checks": 0, "failure": "Synthetic 记录"} for index in range(5)]
    (directory / "phases.jsonl").write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in phases), encoding="utf-8", newline="\n"
    )
    (directory / "results.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_guard_batch_runs_once_without_pipes_or_expected_answers(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand"]
        assert kwargs["timeout"] == 20 and kwargs["check"] is False and kwargs["stdin"] == subprocess.DEVNULL
        assert "capture_output" not in kwargs
        assert kwargs["stdout"].name == str(tmp_path / "stdout.txt")
        assert kwargs["stderr"].name == str(tmp_path / "stderr.txt")
        script = base64.b64decode(command[-1]).decode("utf-16-le")
        assert script.count("::ParseFile(") == 1 and "expected_checks" not in script and "blocked" not in script
        inputs = json.loads(script.split("$cases = ConvertFrom-Json @'\n", 1)[1].split("\n'@", 1)[0])
        assert len(inputs) == 5 and all(
            set(case) == {"case_id", "provider", "enabled", "skip_rag", "ready"} for case in inputs
        )
        assert [(case["provider"], case["enabled"], case["skip_rag"], case["ready"]) for case in inputs] == [
            case[:4] for case in _GUARD_CASES
        ]
        _synthetic_guard_output(tmp_path)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert len(_collect_guard_batch(tmp_path)) == 5
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure", ["partial", "duplicate", "bad_type", "bad_keys", "bad_json", "missing_phase", "extra_phase", "nonzero"]
)
def test_guard_batch_rejects_partial_malformed_or_unsuccessful_results(tmp_path, monkeypatch, failure):
    def run(command, **kwargs):
        rows = [{"case_id": index, "checks": 0, "failure": ""} for index in range(5)]
        phases = list(_GUARD_PHASES)
        if failure == "partial":
            rows.pop()
        elif failure == "duplicate":
            rows[-1]["case_id"] = 0
        elif failure == "bad_type":
            rows[0]["checks"] = True
        elif failure == "bad_keys":
            rows[0]["unexpected"] = "value"
        elif failure == "missing_phase":
            phases.pop()
        elif failure == "extra_phase":
            phases.append(phases[-1])
        _synthetic_guard_output(tmp_path, phases=phases, rows=rows)
        if failure == "bad_json":
            (tmp_path / "results.json").write_bytes(b'[{"case_id":')
        return subprocess.CompletedProcess(command, 1 if failure == "nonzero" else 0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _collect_guard_batch(tmp_path)


@pytest.mark.parametrize("has_phase", [False, True])
def test_guard_timeout_reports_only_last_complete_phase_and_bounded_tails(tmp_path, monkeypatch, has_phase):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if has_phase:
            _synthetic_guard_output(tmp_path, phases=_GUARD_PHASES[:4])
            with (tmp_path / "phases.jsonl").open("ab") as handle:
                handle.write(b'{"stage":"case_end"')
        kwargs["stdout"].write(b"old-output-not-in-tail" + b"x" * 4096 + b"tail-marker")
        raise subprocess.TimeoutExpired(command, 20)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(pytest.fail.Exception) as error:
        _collect_guard_batch(tmp_path)
    message = str(error.value)
    assert "exceeded 20 seconds" in message and "tail-marker" in message
    assert "old-output-not-in-tail" not in message and len(message) < 4500
    if has_phase:
        assert "'stage': 'case_begin', 'case_id': 0" in message and "case_end" not in message
    else:
        assert "No complete phase record persisted; failure stage unknown." in message
    assert len(calls) == 1
