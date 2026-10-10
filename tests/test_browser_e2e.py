import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4
from zipfile import ZipFile

import pytest

from tests.support.report_fixtures import _valid_report, section_response_from_markdown

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "src" / "wildfireChat.py"
ARTIFACT_PARENT = PROJECT_ROOT / "output" / "playwright"

# Synthetic response for the exact Cairns Council pilot and map fixture below.
# No quality result is mocked: the offline preflight and UI use the current gate.
MOCK_REPORT_MARKDOWN = """# 1. Title

Cairns Council Bushfire Preparedness Draft

## 2. Executive Summary
This synthetic planning draft presents a Council community preparedness review agenda for Cairns, Queensland.
The audience includes community resilience officers, school safety leads and local service partners. It contains
no verified local operating arrangements, current incident information or nominated destinations. Evidence gaps,
proposed responsibilities and review dates remain subject to responsible organisational confirmation before
formal use.

## 3. Purpose and Scope
This draft covers the application-recognised council community preparedness scenario. This draft includes
evacuation, communication, smoke exposure, roles and responsibilities, official source verification and human
review in its preparedness planning. The scope is this month's preparedness discussions, not live emergency
advice or an instruction to move people. The administrative timetable is a proposal with no established claim
about any measure's effects. Operational decisions remain outside the supplied evidence.

## 4. Selected Geography and Key Assumptions
No site address, premises boundary or participant register is verified for this selected Cairns SA4 fixture.
The responsible organisation has not approved the assumptions or timetable.

[APP_P2_FIELDS]

## 5. Data Sources and Limitations
The source register contains controlled verification entry points only, with no submitted passage supporting
a local operating arrangement. No live warning feed or current road information is available. Source currency,
geographic applicability and organisational relevance remain unresolved review matters. The prose is draft
synthesis, not a substitute for evidence or responsible-authority advice.

## 6. Local Risk Context
Bushfire, smoke, heat, road access, power and communication are topics for the review agenda. Their local
occurrence, severity and effects are unknown in this example. No causal assessment of the community is
established by the supplied information. Evidence gaps remain for qualified reviewers using relevant records
and current official information; household guidance is not an established organisational procedure.

## 7. Preparedness Priorities
Unverified proposal for local review: the responsible organisation must confirm the evacuation, communication
and smoke health support priorities, including the evidence needed for each topic and the accountable reviewer
for outstanding questions. Existing local policies, appointment records and consultation outcomes remain unknown.

## 8. Evacuation Planning
Warning procedures, candidate routes, assisted transport and participant accountability arrangements are not
supplied. No route or destination is verified. Unverified proposal for local review: the responsible organisation
must confirm a process for obtaining authorised advice on notification, movement and accountability before any
operational use. This draft contains no direction about when or where people should move.

## 9. Candidate Assembly Point Criteria
Physical assembly criteria are unknown and no candidate venue has been verified. Unverified proposal for local
review: the responsible organisation must confirm which authority will provide applicable criteria and which
records are needed for a later venue assessment. Venue selection remains unresolved, with no facility designated.

## 10. Roles and Responsibilities
The following role label describes a review responsibility, not a confirmed appointment or existing procedure.

[APP_ROLE_FIELDS]

## 11. Communication and Inclusion Needs
Internal notification, accessible public information and backup communication arrangements are unknown.
Unverified proposal for local review: the communications officer must confirm channel ownership, participant
needs and the process for checking current official warning information.

## 12. First Aid, Training and Exercises
First aid readiness, smoke and heat health support, AED and burn preparedness, qualifications and exercise
frequency are unknown. Unverified proposal for local review: the first aid coordinator must confirm qualified
reviewers, evidence requirements and exercise records. This draft provides no clinical treatment instructions.

## 13. Action Plan
[APP_ACTION_FIELDS]

## 14. Human Review and Approval Checklist
[APP_REVIEW_FIELDS]

## 15. Safety Disclaimer
This draft does not establish operational safety. Live warnings, fire bans, evacuation orders and life-safety
decisions must come from official emergency services. Call 000 in a life-threatening emergency.
"""

# The loopback mock returns the same strict protocol payload expected from a
# governed model. Rendering, frozen fields and gate assessment remain real.
MOCK_REPORT = section_response_from_markdown(MOCK_REPORT_MARKDOWN, _valid_report()[1])


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


def _fill_review_field(page, label, value, *, textarea=False):
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import expect

    selector = "textarea" if textarea else "input"
    last_error = None
    for _attempt in range(4):
        try:
            review_tab = page.get_by_role("tab", name="Review & Export", exact=True)
            review_tab.click()
            expect(review_tab).to_have_attribute("aria-selected", "true", timeout=15_000)
            field = page.locator(f'{selector}[aria-label="{label}"]:visible').last
            expect(field).to_be_editable(timeout=15_000)
            field.fill(value, timeout=15_000)
            return
        except PlaywrightTimeoutError as error:
            last_error = error
    raise last_error


def _wait_for_health(process, health_url, timeout_seconds=45):
    target = urlsplit(health_url)
    if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("E2E health checks must use a local HTTP endpoint.")
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Streamlit exited before the browser test could start.")
        try:
            with opener.open(health_url, timeout=1) as response:
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


def _write_map_fixture(runtime_dir):
    profile_path = runtime_dir / "sa2_profiles_all.csv"
    profile_path.write_text(
        "sa2_code,state_name,sa4_name,sa3_name,sa2_name,population,older_people_count,"
        "language_other_than_english_count,language_support_needed\n"
        "306041173,Queensland,Cairns,Cairns - North,Cairns City,171000,25650,34200,high\n"
        "305031136,Queensland,Brisbane - East,Brisbane East,Bayside,205000,28700,41000,high\n",
        encoding="utf-8",
    )
    boundary_path = runtime_dir / "sa2_boundaries_all.geojson"
    features = [
        {
            "type": "Feature",
            "properties": {
                "sa2_code_2021": "306041173",
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
                "sa2_code_2021": "305031136",
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
    (runtime_dir / "sa2_map_bundle.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_rows": 2,
                "boundary_features": 2,
                "shared_sa2_codes": 2,
                "artifacts": {
                    "profile": {
                        "size_bytes": profile_path.stat().st_size,
                        "sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                    },
                    "boundary": {
                        "size_bytes": boundary_path.stat().st_size,
                        "sha256": hashlib.sha256(boundary_path.read_bytes()).hexdigest(),
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return profile_path, boundary_path


def _write_official_sources_fixture(runtime_dir, server_port):
    path = runtime_dir / "official_sources.yml"
    path.write_text(
        "sources:\n"
        "  - id: mock_qld_source\n"
        "    name: Mock Queensland Official Source\n"
        f"    url: http://127.0.0.1:{server_port}/official/healthy\n"
        "    scope: [australia, queensland]\n"
        "    purpose: Controlled entry-point reachability test.\n"
        "    use_when: Browser E2E verification only.\n"
        "  - id: mock_bom_source\n"
        "    name: Mock Bureau of Meteorology Source\n"
        f"    url: http://127.0.0.1:{server_port}/official/healthy\n"
        "    scope: [australia, queensland, weather]\n"
        "    purpose: Controlled weather-source reachability test.\n"
        "    use_when: Browser E2E verification only.\n",
        encoding="utf-8",
    )
    return path


def _report_download_button(page, label, protected_downloads):
    if not protected_downloads:
        return page.get_by_role("button", name=label, exact=True)
    # The private-delivery component uses a session-local srcdoc, not a media URL.
    frame = page.locator(f'iframe:visible[srcdoc*="{label}</button>"]').content_frame
    return frame.get_by_role("button", name=label, exact=True)


def _route_loopback_only(route, blocked_requests):
    target = urlsplit(route.request.url)
    if target.scheme in {"http", "https"} and target.hostname not in {"127.0.0.1", "localhost", "::1"}:
        # Keep only non-secret resource origin/path; never record URL query values.
        blocked_requests.append({"origin": f"{target.scheme}://{target.hostname}", "path": target.path})
        route.abort()
    else:
        route.continue_()


def _validate_workspace_path(path):
    root = PROJECT_ROOT.resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("E2E paths must be strict children of the workspace.")
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            attributes = getattr(candidate.lstat(), "st_file_attributes", 0)
            if candidate.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("E2E paths must not traverse a symlink or reparse point.")
        if candidate == root:
            break
    if not path.resolve().is_relative_to(root):
        raise ValueError("Resolved E2E path escaped the workspace.")


def _create_run_paths():
    """Never delete or reuse another run's outputs, including on successful runs."""
    _validate_workspace_path(ARTIFACT_PARENT)
    ARTIFACT_PARENT.mkdir(parents=True, exist_ok=True)
    artifact_dir = ARTIFACT_PARENT / f"e2e-v7-{uuid4().hex}"
    _validate_workspace_path(artifact_dir)
    artifact_dir.mkdir(exist_ok=False)
    runtime_dir = artifact_dir / "runtime"
    runtime_dir.mkdir(exist_ok=False)
    _validate_workspace_path(runtime_dir)
    return artifact_dir, runtime_dir


def _browser_environment(runtime_dir, server_port, protected_downloads):
    profile_path, boundary_path = _write_map_fixture(runtime_dir)
    sources_path = _write_official_sources_fixture(runtime_dir, server_port)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("BUSHFIRE_", "RAILWAY_", "OLLAMA_", "LLM_", "OPENAI_", "OPENROUTER_", "DEEPSEEK_"))
        and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
    }
    environment.update(
        {
            "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONIOENCODING": "utf-8",
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
            "BUSHFIRE_DEPLOYMENT_MODE": "local",
            "BUSHFIRE_ALLOW_EXTERNAL_MODEL": "false",
            "BUSHFIRE_ACCESS_PASSWORD": "Synthetic-workflow-password-2026" if protected_downloads else "",
            "BUSHFIRE_ACCESS_PASSWORD_HASH": "",
            "BUSHFIRE_ADMIN_PASSWORD": "",
            "BUSHFIRE_ADMIN_PASSWORD_HASH": "",
            "LLM_PROVIDER": "ollama",
            "OLLAMA_BASE_URL": f"http://127.0.0.1:{server_port}/v1",
            "OLLAMA_API_KEY": "synthetic-loopback-only",
            "OLLAMA_MODEL": "e2e-model",
            "BUSHFIRE_RUNTIME_DIR": str(runtime_dir),
            "BUSHFIRE_SESSION_STATE_PATH": str(runtime_dir / "session_state.json"),
            "BUSHFIRE_INTERACTION_LOG_PATH": str(runtime_dir / "interaction.jsonl"),
            "BUSHFIRE_AUDIT_DIR": str(runtime_dir / "audit"),
            "BUSHFIRE_TRACE_DIR": str(runtime_dir / "traces"),
            "BUSHFIRE_TRACE_ENABLED": "true",
            "BUSHFIRE_RAG_ENABLED": "false",
            "BUSHFIRE_ALL_SA2_PROFILE_PATH": str(profile_path),
            "BUSHFIRE_ALL_SA2_BOUNDARY_PATH": str(boundary_path),
            "BUSHFIRE_ALL_SA2_BOUNDARY_BY_STATE_DIR": str(runtime_dir / "boundaries_by_state"),
            "BUSHFIRE_OFFICIAL_SOURCES_PATH": str(sources_path),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        }
    )
    return environment


def _assert_fixture_governed_gate(environment):
    """Exercise the app's exact form/map analysis and actual gate, with no SDK call."""
    with patch.dict(os.environ, environment, clear=True):
        from src.agents import run_analysis_pipeline
        from src.app_catalog import EXAMPLE_CASES
        from src.coverage_map import is_area_selection_available
        from src.report_generation_quality import generate_narrative_with_repairs

        example = EXAMPLE_CASES["Cairns Council pilot"]
        assert is_area_selection_available(example["map_selection"])
        analysis = run_analysis_pipeline(
            **{
                key: example[key]
                for key in ("location", "audience", "scenario", "concerns", "timeframe", "extra_context")
            },
            area_selection=dict(example["map_selection"]),
        )
        assert analysis["community"]["indicators"]["population"] == "171000"
        assert analysis["community"]["indicators"]["older_people_pct"] == "15.0"
        assert analysis["community"]["indicators"]["matched_sa2_count"] == "1"
        assert not analysis["knowledge"].get("retrieved_chunks")
        narrative, quality, attempts = generate_narrative_with_repairs(
            "Synthetic offline preflight; no SDK transport.",
            analysis,
            lambda _prompt, _attempt, _repair: MOCK_REPORT,
            max_repair_attempts=0,
        )
        assert attempts == 1
        assert quality["approval_gate"]["passed"] is True, [
            (check["name"], check.get("word_count"), check["detail"])
            for check in quality["checks"]
            if check["status"] == "fail"
        ]
        assert quality["quality_policy_version"] == "governed-report-v11"
        return analysis, narrative, quality


def test_browser_mock_report_passes_real_current_gate_offline():
    artifact_dir, runtime_dir = _create_run_paths()
    environment = _browser_environment(runtime_dir, 49151, False)
    _analysis, _narrative, quality = _assert_fixture_governed_gate(environment)
    # Retain only this synthetic preflight result, not user records or SDK metadata.
    (artifact_dir / "offline-gate.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")


def test_browser_run_paths_are_fresh_and_preserve_existing_artifacts(monkeypatch):
    artifact_dir, runtime_dir = _create_run_paths()
    assert artifact_dir.parent == ARTIFACT_PARENT
    assert runtime_dir.parent == artifact_dir
    marker = runtime_dir / "synthetic-preservation-marker.txt"
    marker.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "uuid4", lambda: type("FixedID", (), {"hex": artifact_dir.name[7:]})())
    with pytest.raises(FileExistsError):
        _create_run_paths()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_browser_path_guard_rejects_outside_and_reparse(monkeypatch):
    with pytest.raises(ValueError, match="strict children"):
        _validate_workspace_path(PROJECT_ROOT.parent / "not-the-project")
    original = Path.lstat
    blocked = ARTIFACT_PARENT / "synthetic-reparse"
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == blocked)
    monkeypatch.setattr(Path, "lstat", lambda path: original(ARTIFACT_PARENT) if path == blocked else original(path))
    with pytest.raises(ValueError, match="symlink or reparse"):
        _validate_workspace_path(blocked)


def test_browser_network_guards_are_loopback_only_without_url_query_logging():
    with pytest.raises(ValueError, match="local HTTP"):
        _wait_for_health(None, "https://external.invalid/health")
    blocked = []
    for url, expected in (
        ("http://127.0.0.1:8501/static/app.js", "continue"),
        ("http://localhost:8501/", "continue"),
        ("http://[::1]:8501/", "continue"),
        ("data:text/plain,synthetic", "continue"),
        ("blob:http://127.0.0.1:8501/synthetic", "continue"),
        ("https://external.invalid/tiles?token=synthetic-private", "abort"),
        ("http://localhost.external.invalid/script.js", "abort"),
    ):
        actions = []
        route = SimpleNamespace(
            request=SimpleNamespace(url=url),
            abort=lambda: actions.append("abort"),
            continue_=lambda: actions.append("continue"),
        )
        _route_loopback_only(route, blocked)
        assert actions == [expected]
    assert blocked == [
        {"origin": "https://external.invalid", "path": "/tiles"},
        {"origin": "http://localhost.external.invalid", "path": "/script.js"},
    ]


@pytest.mark.e2e
@pytest.mark.parametrize("protected_downloads", [False, True], ids=["native-local", "authenticated-blob"])
def test_browser_report_data_map_and_human_signoff_workflow(protected_downloads):
    from playwright.sync_api import expect, sync_playwright

    artifact_dir, runtime_dir = _create_run_paths()

    MockModelHandler.request_count = 0
    MockModelHandler.official_request_count = 0
    model_port = _available_port()
    env = _browser_environment(runtime_dir, model_port, protected_downloads)
    _assert_fixture_governed_gate(env)
    model_server = ThreadingHTTPServer(("127.0.0.1", model_port), MockModelHandler)
    model_thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    model_thread.start()

    app_port = _available_port()
    app_url = f"http://127.0.0.1:{app_port}"
    log_path = artifact_dir / "streamlit.log"
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
            browser = playwright.chromium.launch(headless=True, env=env, args=["--no-proxy-server"])
            context = browser.new_context(accept_downloads=True)
            blocked_requests = []
            context.route("**/*", lambda route: _route_loopback_only(route, blocked_requests))
            context.tracing.start(screenshots=True, snapshots=True, sources=False)
            browser_errors = []
            try:
                page = context.new_page()
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                page.goto(app_url, wait_until="domcontentloaded", timeout=60_000)
                if protected_downloads:
                    page.get_by_label("Access password", exact=True).fill("Synthetic-workflow-password-2026")
                    page.get_by_role("button", name="Sign in", exact=True).click()
                expect(
                    page.get_by_role(
                        "heading",
                        name="BushfireReadyGPT Preparedness Planning Workspace",
                        exact=True,
                    )
                ).to_be_visible(timeout=30_000)

                pilot_example = page.get_by_label("Pilot example", exact=True)
                pilot_example.click()
                pilot_example.press("ArrowDown")
                pilot_example.press("Enter")
                expect(pilot_example).to_have_value("Cairns Council pilot")
                page.get_by_role("button", name="Load example", exact=True).click()
                expect(page.get_by_label("Location", exact=True)).to_have_value("Cairns, Queensland")
                expect(page.get_by_label("Audience", exact=True)).to_have_value(
                    "Council community resilience officers, school safety leads, and local service partners"
                )

                page.get_by_role("button", name="Generate report", exact=True).click()
                expect(page.get_by_role("heading", name="Latest Report Preview", exact=True)).to_be_visible(
                    timeout=60_000
                )
                expect(page.get_by_text("Cairns Council Bushfire Preparedness Draft", exact=True).first).to_be_visible()

                with page.expect_download(timeout=30_000) as markdown_download_info:
                    _report_download_button(page, "Download Markdown", protected_downloads).click()
                markdown_download = markdown_download_info.value
                assert markdown_download.suggested_filename == "bushfire_ready_report.md"
                assert "Cairns Council Bushfire Preparedness Draft" in Path(markdown_download.path()).read_text(
                    encoding="utf-8"
                )

                page.wait_for_timeout(1_000)
                page.get_by_role("tab", name="Review & Export", exact=True).click()
                expect(
                    page.get_by_role(
                        "heading",
                        name="Evidence Confidence and Provenance",
                        exact=True,
                    ).last
                ).to_be_visible()
                _fill_review_field(page, "Reviewer name", "Browser E2E Reviewer")
                _fill_review_field(page, "Reviewer role / title", "School safety reviewer")
                _fill_review_field(page, "Organisation / department", "Cairns Campus Pilot")
                _fill_review_field(
                    page,
                    "Review notes",
                    "Reviewed through the automated browser workflow.",
                    textarea=True,
                )
                page.get_by_role("tab", name="Review & Export", exact=True).click()
                page.get_by_role("button", name="Update sign-off record", exact=True).click()

                expect(page.get_by_text("Sign-off section updated in the latest report.", exact=True)).to_be_visible()
                expect(
                    page.get_by_text(
                        "A new append-only audit event was created and linked to the prior event.",
                        exact=True,
                    )
                ).to_be_visible()

                # Do not interact with any other widget before testing the earlier
                # sidebar export: a rerun must already have refreshed the signed report.
                with page.expect_download(timeout=30_000) as signed_sidebar_info:
                    _report_download_button(page, "Download latest report", protected_downloads).click()
                signed_sidebar = Path(signed_sidebar_info.value.path()).read_text(encoding="utf-8")
                assert "Browser E2E Reviewer" in signed_sidebar
                assert "Reviewed through the automated browser workflow." in signed_sidebar
                if protected_downloads:
                    assert signed_sidebar_info.value.url.startswith("blob:")

                with page.expect_download(timeout=30_000) as package_download_info:
                    _report_download_button(page, "Download pilot export package", protected_downloads).click()
                package_download = package_download_info.value
                package_download.save_as(artifact_dir / "signed-pilot-package.zip")
                with ZipFile(package_download.path()) as package:
                    names = set(package.namelist())
                    audit_payload = json.loads(package.read("governance/audit_record.json"))
                    package_manifest = json.loads(package.read("governance/package_manifest.json"))
                    packaged_report = package.read(
                        next(name for name in names if name.startswith("reports/") and name.endswith(".md"))
                    ).decode("utf-8")
                    packaged_documents = {
                        suffix: package.read(
                            next(name for name in names if name.startswith("reports/") and name.endswith("." + suffix))
                        )
                        for suffix in ("pdf", "docx")
                    }
                assert packaged_report == signed_sidebar

                page.get_by_role("tab", name="Create Report", exact=True).click()
                with page.expect_download(timeout=30_000) as signed_preview_info:
                    _report_download_button(page, "Download Markdown", protected_downloads).click()
                assert Path(signed_preview_info.value.path()).read_text(encoding="utf-8") == signed_sidebar
                for suffix, label in (("pdf", "Download PDF"), ("docx", "Download DOCX")):
                    with page.expect_download(timeout=30_000) as standalone_info:
                        _report_download_button(page, label, protected_downloads).click()
                    standalone = standalone_info.value
                    standalone.save_as(artifact_dir / f"signed-report.{suffix}")
                    assert Path(standalone.path()).read_bytes() == packaged_documents[suffix]
                    if protected_downloads:
                        assert standalone.url.startswith("blob:")
                assert "governance/package_manifest.json" in names
                assert "governance/audit_record.json" in names
                assert len([name for name in names if name.startswith("governance/audit_chain/")]) == 2
                assert any(name.endswith(".md") for name in names)
                assert audit_payload["event_type"] == "review.recorded"
                assert package_manifest["privacy"]["classification"] == "sensitive-governance-export"
                assert len(package_manifest["audit_chain"]) == 2
                assert {row["code"] for row in audit_payload["analysis"]["evidence_confidence"]} == {
                    "O1",
                    "P2",
                    "R3",
                    "A4",
                    "U0",
                }
                assert MockModelHandler.request_count == 1

                page.get_by_role("tab", name="Data & Map", exact=True).click()
                expect(
                    page.get_by_text(
                        "Active report geography: Queensland / SA4 / Cairns",
                        exact=True,
                    )
                ).to_be_visible(
                    timeout=30_000,
                )
                search_area = page.get_by_label("Search area", exact=True)
                search_area.fill("Brisbane")
                search_area.press("Enter")
                page.get_by_role("button", name="Use previewed area for report", exact=True).click()
                expect(
                    page.get_by_text(
                        "Active report geography: Queensland / SA4 / Brisbane - East",
                        exact=True,
                    )
                ).to_be_visible(timeout=30_000)

                data_map_panel = page.get_by_label("Data & Map")
                expect(data_map_panel.get_by_text("Mock Queensland Official Source", exact=True)).to_be_visible()
                page.get_by_role("button", name="Check official source status", exact=True).click()
                reachable_card = page.locator(".status-card").filter(has_text="Reachable")
                expect(reachable_card).to_contain_text("2", timeout=30_000)
                assert MockModelHandler.official_request_count == 2

                active_data_card = page.locator(".status-card").filter(has_text="Active data")
                expect(active_data_card).to_contain_text("ABS processed data")
                workflow_completed = True
            except Exception:
                if page is not None:
                    page.screenshot(path=str(artifact_dir / "failure.png"), full_page=True)
                (artifact_dir / "browser-errors.json").write_text(
                    json.dumps(browser_errors, indent=2), encoding="utf-8"
                )
                context.tracing.stop(path=str(artifact_dir / "failure-trace.zip"))
                raise
            finally:
                (artifact_dir / "blocked-external-resources.json").write_text(
                    json.dumps(blocked_requests, indent=2), encoding="utf-8"
                )
                context.close()
                browser.close()
    finally:
        _stop_process(app_process)
        log_file.close()
        model_server.shutdown()
        model_server.server_close()
        model_thread.join(timeout=5)
        if workflow_completed:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            assert "StreamlitAPIException" not in log_text
            assert "was created with a default value but also had its value set" not in log_text
