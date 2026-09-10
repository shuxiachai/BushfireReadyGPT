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


@pytest.mark.skipif(os.name != "nt", reason="Tests the Windows launcher guard in isolation.")
@pytest.mark.parametrize(
    ("provider", "enabled", "skip_rag", "ready", "expected_checks", "blocked"),
    [
        ("fastembed", True, False, False, 1, True),
        ("fastembed", True, False, True, 1, False),
        ("fastembed", False, False, False, 0, False),
        ("fastembed", True, True, False, 0, False),
        ("ollama", True, False, False, 0, False),
    ],
)
def test_cpu_guard_precedes_download_and_keeps_ollama_and_skipped_paths_unchanged(
    provider, enabled, skip_rag, ready, expected_checks, blocked
):
    path = str(LAUNCHER).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$null, [ref]$null)
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
$ragProvider = '{provider}'
$ragEnabled = ${str(enabled).lower()}
$skipRag = ${str(skip_rag).lower()}
$virtualPython = 'unused-synthetic-python'
$script:checks = 0
function Test-CpuEmbeddingPreflight {{
    param([string]$Python)
    $script:checks += 1
    return ${str(ready).lower()}
}}
$failure = ''
try {{ Invoke-Expression $guard.Extent.Text }} catch {{ $failure = $_.Exception.Message }}
@{{ checks=$script:checks; failure=$failure }} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed["checks"] == expected_checks
    assert bool(observed["failure"]) is blocked
    if blocked:
        assert "poetry install --with dev,cloud --no-root" in observed["failure"]
        assert "--prepare-embedding-only" in observed["failure"]
        assert "No model or source downloads were started" in observed["failure"]
