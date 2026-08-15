"""``tkipw.widget_modules``: explicit AMD/nbextension registration (no WebView)."""

from __future__ import annotations

from urllib.request import urlopen

import pytest

from tkipw.app import _load_shell_html
from tkipw.widget_modules import (
    register_widget_module,
    registered_widget_modules,
    unregister_widget_module,
    watch_widget_modules,
)


def test_register_widget_module_serves_js_and_css(tmp_path):
    js = tmp_path / "index.js"
    css = tmp_path / "index.css"
    js.write_text("define([], function () { return { X: 1 }; });\n", encoding="utf-8")
    css.write_text(".grid { color: red; }\n", encoding="utf-8")
    try:
        register_widget_module("demo-grid", tmp_path)
        spec = registered_widget_modules()["demo-grid"]
        assert spec["url"].startswith("http://127.0.0.1:")
        assert spec["url"].endswith("/index.js")
        assert spec["publicPath"].endswith("/")
        assert spec["style"].endswith("/index.css")
        with urlopen(spec["url"], timeout=5) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
            ctype = resp.headers.get_content_type()
        assert "define(" in body
        assert "javascript" in ctype
        with urlopen(spec["style"], timeout=5) as resp:  # noqa: S310
            assert b"color: red" in resp.read()
        html = _load_shell_html(
            runtime_js_url="http://127.0.0.1/runtime.js",
            runtime_css_url="http://127.0.0.1/runtime.css",
        )
        assert spec["url"] in html
        assert "window.__tkipwWidgetModules=" in html
        assert "__WIDGET_MODULES__" not in html
    finally:
        unregister_widget_module("demo-grid")
    assert "demo-grid" not in registered_widget_modules()


def test_register_widget_module_file_path(tmp_path):
    js = tmp_path / "grid.js"
    js.write_text("define([], function () { return {}; });\n", encoding="utf-8")
    try:
        register_widget_module("file-grid", js)
        spec = registered_widget_modules()["file-grid"]
        assert spec["url"].endswith("/grid.js")
        assert "style" not in spec
    finally:
        unregister_widget_module("file-grid")


def test_register_widget_module_rejects_reserved_and_missing(tmp_path):
    with pytest.raises(ValueError, match="bundled"):
        register_widget_module("bqplot", tmp_path)
    with pytest.raises(ValueError, match="name"):
        register_widget_module("", tmp_path)
    with pytest.raises(FileNotFoundError):
        register_widget_module("missing-grid", tmp_path / "nope.js")


def test_register_widget_module_notifies_watchers(tmp_path):
    js = tmp_path / "index.js"
    js.write_text("define([], function () { return {}; });\n", encoding="utf-8")
    seen: list[dict] = []
    unwatch = watch_widget_modules(lambda snap: seen.append(dict(snap)))
    try:
        register_widget_module("watched-grid", js)
        assert "watched-grid" in seen[-1]
        unregister_widget_module("watched-grid")
        assert "watched-grid" not in seen[-1]
    finally:
        unwatch()
        unregister_widget_module("watched-grid")
