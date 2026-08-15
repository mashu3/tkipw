"""``tkipw.widget_modules``: explicit AMD/nbextension registration (no WebView)."""

from __future__ import annotations

from urllib.request import urlopen

import pytest

from tkipw.app import _load_shell_html
from tkipw.widget_modules import (
    discover_widget_modules,
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


_AMD_EMPTY = b"define([],function(){return {};});\n"


def _write_nbextension(root, name: str, payload: bytes = _AMD_EMPTY):
    folder = root / name
    folder.mkdir()
    (folder / "index.js").write_bytes(payload)
    return folder


def test_discover_widget_modules_registers_index_js(tmp_path):
    _write_nbextension(tmp_path, "demo-auto")
    _write_nbextension(tmp_path, "bqplot")  # bundled — skipped
    chrome = tmp_path / "chrome-only"
    chrome.mkdir()
    (chrome / "extension.js").write_bytes(b"define([],function(){});\n")
    try:
        added = discover_widget_modules(paths=[tmp_path])
        assert added == ["demo-auto"]
        spec = registered_widget_modules()["demo-auto"]
        assert spec["url"].endswith("/index.js")
        assert "bqplot" not in registered_widget_modules()
        assert "chrome-only" not in registered_widget_modules()
    finally:
        unregister_widget_module("demo-auto")


def test_discover_widget_modules_keeps_explicit_register(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    explicit = _write_nbextension(first, "demo-keep", b"/*a*/")
    _write_nbextension(second, "demo-keep", b"/*b*/")
    try:
        register_widget_module("demo-keep", explicit)
        url = registered_widget_modules()["demo-keep"]["url"]
        added = discover_widget_modules(paths=[second])
        assert added == []
        assert registered_widget_modules()["demo-keep"]["url"] == url
    finally:
        unregister_widget_module("demo-keep")


def test_discover_widget_modules_first_path_wins(tmp_path):
    early = tmp_path / "early"
    late = tmp_path / "late"
    early.mkdir()
    late.mkdir()
    _write_nbextension(early, "demo-win", b"/*early*/")
    _write_nbextension(late, "demo-win", b"/*late*/")
    try:
        added = discover_widget_modules(paths=[early, late])
        assert added == ["demo-win"]
        with urlopen(registered_widget_modules()["demo-win"]["url"], timeout=5) as resp:  # noqa: S310
            assert b"/*early*/" in resp.read()
    finally:
        unregister_widget_module("demo-win")


def test_shell_document_url_discovers_nbextensions(tmp_path, monkeypatch):
    from tkipw.app import _shell_document_url

    _write_nbextension(tmp_path, "demo-shell")
    monkeypatch.setattr("tkipw.widget_modules.nbextension_dirs", lambda: [tmp_path])
    try:
        url = _shell_document_url()
        spec = registered_widget_modules()["demo-shell"]
        with urlopen(url, timeout=5) as resp:  # noqa: S310
            html = resp.read().decode("utf-8")
        assert spec["url"] in html
    finally:
        unregister_widget_module("demo-shell")
