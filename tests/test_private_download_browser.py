"""Real-browser regression for authenticated delivery without public media files."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_browser_e2e import _available_port, _stop_process, _wait_for_health

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_PASSWORD = "Synthetic-download-test-2026"
PAYLOAD = 'Synthetic private export: 中文 </script><script>fetch("/leak")</script>\n'.encode()


@pytest.mark.e2e
def test_private_downloads_are_browser_local_and_session_isolated(tmp_path):
    from playwright.sync_api import expect, sync_playwright
    from streamlit.runtime.memory_media_file_storage import _calculate_file_id, get_extension_for_mimetype

    url = f"http://127.0.0.1:{_available_port()}"
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("BUSHFIRE_", "RAILWAY_", "DEEPSEEK_", "OPENAI_"))
    }
    environment.update(
        {
            "BUSHFIRE_DEPLOYMENT_MODE": "cloud",
            "BUSHFIRE_RUNTIME_DIR": str(tmp_path / "runtime"),
            "BUSHFIRE_ACCESS_PASSWORD": TEST_PASSWORD,
            "PYTHONPATH": str(PROJECT_ROOT),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    with (tmp_path / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(PROJECT_ROOT / "tests/fixtures/private_download_app.py"),
                "--server.address=127.0.0.1",
                f"--server.port={url.rsplit(':', 1)[1]}",
                "--server.headless=true",
                "--server.fileWatcherType=none",
                "--browser.gatherUsageStats=false",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_health(process, f"{url}/_stcore/health")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    owner = browser.new_context(accept_downloads=True)
                    other = browser.new_context(accept_downloads=True)
                    page = owner.new_page()
                    requests = []
                    page.on("request", lambda request: requests.append(request.url))
                    page.goto(url)
                    expect(page.get_by_label("Access password")).to_be_visible()
                    expect(page.locator("iframe")).to_have_count(0)
                    page.get_by_label("Access password").fill(TEST_PASSWORD)
                    page.get_by_role("button", name="Sign in", exact=True).click()
                    expect(page.get_by_text("Authenticated export session", exact=True)).to_be_visible()
                    expect(page.locator("iframe")).to_have_count(6)

                    outsider = other.new_page()
                    outsider.goto(url)
                    expect(outsider.get_by_label("Access password")).to_be_visible()
                    expect(outsider.locator("iframe")).to_have_count(0)
                    for index, (label, filename, mime) in enumerate(
                        (
                            ("Download Markdown", "测试报告.md", "text/markdown"),
                            ("Download PDF", "report.pdf", "application/pdf"),
                            (
                                "Download DOCX",
                                "report.docx",
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            ),
                            ("Download ZIP", "report.zip", "application/zip"),
                            ("Download audit", "audit.json", "application/json"),
                            ("Download CSV", "register.csv", "text/csv"),
                        )
                    ):
                        frame = page.frame_locator("iframe").nth(index)
                        with page.expect_download() as event:
                            frame.get_by_role("button", name=label, exact=True).click()
                        download = event.value
                        assert download.suggested_filename == filename
                        assert download.url.startswith("blob:")
                        destination = tmp_path / filename
                        download.save_as(destination)
                        assert destination.read_bytes() == PAYLOAD
                        status = frame.get_by_role("status")
                        expect(status).to_contain_text("Download requested.")
                        expect(status).to_contain_text("If no file appears, retry in Chrome or Edge.")
                        expect(status).not_to_contain_text("saved")
                        expect(status).to_be_visible()
                        # Streamlit's content-sized iframe must grow with the feedback;
                        # a fixed 64px frame would clip the narrow-column message.
                        status_bounds = status.bounding_box()
                        iframe_bounds = page.locator("iframe").nth(index).bounding_box()
                        assert status_bounds and iframe_bounds
                        assert status_bounds["y"] + status_bounds["height"] <= (
                            iframe_bounds["y"] + iframe_bounds["height"] + 1
                        )
                        # Knowing the exact synthetic bytes/filename must not produce
                        # a retrievable file in Streamlit's unauthenticated media store.
                        file_id = _calculate_file_id(PAYLOAD, mime, filename)
                        suffix = get_extension_for_mimetype(mime)
                        response = other.request.get(f"{url}/media/{file_id}{suffix}")
                        assert response.status == 404
                    assert not any(request.startswith(f"{url}/media/") or "/leak" in request for request in requests)
                    page.get_by_role("button", name="End test session", exact=True).click()
                    expect(page.get_by_label("Access password")).to_be_visible()
                    expect(page.locator("iframe")).to_have_count(0)
                finally:
                    browser.close()
        finally:
            _stop_process(process)
