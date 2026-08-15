"""``tkipw.output``: notebook-like display, Output areas, and global patches.

No WebView required. Extension-driven transforms (e.g. matplotlib) are covered
in ``test_extensions.py``; this module tests the plain output primitives plus
the display-logging / excepthook install/uninstall lifecycle.
"""

from __future__ import annotations

import logging
import sys

import ipywidgets as widgets
import pytest
from IPython.display import HTML, Markdown

from tkipw.output import (
    DisplayLogHandler,
    Output,
    clear_output,
    display,
    error_html,
    install_display_logging,
    install_excepthook,
    register_mime_renderer,
    render_html,
    stream_context,
    to_widget,
    uninstall_display_logging,
    uninstall_excepthook,
    unregister_mime_renderer,
    update_display,
)


class TestToWidget:
    def test_passthrough(self):
        w = widgets.Label(value="hi")
        assert to_widget(w) is w

    def test_str_becomes_html(self):
        w = to_widget("hello")
        assert isinstance(w, widgets.HTML)
        assert "hello" in w.value


class TestRenderHtml:
    def test_plain_text(self):
        assert "hello" in render_html("hello")

    def test_escapes_markup(self):
        assert "&lt;" in render_html("a<b")

    def test_ipython_html(self):
        assert render_html(HTML("<strong>hello</strong>")) == "<strong>hello</strong>"

    def test_ipython_markdown(self):
        html = render_html(Markdown("# Heading\n\n- one\n- two"))
        assert 'class="tkipw-markdown"' in html
        assert "<h1>Heading</h1>" in html
        assert "<li>one</li>" in html

    def test_markdown_mimebundle(self):
        class MarkdownBundle:
            def _repr_mimebundle_(self, include=None, exclude=None):
                return {"text/markdown": "**bold**"}

        html = render_html(MarkdownBundle())
        assert "<strong>bold</strong>" in html

    def test_svg_mimebundle(self):
        class SvgBundle:
            def _repr_mimebundle_(self, include=None, exclude=None):
                return {"image/svg+xml": '<svg xmlns="http://www.w3.org/2000/svg"/>'}

        html = render_html(SvgBundle())
        assert 'class="tkipw-svg"' in html
        assert "<svg" in html

    def test_jpeg_mimebundle(self):
        class JpegBundle:
            def _repr_mimebundle_(self, include=None, exclude=None):
                return {"image/jpeg": b"\xff\xd8jpeg"}

        html = render_html(JpegBundle())
        assert "data:image/jpeg;base64," in html

    def test_json_mimebundle(self):
        class JsonBundle:
            def _repr_mimebundle_(self, include=None, exclude=None):
                return {"application/json": {"n": 1}}

        html = render_html(JsonBundle())
        assert 'class="tkipw-json"' in html
        assert '"n": 1' in html

    def test_svg_preferred_over_png(self):
        class Both:
            def _repr_mimebundle_(self, include=None, exclude=None):
                return {
                    "image/png": b"png",
                    "image/svg+xml": "<svg/>",
                }

        html = render_html(Both())
        assert "<svg" in html
        assert "image/png" not in html

    def test_repr_svg(self):
        class Svg:
            def _repr_svg_(self):
                return "<svg/>"

        html = render_html(Svg())
        assert 'class="tkipw-svg"' in html
        assert "<svg" in html

    def test_repr_png(self):
        class Png:
            def _repr_png_(self):
                return b"png"

        html = render_html(Png())
        assert "data:image/png;base64," in html

    def test_repr_jpeg(self):
        class Jpeg:
            def _repr_jpeg_(self):
                return b"\xff\xd8jpeg"

        html = render_html(Jpeg())
        assert "data:image/jpeg;base64," in html

    def test_repr_json(self):
        class Payload:
            def _repr_json_(self):
                return {"n": 1}

        html = render_html(Payload())
        assert 'class="tkipw-json"' in html
        assert '"n": 1' in html

    def test_mimebundle_html_wins_over_repr_png(self):
        class Both:
            def _repr_mimebundle_(self, include=None, exclude=None):
                return {"text/html": "<b>html</b>"}

            def _repr_png_(self):
                return b"png"

        html = render_html(Both())
        assert html == "<b>html</b>"
        assert "image/png" not in html

    def test_register_mime_renderer_beats_json_and_plain(self):
        register_mime_renderer(
            "application/vnd.my-plot+json",
            lambda raw: f'<div class="my-plot">{raw}</div>',
        )
        try:

            class Plot:
                def _repr_mimebundle_(self, include=None, exclude=None):
                    return {
                        "application/vnd.my-plot+json": "xyz",
                        "application/json": {"n": 1},
                        "text/plain": "plain",
                    }

            html = render_html(Plot())
            assert 'class="my-plot"' in html
            assert "xyz" in html
            assert "plain" not in html
            assert "tkipw-json" not in html
        finally:
            unregister_mime_renderer("application/vnd.my-plot+json")

    def test_register_mime_renderer_html_still_wins(self):
        register_mime_renderer(
            "application/vnd.my-plot+json",
            lambda raw: "CUSTOM",
        )
        try:

            class Both:
                def _repr_mimebundle_(self, include=None, exclude=None):
                    return {
                        "text/html": "<b>html</b>",
                        "application/vnd.my-plot+json": "xyz",
                    }

            assert render_html(Both()) == "<b>html</b>"
        finally:
            unregister_mime_renderer("application/vnd.my-plot+json")

    def test_mime_renderer_none_falls_through(self):
        register_mime_renderer("application/vnd.skip+json", lambda raw: None)
        try:

            class Skip:
                def _repr_mimebundle_(self, include=None, exclude=None):
                    return {
                        "application/vnd.skip+json": "ignored",
                        "text/plain": "plain",
                    }

            html = render_html(Skip())
            assert "plain" in html
            assert "ignored" not in html
        finally:
            unregister_mime_renderer("application/vnd.skip+json")

    def test_unregister_mime_renderer_restores_builtin(self):
        class Plain:
            def _repr_mimebundle_(self, include=None, exclude=None):
                return {"text/plain": "hello"}

        register_mime_renderer("text/plain", lambda raw: f"custom:{raw}")
        try:
            assert render_html(Plain()) == "custom:hello"
        finally:
            unregister_mime_renderer("text/plain")
        assert "<pre>hello</pre>" in render_html(Plain())

    def test_register_mime_renderer_rejects_empty(self):
        with pytest.raises(ValueError, match="mime"):
            register_mime_renderer("", lambda raw: str(raw))

    def test_error_html(self):
        html = error_html("ValueError: boom")
        assert "ValueError" in html
        assert "tkipw-error" in html
        assert "tkipw-stream" in html

    def test_stderr_html(self):
        html = error_html("warn", kind="stderr")
        assert "tkipw-stderr" in html
        assert "#9a3412" not in html


class TestOutput:
    def test_wait_then_replace(self):
        out = Output()
        a = widgets.Label("a")
        b = widgets.Label("b")
        out._append([a])
        assert out.children == (a,)

        with out:
            clear_output(wait=True)
            assert out.children == (a,)  # deferred until next append
            display(b)
        assert out.children == (b,)

    def test_clear_immediate(self):
        out = Output()
        out._append([widgets.Label("x")])
        out.clear_output(wait=False)
        assert out.children == ()

    def test_display_id_update_replaces_html_in_place(self):
        out = Output()
        with out:
            handle = display("one", display_id=True)
            assert handle is not None
            first = out.children[0]
            handle.update("two")
        assert len(out.children) == 1
        assert out.children[0] is first
        assert "two" in first.value

    def test_update_display_keeps_other_outputs(self):
        out = Output()
        with out:
            display("keep")
            display("old", display_id="slot")
            update_display("new", display_id="slot")
        assert len(out.children) == 2
        assert "keep" in out.children[0].value
        assert "new" in out.children[1].value

    def test_update_without_display_id_raises(self):
        with pytest.raises(ValueError, match="display_id"):
            display("x", update=True)

    def test_stream_context_groups_errors_but_not_regular_display(self):
        stream = Output()
        regular = Output()

        with regular:
            # Regular Output context still takes ordinary display().
            with stream_context(stream):
                display(widgets.Label("regular"))
                from tkipw.output import display_error

                display_error("boom")

        assert len(regular.children) == 1
        assert regular.children[0].value == "regular"
        assert len(stream.children) == 1
        assert "boom" in stream.children[0].value

    def test_clear_output_clears_stream_context(self):
        stream = Output()
        with stream_context(stream):
            from tkipw.output import display_error

            display_error("old")
            clear_output()
        assert stream.children == ()


class TestDisplayLogging:
    def _handler_count(self) -> int:
        root = logging.getLogger()
        return sum(1 for h in root.handlers if isinstance(h, DisplayLogHandler))

    def test_install_uninstall_toggles_root_handler(self):
        uninstall_display_logging()
        assert self._handler_count() == 0

        install_display_logging()
        assert self._handler_count() == 1
        install_display_logging()  # idempotent
        assert self._handler_count() == 1

        uninstall_display_logging()
        assert self._handler_count() == 0


class TestExcepthook:
    def test_install_uninstall_restores_previous(self):
        uninstall_excepthook()
        original = sys.excepthook

        install_excepthook()
        assert sys.excepthook is not original

        uninstall_excepthook()
        assert sys.excepthook is original
