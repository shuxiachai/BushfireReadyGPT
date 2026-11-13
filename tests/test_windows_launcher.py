from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


_LAUNCHER_TRIPWIRE = """
import os
import sys
from pathlib import Path

root = Path(os.environ['LAUNCHER_TEST_REAL_ROOT']).resolve()
marker = Path(os.environ['LAUNCHER_TEST_TRIPWIRE'])
protected = (root / '.venv', root / 'chat_history', root / 'data_australia')

def stop(reason):
    marker.write_text(reason, encoding='utf-8')
    os.write(2, ('Launcher test blocked ' + reason + '\\n').encode())
    os._exit(86)

arguments = sys.orig_argv
if '-m' in arguments:
    position = arguments.index('-m')
    module, options = arguments[position + 1], arguments[position + 2:]
    if module == 'poetry' or (module == 'pip' and options != ['check']):
        stop('installer invocation')

def audit(event, arguments):
    if event == 'open':
        value, mode, flags = arguments
        if not isinstance(value, (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(value)).resolve()
        if path == root / '.env' or path == protected[1] or protected[1] in path.parents:
            stop('real configuration or state access')
        writes = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        if writes and any(path == item or item in path.parents for item in protected):
            stop('real workstation write')
    elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.chmod', 'os.utime'}:
        paths = arguments[:2] if event == 'os.rename' else arguments[:1]
        for value in paths:
            if not isinstance(value, (str, bytes, os.PathLike)):
                continue
            path = Path(os.fsdecode(value)).resolve()
            if path == root / '.env' or any(path == item or item in path.parents for item in protected):
                stop('real workstation mutation')

sys.addaudithook(audit)
"""


@pytest.fixture
def isolated_launcher(tmp_path):
    """Exercise the unchanged launcher against disposable configuration and state."""
    project = tmp_path / "launcher-project"
    project.mkdir()
    tracked = (
        subprocess.run(
            ["git", "ls-files", "-z", "--", "src", "scripts"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=True,
        )
        .stdout.decode("utf-8")
        .split("\0")
    )
    required = ["start_app.ps1", "Start BushfireReadyGPT.bat", "poetry.lock", "Modelfile", "pyproject.toml"]
    copied = []
    for name in [*required, *filter(None, tracked)]:
        relative = Path(name)
        if any(part in {".git", ".venv", "__pycache__", "api_keys"} for part in relative.parts):
            continue
        if relative.name.startswith(".env") or relative.suffix == ".pyc":
            continue
        assert not relative.is_absolute() and ".." not in relative.parts
        source, target = PROJECT_ROOT / relative, project / relative
        assert not source.is_symlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert source.read_bytes() == target.read_bytes()
        copied.append(relative)
    assert all(Path(name) in copied for name in required)
    assert Path("src/wildfireChat.py") in copied

    synthetic_env = "LLM_PROVIDER=ollama\nOLLAMA_MODEL=launcher-test-model\nBUSHFIRE_RAG_ENABLED=false\n"
    (project / ".env").write_text(synthetic_env, encoding="utf-8")
    profile = tmp_path / "launcher-profile"
    for path in (profile, profile / "AppData" / "Local", profile / "AppData" / "Roaming", profile / "temp"):
        path.mkdir(parents=True, exist_ok=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("BUSHFIRE_", "OLLAMA_", "OPENAI_", "OPENROUTER_", "DEEPSEEK_", "RAILWAY_", "STREAMLIT_"))
        and key not in {"LLM_PROVIDER", "PYTHONPATH", "PYTHONHOME"}
    }
    environment.update(
        PYTHON_DOTENV_DISABLED="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        BUSHFIRE_DATA_DIR=str(PROJECT_ROOT / "data_australia"),
        BUSHFIRE_RAG_ENABLED="false",
        STREAMLIT_BROWSER_GATHER_USAGE_STATS="false",
        USERPROFILE=str(profile),
        LOCALAPPDATA=str(profile / "AppData" / "Local"),
        APPDATA=str(profile / "AppData" / "Roaming"),
        TEMP=str(profile / "temp"),
        TMP=str(profile / "temp"),
        PIP_CACHE_DIR=str(profile / "pip-cache"),
        HF_HOME=str(profile / "hf-cache"),
        XDG_CACHE_HOME=str(profile / "cache"),
    )
    subprocess.run(
        [sys.executable, "-B", "-m", "venv", "--without-pip", "--copies", str(project / ".venv")],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    python = project / ".venv" / "Scripts" / "python.exe"
    assert python.is_file() and not python.is_symlink()
    guard = tmp_path / "launcher-tripwire"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(_LAUNCHER_TRIPWIRE, encoding="utf-8")
    marker = guard / "blocked.txt"
    ollama_tripwire = guard / "ollama.cmd"
    ollama_tripwire.write_text(
        '@echo off\necho real model service invocation> "%LAUNCHER_TEST_TRIPWIRE%"\nexit /b 86\n',
        encoding="ascii",
    )
    environment.update(
        PYTHONPATH=os.pathsep.join((str(guard), sysconfig.get_path("purelib"))),
        PATH=str(guard) + os.pathsep + environment.get("PATH", ""),
        LAUNCHER_TEST_REAL_ROOT=str(PROJECT_ROOT),
        LAUNCHER_TEST_TRIPWIRE=str(marker),
    )
    # Harmless negative controls prove the guard runs before either installer.
    for command in (("pip", "install", "--help"), ("poetry", "--version")):
        result = subprocess.run(
            [str(python), "-B", "-m", *command], cwd=project, env=environment, capture_output=True, timeout=15
        )
        assert result.returncode == 86 and marker.read_text(encoding="utf-8") == "installer invocation"
        marker.unlink()
    resolution = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-Command ollama -ErrorAction Stop).Source))",
        ],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert Path(base64.b64decode(resolution.stdout.strip()).decode("utf-8")).resolve() == ollama_tripwire
    control = subprocess.run(
        ["cmd.exe", "/d", "/c", str(ollama_tripwire), "--version"],
        cwd=project,
        env=environment,
        capture_output=True,
        timeout=15,
    )
    assert control.returncode == 86 and marker.read_text(encoding="utf-8").strip() == "real model service invocation"
    marker.unlink()
    provenance = subprocess.run(
        [
            str(python),
            "-B",
            "-c",
            "import json,sys; from src.data_paths import PROJECT_ROOT; "
            "print(json.dumps({'root':str(PROJECT_ROOT),'prefix':sys.prefix}))",
        ],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    provenance = json.loads(provenance.stdout)
    assert Path(provenance["root"]) == project and Path(provenance["prefix"]) == project / ".venv"
    yield SimpleNamespace(root=project, python=python, environment=environment)
    assert not marker.exists(), "The launcher attempted an installer or access to protected workstation files."
    assert (project / ".env").read_text(encoding="utf-8") == synthetic_env
    for name in required:
        assert (PROJECT_ROOT / name).read_bytes() == (project / name).read_bytes()


@pytest.mark.skipif(os.name != "nt", reason="Tests owned Windows job cleanup.")
def test_launcher_supervisor_kills_owned_descendants_on_timeout(isolated_launcher, tmp_path):
    from tests.support.windows_launcher_job import kernel32, owned_process

    pid_file = tmp_path / "owned-child.pid"
    script = (
        "import pathlib, subprocess, sys; "
        "child=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='ascii'); child.wait()"
    )
    api, child = kernel32(), None
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            with owned_process(
                [str(isolated_launcher.python), "-B", "-c", script, str(pid_file)],
                python=isolated_launcher.python,
                cwd=isolated_launcher.root,
                env=isolated_launcher.environment,
            ) as process:
                deadline = time.monotonic() + 15
                while not pid_file.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert pid_file.is_file(), "The owned cleanup-control child did not start."
                # Hold the exact process object, never a possibly reused PID.
                child = api.OpenProcess(0x00100001, False, int(pid_file.read_text(encoding="ascii")))
                assert child
                process.communicate(timeout=0.1)
        assert api.WaitForSingleObject(child, 10_000) == 0
    finally:
        if child:
            try:
                if api.WaitForSingleObject(child, 0) != 0:
                    api.TerminateProcess(child, 86)
                    api.WaitForSingleObject(child, 10_000)
            finally:
                api.CloseHandle(child)


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
def test_batch_launcher_preflight_executes_the_user_facing_entrypoint(isolated_launcher):
    from tests.support.windows_launcher_job import run_owned

    result = run_owned(
        [
            "cmd.exe",
            "/d",
            "/c",
            str(isolated_launcher.root / "Start BushfireReadyGPT.bat"),
            "--preflight",
        ],
        python=isolated_launcher.python,
        cwd=isolated_launcher.root,
        env=isolated_launcher.environment,
        timeout=90,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "BushfireReadyGPT launcher preflight passed" in output
    assert "Python dependencies are ready; installation skipped." in output
    assert (isolated_launcher.root / "chat_history" / "bushfire_ready_setup_state.json").is_file()


@pytest.mark.skipif(os.name != "nt", reason="The production launcher is Windows PowerShell-specific.")
def test_windows_launcher_reaches_health_check_without_opening_browser(tmp_path, isolated_launcher):
    from tests.support.windows_launcher_job import run_owned

    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllamaHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    state_directory = tmp_path / "launcher-state"
    env = isolated_launcher.environment.copy()
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
        result = run_owned(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(isolated_launcher.root / "start_app.ps1"),
                "-PythonPath",
                str(isolated_launcher.python),
                "-NoBrowser",
                "-ExitAfterReady",
                "-RuntimeStateDirectory",
                str(state_directory),
            ],
            python=isolated_launcher.python,
            cwd=isolated_launcher.root,
            env=env,
            timeout=90,
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
