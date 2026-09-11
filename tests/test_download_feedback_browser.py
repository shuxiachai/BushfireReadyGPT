"""Browser-local failure feedback uses only synthetic exports and no service."""

import html

import pytest

from src.ui.downloads import _private_download_html


@pytest.mark.e2e
@pytest.mark.parametrize("failure", ["missing_api", "blob_error", "silent_policy_block"])
def test_private_download_failure_is_visible_without_claiming_file_save(failure):
    from playwright.sync_api import expect, sync_playwright

    document = _private_download_html(
        "Download synthetic report", b"Synthetic private bytes", "report.md", "text/markdown"
    )
    sandbox = (
        "allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox "
        "allow-same-origin allow-scripts allow-downloads"
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(accept_downloads=True)
            requests, errors, downloads = [], [], []
            page.on("request", lambda request: requests.append(request.url))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("download", lambda download: downloads.append(download.url))
            page.set_content(f'<iframe sandbox="{sandbox}" srcdoc="{html.escape(document, quote=True)}"></iframe>')
            frame = page.frames[1]
            button = frame.get_by_role("button", name="Download synthetic report", exact=True)
            expect(button).to_be_visible()
            frame.evaluate(
                {
                    "missing_api": "() => { URL.createObjectURL = undefined; }",
                    "blob_error": """() => {
                        URL.createObjectURL = () => {
                            throw new DOMException('Synthetic private exception detail', 'QuotaExceededError');
                        };
                    }""",
                    # Browser policy can decline a download without throwing. The app
                    # can report only the request, never confirm a disk write.
                    "silent_policy_block": "() => { HTMLAnchorElement.prototype.click = () => {}; }",
                }[failure]
            )
            button.click()
            status = frame.get_by_role("status")
            expected = "Download requested." if failure == "silent_policy_block" else "Download could not be started."
            expect(status).to_contain_text(expected)
            expect(status).to_contain_text("Chrome or Edge")
            expect(status).to_contain_text("Keep this session open")
            expect(status).not_to_contain_text("saved")
            expect(status).not_to_contain_text("Synthetic private")
            expect(status).to_be_visible()
            assert frame.locator("a").count() == 0
            assert not downloads
            assert not errors
            assert not requests
        finally:
            browser.close()
