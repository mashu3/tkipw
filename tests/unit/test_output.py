"""``tkipw.output``: notebook-like display, Output areas, and global patches.

No WebView required. Extension-driven transforms (e.g. matplotlib) are covered
in ``test_extensions.py``; this module tests the plain output primitives plus
the display-logging / excepthook install/uninstall lifecycle.
"""

from __future__ import annotations

import logging
import sys

import ipywidgets as widgets
from IPython.display import HTML, Markdown

from tkipw.output import (
    DisplayLogHandler,
    Output,
    clear_output,
    display,
    error_html,
    install_display_logging,
    install_excepthook,
    render_html,
    stream_context,
    to_widget,
    uninstall_display_logging,
    uninstall_excepthook,
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
