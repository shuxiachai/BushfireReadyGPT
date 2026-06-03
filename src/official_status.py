from datetime import datetime

import requests


DEFAULT_TIMEOUT_SECONDS = 8
USER_AGENT = "BushfireReadyGPT prototype official-source-status-check/0.1"


def check_official_sources(sources, timeout=DEFAULT_TIMEOUT_SECONDS):
    """Check official source entry-point availability without interpreting warnings."""

    checked_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for source in sources:
        rows.append(_check_source(source, checked_at, timeout))
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
        response, elapsed_ms = _request_source(url, timeout)
        status_code = response.status_code
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
    started = datetime.now()
    try:
        response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        if response.status_code in {403, 405} or response.status_code >= 500:
            response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
    except requests.RequestException:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
    elapsed_ms = int((datetime.now() - started).total_seconds() * 1000)
    response.close()
    return response, elapsed_ms


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
