"""Widget shell must load via loopback URL (WebView2 2 MB NavigateToString limit)."""

from __future__ import annotations

from urllib.request import urlopen

from tkipw.app import _load_shell_html, _shell_document_url

# WebView2 NavigateToString rejects HTML larger than this (UTF-16-ish bound;
# we treat UTF-8 byte length as a conservative stand-in).
_WEBVIEW2_NAVIGATE_TO_STRING_LIMIT = 2 * 1024 * 1024


def test_shell_html_exceeds_webview2_inline_limit():
    html = _load_shell_html()
    assert len(html.encode("utf-8")) > _WEBVIEW2_NAVIGATE_TO_STRING_LIMIT


def test_shell_document_url_serves_runtime_over_loopback():
    url = _shell_document_url()
    assert url.startswith("http://127.0.0.1:")
    with urlopen(url, timeout=5) as resp:  # noqa: S310 — loopback only
        body = resp.read().decode("utf-8")
    assert "tkipw-root" in body
    assert "Starting widget runtime" in body
