from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt", reason="Tests the production PowerShell expression in isolation.")
@pytest.mark.parametrize(
    ("provider", "rag_provider", "rag_enabled", "preflight", "needs_ollama", "needs_rag_ollama", "default_model"),
    [
        ("deepseek", "fastembed", True, False, False, False, "BAAI/bge-small-en-v1.5"),
        ("ollama", "fastembed", True, False, True, False, "BAAI/bge-small-en-v1.5"),
        ("deepseek", "ollama", True, False, True, True, "embeddinggemma"),
        ("deepseek", "ollama", False, False, False, False, "embeddinggemma"),
        ("ollama", "ollama", True, True, False, False, "embeddinggemma"),
    ],
)
def test_launcher_only_requires_ollama_for_features_using_ollama(
    provider, rag_provider, rag_enabled, preflight, needs_ollama, needs_rag_ollama, default_model
):
    # Evaluate only the model-selection block and the embedding-pull condition.
    # Do not execute the launcher, read .env, start services, or download models.
    path = str(PROJECT_ROOT / "start_app.ps1").replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$null, [ref]$null)
$provider = '{provider}'
$testRagProvider = '{rag_provider}'
$ragEnabled = ${str(rag_enabled).lower()}
$skipModels = ${str(preflight).lower()}
$skipRag = ${str(preflight).lower()}
function Get-DotEnvValue {{
    param([string]$Name, [string]$DefaultValue)
    if ($Name -eq 'BUSHFIRE_RAG_EMBED_PROVIDER') {{ return $testRagProvider }}
    return $DefaultValue
}}
$first = $ast.Find({{
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq '$ragProvider'
}}, $true)
$last = $ast.Find({{
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq '$needsOllama'
}}, $true)
if (-not $first -or -not $last) {{ throw 'The embedding provider selection block is missing.' }}
$selection = $ast.Extent.Text.Substring($first.Extent.StartOffset, $last.Extent.EndOffset - $first.Extent.StartOffset)
Invoke-Expression $selection
$pull = $ast.Find({{
    param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text.Contains('Downloading the missing RAG embedding model:')
}}, $true)
if (-not $pull) {{ throw 'The embedding download guard is missing.' }}
$allowsPull = Invoke-Expression $pull.Clauses[0].Item1.Extent.Text
@{{ needs_ollama=$needsOllama; needs_rag_ollama=$needsRagOllama; default_model=$ragModel; allows_pull=$allowsPull }} | ConvertTo-Json -Compress
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
    assert json.loads(result.stdout) == {
        "needs_ollama": needs_ollama,
        "needs_rag_ollama": needs_rag_ollama,
        "default_model": default_model,
        "allows_pull": needs_rag_ollama and not preflight,
    }


class _FakeOllamaHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/api/tags":
            self.send_error(404)
            return

        body = json.dumps({"models": [{"name": "launcher-test-model:latest"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


@pytest.mark.skipif(os.name != "nt", reason="The production launcher is Windows-specific.")
def test_batch_launcher_preflight_executes_the_user_facing_entrypoint():
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(PROJECT_ROOT / "Start BushfireReadyGPT.bat"), "--preflight"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "BushfireReadyGPT launcher preflight passed" in output


@pytest.mark.skipif(os.name != "nt", reason="The production launcher is Windows PowerShell-specific.")
def test_windows_launcher_reaches_health_check_without_opening_browser(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllamaHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    state_directory = tmp_path / "launcher-state"
    env = os.environ.copy()
    env.update(
        {
            "BUSHFIRE_RAG_ENABLED": "false",
            "LLM_PROVIDER": "ollama",
            "OLLAMA_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
            "OLLAMA_MODEL": "launcher-test-model",
            "PYTHONUTF8": "1",
        }
    )

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PROJECT_ROOT / "start_app.ps1"),
                "-PythonPath",
                sys.executable,
                "-NoBrowser",
                "-ExitAfterReady",
                "-RuntimeStateDirectory",
                str(state_directory),
            ],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Python dependencies are ready; installation skipped." in output
    assert "Ollama is ready" in output
    assert "Browser launch skipped" in output
    assert "Streamlit readiness check passed" in output
    assert (state_directory / "bushfire_ready_setup_state.json").is_file()
    assert not (state_directory / "bushfire_ready_port.txt").exists()
