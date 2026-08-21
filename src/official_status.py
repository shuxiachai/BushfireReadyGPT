from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import perf_counter

import requests

DEFAULT_TIMEOUT_SECONDS = 8
MAX_CONCURRENT_CHECKS = 4
USER_AGENT = "BushfireReadyGPT prototype official-source-status-check/0.1"


def check_official_sources(sources, timeout=DEFAULT_TIMEOUT_SECONDS):
    """Check official source entry-point availability without interpreting warnings."""

    checked_at = datetime.now().isoformat(timespec="seconds")
    source_rows = list(sources)
    if source_rows:
        worker_count = min(MAX_CONCURRENT_CHECKS, len(source_rows))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            rows = list(
                executor.map(
                    lambda source: _check_source(source, checked_at, timeout),
                    source_rows,
                )
            )
    else:
        rows = []
    return {
        "checked_at": checked_at,
        "rows": rows,
        "summary": _summarise(rows),
        "limitations": [
            "This panel checks whether official information entry points are reachable from this computer.",
            "It does not read, classify, summarise or validate current warnings, incidents, fire bans or evacuation orders.",
            "Operational decisions must still be made from official emergency services and responsible organisations.",
        ],
    }


def _check_source(source, checked_at, timeout):
    url = source.get("url", "")
    base = {
        "name": source.get("name", ""),
        "purpose": source.get("purpose", ""),
        "url": url,
        "checked_at": checked_at,
        "status": "Not checked",
        "http_status": "",
        "response_ms": "",
        "message": "",
    }
    if not url:
        return {**base, "status": "Missing URL", "message": "No source URL configured."}

    try:
        status_code, elapsed_ms = _request_source(url, timeout)
        status = "Reachable" if 200 <= status_code < 400 else "Check warning"
        return {
            **base,
            "status": status,
            "http_status": str(status_code),
            "response_ms": str(elapsed_ms),
            "message": _status_message(status_code),
        }
    except requests.RequestException as exc:
        return {
            **base,
            "status": "Check failed",
            "message": str(exc)[:180],
        }


def _request_source(url, timeout):
    headers = {"User-Agent": USER_AGENT}
    started = perf_counter()
    deadline = started + max(float(timeout), 0.05)
    try:
        # Bandit B113 false positive: timeout is the remaining shared deadline budget.
        response = requests.head(  # nosec B113
            url,
            headers=headers,
            timeout=_remaining_timeout(deadline),
            allow_redirects=True,
        )
        status_code = response.status_code
        response.close()
        if status_code in {403, 405} or status_code >= 500:
            status_code = _get_status_code(url, headers, deadline)
    except requests.RequestException:
        status_code = _get_status_code(url, headers, deadline)
    elapsed_ms = int((perf_counter() - started) * 1000)
    return status_code, elapsed_ms


def _get_status_code(url, headers, deadline):
    # Bandit B113 false positive: timeout is the remaining shared deadline budget.
    response = requests.get(  # nosec B113
        url,
        headers=headers,
        timeout=_remaining_timeout(deadline),
        allow_redirects=True,
        stream=True,
    )
    try:
        return response.status_code
    finally:
        response.close()


def _remaining_timeout(deadline):
    remaining = deadline - perf_counter()
    if remaining <= 0:
        raise requests.Timeout("Official-source check exceeded its total timeout budget.")
    return remaining


def _status_message(status_code):
    if 200 <= status_code < 300:
        return "Official entry point responded successfully."
    if 300 <= status_code < 400:
        return "Official entry point redirected successfully."
    if status_code in {401, 403}:
        return "Official site is reachable but rejected this automated check."
    if status_code == 404:
        return "Configured page was not found. Verify the URL."
    if status_code >= 500:
        return "Official site returned a server-side error during this check."
    return "Official entry point responded, but the status should be reviewed."


def _summarise(rows):
    reachable = sum(1 for row in rows if row["status"] == "Reachable")
    failed = sum(1 for row in rows if row["status"] == "Check failed")
    warnings = len(rows) - reachable - failed
    return {
        "total": len(rows),
        "reachable": reachable,
        "warnings": warnings,
        "failed": failed,
    }
