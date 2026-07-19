"""``tkipw.html_host``: module-script demotion and loopback iframe hosting.

No WebView required; these exercise the pure HTML rewriting and the local
loopback HTTP server that srcdoc-heavy libraries rely on.
"""

from __future__ import annotations

from tkipw.html_host import (
    demote_module_scripts,
    host_html_document,
    host_srcdoc_iframe,
)


def test_demote_module_scripts():
    doc = '<script type="module">window.x=1</script>'
    fixed = demote_module_scripts(doc)
    assert 'type="module"' not in fixed
    assert "<script>" in fixed


def test_host_html_document_returns_loopback_iframe():
    fragment = host_html_document(
        "<!doctype html><p>hi</p>",
        width="800px",
        height="420px",
        title="My doc",
    )
    assert "tkipw-hosted-html" in fragment
    assert "http://127.0.0.1:" in fragment
    assert 'title="My doc"' in fragment
    assert "width:800px" in fragment
    assert "height:420px" in fragment


def test_host_html_document_inline_forces_full_width():
    from support import FakeApp

    from tkipw.comm_backend import set_bridge
    from tkipw.html_host import get_html_host

    set_bridge(FakeApp(display_mode="inline"))
    try:
        fragment = host_html_document(
            "<!doctype html><html><head></head><body><div id='x'></div></body></html>",
            width="800px",
            height="400px",
        )
        assert "width:100%" in fragment
        assert "aspect-ratio:800 / 400" in fragment
        assert "height:auto" in fragment
        assert "width:800px" not in fragment
        assert "height:400px" not in fragment
        # Inner document should stretch to the iframe.
        url = fragment.split('src="')[1].split('"')[0]
        key = url.rsplit("/", 1)[-1].removesuffix(".html")
        body = get_html_host()._documents[key].decode("utf-8")
        assert "width:100%!important" in body
    finally:
        set_bridge(None)


def test_host_html_document_inline_keeps_height_when_width_already_fluid():
    from support import FakeApp

    from tkipw.comm_backend import set_bridge

    set_bridge(FakeApp(display_mode="inline"))
    try:
        fragment = host_html_document(
            "<!doctype html><p>hi</p>",
            width="100%",
            height="320px",
        )
        assert "width:100%" in fragment
        assert "height:320px" in fragment
        assert "aspect-ratio" not in fragment
    finally:
        set_bridge(None)


def test_host_srcdoc_iframe_rewrites_srcdoc_to_src():
    iframe = (
        '<iframe srcdoc="&lt;!doctype html&gt;&lt;p&gt;hi&lt;/p&gt;" '
        'style="width: 99%; height: 600px"></iframe>'
    )
    hosted = host_srcdoc_iframe(iframe)
    assert hosted is not None
    assert "srcdoc" not in hosted
    assert "http://127.0.0.1:" in hosted
