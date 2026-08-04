import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from zipfile import ZipFile

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "src" / "wildfireChat.py"
ARTIFACT_DIR = PROJECT_ROOT / "output" / "playwright"
RUNTIME_DIR = PROJECT_ROOT / "chat_history" / "e2e_runtime"

MOCK_REPORT = """# Cairns Council Bushfire Preparedness Draft

## Executive Summary
This draft supports council community preparedness planning and requires human review.

## Location and Assumptions
The planning area is Cairns, Queensland. Local arrangements must be verified by the responsible organisation.

## Evacuation and Candidate Assembly Points
Confirm evacuation arrangements and candidate assembly points with council partners and official emergency services.

## Roles, Communication and First Aid Training
Assign responsible officers, maintain contact lists and schedule first aid training with local partners.

## This-Month Action Plan
- [ ] Confirm official information sources.
- [ ] Review evacuation arrangements.
- [ ] Record the responsible reviewer.

## Safety Boundary
This report is not live emergency advice. Follow official emergency services and call 000 if life is at risk.
"""


class MockModelHandler(BaseHTTPRequestHandler):
    request_count = 0
    official_request_count = 0

    def do_HEAD(self):
        if self.path != "/official/healthy":
            self.send_error(404)
            return
        type(self).official_request_count += 1
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        type(self).request_count += 1

        chunks = [
            {
                "id": "chatcmpl-browser-e2e",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "e2e-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": MOCK_REPORT},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl-browser-e2e",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "e2e-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        body += "data: [DONE]\n\n"
        payload = body.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format, *_args):
        return


def _available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait_for_health(process, health_url, timeout_seconds=45):
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Streamlit exited before the browser test could start.")
        try:
            with urlopen(health_url, timeout=1) as response:
                if response.status == 200 and response.read().decode("utf-8").strip().lower() == "ok":
                    return
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
        time.sleep(0.25)
    raise AssertionError(f"Streamlit health check timed out: {last_error}")


def _stop_process(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _write_map_fixture():
    profile_path = RUNTIME_DIR / "sa2_profiles_all.csv"
    profile_path.write_text(
        "state_name,sa4_name,sa3_name,sa2_name,population,older_people_count,"
        "language_other_than_english_count,language_support_needed\n"
        "Queensland,Cairns,Cairns - North,Cairns City,171000,25650,34200,high\n"
        "Queensland,Brisbane - East,Brisbane East,Bayside,205000,28700,41000,high\n",
        encoding="utf-8",
    )
    boundary_path = RUNTIME_DIR / "sa2_boundaries_all.geojson"
    features = [
        {
            "type": "Feature",
            "properties": {
                "state_name_2021": "Queensland",
                "sa4_name_2021": "Cairns",
                "sa3_name_2021": "Cairns - North",
                "sa2_name_2021": "Cairns City",
                "population": "171000",
                "language_support_needed": "high",
                "fill_color": [31, 157, 138, 150],
                "line_color": [12, 74, 110, 220],
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [145.7, -17.0],
                        [145.9, -17.0],
                        [145.9, -16.8],
                        [145.7, -16.8],
                        [145.7, -17.0],
                    ]
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {
                "state_name_2021": "Queensland",
                "sa4_name_2021": "Brisbane - East",
                "sa3_name_2021": "Brisbane East",
                "sa2_name_2021": "Bayside",
                "population": "205000",
                "language_support_needed": "high",
                "fill_color": [255, 127, 14, 150],
                "line_color": [12, 74, 110, 220],
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [153.0, -27.6],
                        [153.2, -27.6],
                        [153.2, -27.4],
                        [153.0, -27.4],
                        [153.0, -27.6],
                    ]
                ],
            },
        },
    ]
    boundary_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )
    return profile_path, boundary_path


def _write_official_sources_fixture(server_port):
    path = RUNTIME_DIR / "official_sources.yml"
    path.write_text(
        "sources:\n"
        "  - id: mock_qld_source\n"
        "    name: Mock Queensland Official Source\n"
        f"    url: http://127.0.0.1:{server_port}/official/healthy\n"
        "    scope: [australia, queensland]\n"
        "    purpose: Controlled entry-point reachability test.\n"
        "    use_when: Browser E2E verification only.\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.e2e
def test_browser_report_data_map_and_human_signoff_workflow():
    from playwright.sync_api import expect, sync_playwright

    shutil.rmtree(ARTIFACT_DIR, ignore_errors=True)
    shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    MockModelHandler.request_count = 0
    MockModelHandler.official_request_count = 0
    model_server = ThreadingHTTPServer(("127.0.0.1", 0), MockModelHandler)
    model_thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    model_thread.start()
    map_profile_path, map_boundary_path = _write_map_fixture()
    official_sources_path = _write_official_sources_fixture(model_server.server_port)

    app_port = _available_port()
    app_url = f"http://127.0.0.1:{app_port}"
    env = os.environ.copy()
    env.update(
        {
            "LLM_PROVIDER": "ollama",
            "OLLAMA_BASE_URL": f"http://127.0.0.1:{model_server.server_port}/v1",
            "OLLAMA_MODEL": "e2e-model",
            "BUSHFIRE_SESSION_STATE_PATH": str(RUNTIME_DIR / "session_state.pkl"),
            "BUSHFIRE_INTERACTION_LOG_PATH": str(RUNTIME_DIR / "interaction.jsonl"),
            "BUSHFIRE_AUDIT_DIR": str(RUNTIME_DIR / "audit"),
            "BUSHFIRE_ALL_SA2_PROFILE_PATH": str(map_profile_path),
            "BUSHFIRE_ALL_SA2_BOUNDARY_PATH": str(map_boundary_path),
            "BUSHFIRE_ALL_SA2_BOUNDARY_BY_STATE_DIR": str(RUNTIME_DIR / "boundaries_by_state"),
            "BUSHFIRE_OFFICIAL_SOURCES_PATH": str(official_sources_path),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        }
    )

    log_path = ARTIFACT_DIR / "streamlit.log"
    log_file = open(log_path, "w", encoding="utf-8")
    app_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(APP_PATH),
            f"--server.port={app_port}",
            "--server.address=127.0.0.1",
            "--server.headless=true",
            "--server.fileWatcherType=none",
            "--browser.gatherUsageStats=false",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    workflow_completed = False
    page = None
    try:
        _wait_for_health(app_process, f"{app_url}/_stcore/health")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            try:
                page = context.new_page()
                page.goto(app_url, wait_until="domcontentloaded", timeout=60_000)
                expect(
                    page.get_by_role("heading", name="BushfireReadyGPT Command Workspace", exact=True)
                ).to_be_visible(timeout=30_000)

                page.get_by_role("button", name="Load example", exact=True).click()
                expect(page.get_by_label("Location", exact=True)).to_have_value("Cairns, Queensland")
                expect(page.get_by_label("Audience", exact=True)).to_have_value(
                    "Council community resilience officers, school safety leads, and local service partners"
                )

                page.get_by_role("button", name="Generate report", exact=True).click()
                expect(
                    page.get_by_role("heading", name="Latest Report Preview", exact=True)
                ).to_be_visible(timeout=60_000)
                expect(
                    page.get_by_role("heading", name="Cairns Council Bushfire Preparedness Draft", exact=True).first
                ).to_be_visible()

                with page.expect_download(timeout=30_000) as markdown_download_info:
                    page.get_by_role("button", name="Download Markdown", exact=True).click()
                markdown_download = markdown_download_info.value
                assert markdown_download.suggested_filename == "bushfire_ready_report.md"
                assert "Cairns Council Bushfire Preparedness Draft" in Path(markdown_download.path()).read_text(
                    encoding="utf-8"
                )

                page.get_by_role("tab", name="Review & Export", exact=True).click()
                review_panel = page.get_by_label("Review & Export")
                review_panel.get_by_text("Evidence Trail", exact=True).click()
                expect(
                    page.get_by_role(
                        "heading",
                        name="Evidence Confidence and Provenance",
                        exact=True,
                    ).last
                ).to_be_visible()
                reviewer_name = page.get_by_label("Reviewer name", exact=True).last
                reviewer_name.fill("Browser E2E Reviewer")
                page.get_by_label("Reviewer role / title", exact=True).fill("School safety reviewer")
                page.get_by_label("Organisation / department", exact=True).last.fill("Cairns Campus Pilot")
                page.get_by_label("Review notes", exact=True).fill("Reviewed through the automated browser workflow.")
                page.get_by_role("button", name="Update sign-off record", exact=True).click()

                expect(page.get_by_text("Sign-off section updated in the latest report.", exact=True)).to_be_visible()
                expect(page.get_by_text("Latest audit JSON updated.", exact=True)).to_be_visible()

                with page.expect_download(timeout=30_000) as package_download_info:
                    page.get_by_role("button", name="Download pilot export package", exact=True).click()
                package_download = package_download_info.value
                with ZipFile(package_download.path()) as package:
                    names = set(package.namelist())
                    audit_payload = json.loads(package.read("governance/audit_record.json"))
                assert "governance/package_manifest.json" in names
                assert "governance/audit_record.json" in names
                assert any(name.endswith(".md") for name in names)
                assert {
                    row["code"]
                    for row in audit_payload["analysis"]["evidence_confidence"]
                } == {"O1", "P2", "R3", "A4", "U0"}
                assert MockModelHandler.request_count == 1

                page.get_by_role("tab", name="Data & Map", exact=True).click()
                expect(
                    page.get_by_text(
                        "Current map selection: Queensland / SA4 / Cairns",
                        exact=True,
                    )
                ).to_be_visible(
                    timeout=30_000,
                )
                search_area = page.get_by_label("Search area", exact=True)
                search_area.fill("Brisbane")
                search_area.press("Enter")
                expect(
                    page.get_by_text(
                        "Current map selection: Queensland / SA4 / Brisbane - East",
                        exact=True,
                    )
                ).to_be_visible(timeout=30_000)

                expect(page.get_by_text("Mock Queensland Official Source", exact=True)).to_be_visible()
                page.get_by_role("button", name="Check official source status", exact=True).click()
                reachable_card = page.locator(".status-card").filter(has_text="Reachable")
                expect(reachable_card).to_contain_text("1", timeout=30_000)
                assert MockModelHandler.official_request_count == 1

                active_data_card = page.locator(".status-card").filter(has_text="Active data")
                expect(active_data_card).to_contain_text("ABS processed data")
                workflow_completed = True
            except Exception:
                if page is not None:
                    page.screenshot(path=str(ARTIFACT_DIR / "failure.png"), full_page=True)
                raise
            finally:
                context.close()
                browser.close()
    finally:
        _stop_process(app_process)
        log_file.close()
        model_server.shutdown()
        model_server.server_close()
        model_thread.join(timeout=5)
        shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
        if workflow_completed:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            assert "StreamlitAPIException" not in log_text
            assert "was created with a default value but also had its value set" not in log_text
            shutil.rmtree(ARTIFACT_DIR, ignore_errors=True)
