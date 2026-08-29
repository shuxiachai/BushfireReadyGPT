from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
