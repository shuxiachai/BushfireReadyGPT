"""Deliver private exports through the authenticated session, not public media URLs.

Streamlit's ordinary download_button registers bytes in an unauthenticated HTTP
media store. Protected deployments instead send bounded, encoded bytes in the
current session's iframe srcdoc; the browser creates a local Blob only on click.
Already delivered bytes, like an already displayed report, cannot be revoked.
"""

from __future__ import annotations

import base64
import html

import streamlit as st

from src.deployment_access import (
    AccessDeniedError,
    is_access_authorized,
    requires_access_authentication,
)

MAX_PRIVATE_DOWNLOAD_BYTES = 8 * 1024 * 1024
_ALLOWED_MIME_TYPES = frozenset(
    {
        "application/json",
        "application/pdf",
        "application/zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/csv",
        "text/markdown",
        "text/plain",
    }
)


def _private_download_html(label: str, data: str | bytes, file_name: str, mime: str) -> str:
    if not isinstance(data, (str, bytes)):
        raise ValueError("Downloads require text or bytes, not a path or callback.")
    if not isinstance(mime, str) or mime not in _ALLOWED_MIME_TYPES:
        raise ValueError("Unsupported private download format.")
    if (
        not isinstance(file_name, str)
        or not file_name.strip()
        or len(file_name) > 240
        or file_name in {".", ".."}
        or any(character in file_name for character in "/\\:")
        or any(ord(character) < 32 or ord(character) == 127 for character in file_name)
    ):
        raise ValueError("Downloads require a safe filename without directories.")
    if not isinstance(label, str) or not label.strip() or len(label) > 240:
        raise ValueError("Downloads require a short text label.")
    if len(data) > MAX_PRIVATE_DOWNLOAD_BYTES:
        raise ValueError("Private export exceeds the 8 MiB session-delivery limit.")
    payload = data.encode("utf-8") if isinstance(data, str) else data
    if len(payload) > MAX_PRIVATE_DOWNLOAD_BYTES:
        raise ValueError("Private export exceeds the 8 MiB session-delivery limit.")
    # None of the content, filename or label is ever interpolated into executable JS.
    encoded = base64.b64encode(payload).decode("ascii")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none';
script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<style>
body {{margin:0;font-family:system-ui,sans-serif}}
button {{box-sizing:border-box;width:100%;min-height:44px;padding:8px 10px;
border:1px solid #51677b;border-radius:8px;background:#0e1c27;color:#fafafa;
font:inherit;font-size:14px;cursor:pointer;white-space:normal}}
button:hover {{border-color:#ff7844}} button:focus-visible {{outline:2px solid #ff7844;outline-offset:-3px}}
#download-status {{margin:6px 0 0;color:#b7c8d7;font-size:12px;line-height:1.4}}
#download-status:empty {{margin:0}}
</style></head><body>
<button id="download" type="button" data-filename="{html.escape(file_name, quote=True)}"
data-mime="{mime}" aria-describedby="download-status">{html.escape(label)}</button>
<p id="download-status" role="status" aria-live="polite" aria-atomic="true"></p>
<script id="payload" type="application/octet-stream">{encoded}</script>
<script>
"use strict";
const downloadButton = document.getElementById("download");
const downloadStatus = document.getElementById("download-status");
downloadButton.addEventListener("click", () => {{
    downloadStatus.textContent = "";
    let objectUrl = null;
    let link = null;
    try {{
        if (typeof Blob !== "function" || typeof URL.createObjectURL !== "function" ||
                typeof URL.revokeObjectURL !== "function") {{
            throw new Error("Browser-local downloads are unavailable.");
        }}
        const binary = atob(document.getElementById("payload").textContent);
        const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
        const blob = new Blob([bytes], {{type: downloadButton.dataset.mime}});
        objectUrl = URL.createObjectURL(blob);
        link = document.createElement("a");
        link.href = objectUrl;
        link.download = downloadButton.dataset.filename;
        document.body.appendChild(link);
        link.click();
        // A click cannot confirm that browser policy allowed the file to be saved.
        downloadStatus.textContent = "Download requested. Check your browser's downloads. " +
            "If no file appears, retry in Chrome or Edge. Keep this session open until you have the file.";
    }} catch {{
        downloadStatus.textContent = "Download could not be started. Check your browser's download settings, " +
            "then retry in Chrome or Edge. Keep this session open.";
    }} finally {{
        if (link) link.remove();
        // Give the browser time to acquire the Blob before releasing the URL.
        if (objectUrl) setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    }}
}});
</script></body></html>"""


def download_button(
    label,
    data,
    file_name,
    mime,
    *,
    width="stretch",
    key=None,
    on_click="ignore",
    target=None,
):
    """Preserve open local downloads; never publish protected bytes to /media.

    The server revalidates authentication before every delivery. Browser-local
    downloads do not make another HTTP/model request or trigger a Streamlit rerun.
    """
    renderer = st if target is None else target
    if not requires_access_authentication():
        return renderer.download_button(
            label, data=data, file_name=file_name, mime=mime, width=width, key=key, on_click=on_click
        )
    if not is_access_authorized(st.session_state):
        raise AccessDeniedError("Sign in again before downloading private artifacts.")
    if on_click != "ignore":
        raise ValueError("Private downloads cannot execute server callbacks.")
    document = _private_download_html(label, data, file_name, mime)
    # A raw HTML string uses inline srcdoc. Passing a Path would create a media URL.
    # Content sizing keeps the accessible failure/status message visible on narrow screens.
    return renderer.iframe(document, height="content", width=width, tab_index=0)
