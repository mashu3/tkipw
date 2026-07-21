"""Widget shell loads via loopback URL with external runtime assets."""

from __future__ import annotations

from urllib.request import urlopen

from tkipw.app import _load_shell_html, _shell_document_url

# WebView2 NavigateToString rejects HTML larger than this (UTF-16-ish bound;
# we treat UTF-8 byte length as a conservative stand-in).
_WEBVIEW2_NAVIGATE_TO_STRING_LIMIT = 2 * 1024 * 1024


def test_shell_html_stays_under_webview2_inline_limit():
    html = _load_shell_html(
        runtime_js_url="http://127.0.0.1/runtime.js",
        runtime_css_url="http://127.0.0.1/runtime.css",
    )
    assert len(html.encode("utf-8")) < _WEBVIEW2_NAVIGATE_TO_STRING_LIMIT


def test_shell_document_url_serves_runtime_over_loopback():
    url = _shell_document_url()
    assert url.startswith("http://127.0.0.1:")
    with urlopen(url, timeout=5) as resp:  # noqa: S310 — loopback only
        body = resp.read().decode("utf-8")
    assert "tkipw-root" in body
    assert "Starting widget runtime" in body
    assert 'data-theme="light"' in body
    assert 'rel="stylesheet" href="http://127.0.0.1:' in body
    assert '<script src="http://127.0.0.1:' in body

    # Linked assets must be fetchable and non-trivial.
    import re

    css_url = re.search(r'href="(http://127\.0\.0\.1:[^"]+\.css)"', body).group(1)
    js_url = re.search(r'src="(http://127\.0\.0\.1:[^"]+\.js)"', body).group(1)
    with urlopen(css_url, timeout=5) as resp:  # noqa: S310
        css = resp.read()
    with urlopen(js_url, timeout=5) as resp:  # noqa: S310
        js = resp.read()
    assert len(css) > 1000
    assert len(js) > 100_000


def test_shell_html_bakes_theme_attribute():
    assert 'data-theme="dark"' in _load_shell_html(theme="dark")
    assert 'data-theme="light"' in _load_shell_html(theme="light")
