import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "src" / "wildfireChat.py"


def _available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _process_output(process):
    if process.stdout is None:
        return ""
    return process.stdout.read()


def _wait_for_health(process, health_url, timeout_seconds=30):
    deadline = time.monotonic() + timeout_seconds
    last_error = None

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Streamlit exited before becoming healthy.\n" + _process_output(process))

        try:
            with urlopen(health_url, timeout=1) as response:
                body = response.read().decode("utf-8", errors="replace").strip().lower()
                if response.status == 200 and body == "ok":
                    return
        except (URLError, TimeoutError, OSError) as error:
            last_error = error

        time.sleep(0.25)

    raise AssertionError(f"Streamlit health check timed out: {last_error}")


def test_streamlit_app_starts_and_responds_to_health_check():
    app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
    assert not app.exception, [str(exception) for exception in app.exception]

    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(APP_PATH),
            f"--server.port={port}",
            "--server.address=127.0.0.1",
            "--server.headless=true",
            "--server.fileWatcherType=none",
            "--browser.gatherUsageStats=false",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    try:
        _wait_for_health(process, f"{base_url}/_stcore/health")
        with urlopen(base_url, timeout=5) as response:
            page = response.read().decode("utf-8", errors="replace").lower()
        assert response.status == 200
        assert "streamlit" in page
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if process.stdout is not None:
            process.stdout.close()
