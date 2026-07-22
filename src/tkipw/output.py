"""Notebook-like ``display`` / ``clear_output`` / ``Output`` for tkipw.

This is the generic “area under the cell”: matplotlib, HTML, widgets, etc. all
go through the same path — nothing matplotlib-specific in the App shell.
"""

from __future__ import annotations

import base64
import io
import logging
import sys
import traceback
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Any

import ipywidgets as widgets
import markdown
from ipywidgets import Widget

# Stack of active output targets (``Output`` widgets). Empty → App default area.
_output_stack: list[Output] = []
# Separate stack for stdout/stderr/errors/logging. Unlike ``_output_stack``,
# this does not capture ordinary ``display()`` calls.
_stream_output_stack: list[Output] = []
_logging_installed = False
_excepthook_installed = False
_log_handler: DisplayLogHandler | None = None
_prev_excepthook: Any | None = None

_ERROR_STYLE = "padding:8px 10px;border-radius:4px;overflow:auto;white-space:pre-wrap"
_STDERR_STYLE = _ERROR_STYLE


def error_html(text: str, *, kind: str = "error") -> str:
    """Notebook-like error / stderr block (escaped HTML).

    Colors come from App shell CSS (``.tkipw-error`` / ``.tkipw-stderr``) so
    light/dark themes can restyle without regenerating the fragment.
    """
    css = "tkipw-stderr" if kind == "stderr" else "tkipw-error"
    # Keep a little layout inline; colors live in the shell theme variables.
    return (
        f'<pre class="tkipw-stream {css}" style="{_ERROR_STYLE}">'
        f"{_escape(text.rstrip())}</pre>"
    )


def render_html(obj: Any) -> str:
    """Serialize ``obj`` to an HTML fragment (no Widget / Comm — thread-safe)."""
    if isinstance(obj, Widget):
        value = getattr(obj, "value", None)
        if isinstance(value, str):
            return value
        return f"<pre>{_escape(repr(obj))}</pre>"

    repr_html = getattr(obj, "_repr_html_", None)
    if callable(repr_html):
        try:
            html = repr_html()
            if html is not None:
                return str(html)
        except Exception:
            pass

    repr_markdown = getattr(obj, "_repr_markdown_", None)
    if callable(repr_markdown):
        try:
            source = repr_markdown()
            if source is not None:
                return _render_markdown(str(source))
        except Exception:
            pass

    mime = getattr(obj, "_repr_mimebundle_", None)
    if callable(mime):
        try:
            data = mime(include=None, exclude=None)
            if isinstance(data, tuple):
                data = data[0]
            if isinstance(data, dict):
                if "text/html" in data:
                    return str(data["text/html"])
                if "text/markdown" in data:
                    return _render_markdown(str(data["text/markdown"]))
                if "image/png" in data:
                    raw = data["image/png"]
                    if not isinstance(raw, str):
                        raw = base64.b64encode(raw).decode("ascii")
                    return (
                        '<img style="max-width:100%;height:auto" '
                        f'src="data:image/png;base64,{raw}"/>'
                    )
                if "text/plain" in data:
                    return f"<pre>{_escape(str(data['text/plain']))}</pre>"
        except Exception:
            pass

    if isinstance(obj, str):
        return f'<pre class="tkipw-stream tkipw-stdout">{_escape(obj)}</pre>'

    return f'<pre class="tkipw-stream tkipw-stdout">{_escape(repr(obj))}</pre>'


def _render_markdown(source: str) -> str:
    """Convert Jupyter ``text/markdown`` into a themed HTML fragment."""
    body = markdown.markdown(
        source,
        extensions=["extra", "sane_lists"],
        output_format="html5",
    )
    return f'<article class="tkipw-markdown">{body}</article>'


def to_widget(obj: Any) -> Widget:
    """Apply Jupyter extensions, then convert an object to a Widget.

    This is the single display gateway used by ``tkipw.display``,
    ``App.display`` and the IPython display bridge.
    """
    from .jupyter import transform_display_object

    obj = transform_display_object(obj)
    if isinstance(obj, Widget):
        return obj
    return widgets.HTML(value=render_html(obj))


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def display_error(text: str, *, kind: str = "error") -> None:
    """Show an error / stderr message in the active output area."""
    display_stream(widgets.HTML(value=error_html(text, kind=kind)))


def _current_output() -> Output | None:
    return _output_stack[-1] if _output_stack else None


def _current_stream_output() -> Output | None:
    return _stream_output_stack[-1] if _stream_output_stack else None


def display_stream(*objs: Any) -> None:
    """Display stdout/stderr/error/logging, honoring a stream-only target."""
    target = _current_stream_output()
    if target is not None:
        target._append([to_widget(o) for o in objs])
        return
    display(*objs)


def display(*objs: Any) -> None:
    """Send objects to the active notebook-style output area or a pop-up window.

    Prefer an ``Output`` context; otherwise follow :func:`get_display_mode`:

    * ``inline`` — App default output area
    * ``window`` — a new Tk ``Toplevel`` per call
    """
    from .comm_backend import get_bridge
    from .display_mode import (
        display_title_for,
        get_display_mode,
        open_display_window,
    )

    if not objs:
        return

    converted = [to_widget(o) for o in objs]
    target = _current_output()
    if target is not None:
        target._append(converted)
        return

    if get_display_mode() == "window":
        app = get_bridge()
        prefix = str(getattr(app, "title", None) or "tkipw") if app else "tkipw"
        if len(objs) == 1:
            title = display_title_for(objs[0], app_title=prefix)
        else:
            title = f"{prefix} · output"
        open_display_window(*converted, title=title, sources=objs)
        return

    app = get_bridge()
    if app is None:
        raise RuntimeError("display() requires an active tkipw App (or Output context)")
    app._append_output(converted)


def clear_output(wait: bool = False) -> None:
    """Clear the active output area (notebook ``clear_output``)."""
    from .comm_backend import get_bridge

    target = _current_output()
    if target is not None:
        target.clear_output(wait=wait)
        return

    stream_target = _current_stream_output()
    if stream_target is not None:
        stream_target.clear_output(wait=wait)
        return

    app = get_bridge()
    if app is None:
        return
    app._clear_output(wait=wait)


class Output(widgets.VBox):
    """Notebook-like output region (capture target for ``display`` / ``plt.show``)."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("layout", widgets.Layout(width="100%"))
        super().__init__(children=(), **kwargs)
        self._wait_clear = False

    def clear_output(self, wait: bool = False) -> None:
        if wait:
            self._wait_clear = True
            return
        self._wait_clear = False
        self.children = ()

    def _append(self, items: list[Widget]) -> None:
        if self._wait_clear:
            self.children = tuple(items)
            self._wait_clear = False
        else:
            self.children = tuple(self.children) + tuple(items)

    def __enter__(self) -> Output:
        _output_stack.append(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if _output_stack and _output_stack[-1] is self:
            _output_stack.pop()
        if exc is not None:
            self._append(
                [
                    widgets.HTML(
                        value=error_html(
                            "".join(traceback.format_exception(exc_type, exc, tb))
                        )
                    )
                ]
            )
        return False


@contextmanager
def output_context(out: Output) -> Iterator[Output]:
    """Explicit context manager alias for ``with Output():``."""
    with out:
        yield out


@contextmanager
def stream_context(out: Output) -> Iterator[Output]:
    """Capture only stdout/stderr/errors/logging, leaving ``display()`` alone."""
    _stream_output_stack.append(out)
    try:
        yield out
    finally:
        if _stream_output_stack and _stream_output_stack[-1] is out:
            _stream_output_stack.pop()


class DisplayLogHandler(logging.Handler):
    """Send log records into the notebook-style output area."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            kind = "error" if record.levelno >= logging.ERROR else "stderr"
            display_error(msg, kind=kind)
        except Exception:
            self.handleError(record)


def install_display_logging(level: int = logging.WARNING) -> DisplayLogHandler:
    """Attach a root logging handler that shows messages in the output area."""
    global _logging_installed, _log_handler
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, DisplayLogHandler):
            h.setLevel(level)
            _log_handler = h
            return h
    handler = DisplayLogHandler()
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    _logging_installed = True
    _log_handler = handler
    return handler


def uninstall_display_logging() -> None:
    """Remove the root logging handler installed by :func:`install_display_logging`."""
    global _logging_installed, _log_handler
    root = logging.getLogger()
    for h in [h for h in root.handlers if isinstance(h, DisplayLogHandler)]:
        root.removeHandler(h)
    _log_handler = None
    _logging_installed = False


def install_excepthook() -> None:
    """Show uncaught exceptions in the output area (and still print to stderr)."""
    global _excepthook_installed, _prev_excepthook
    if _excepthook_installed:
        return
    prev = sys.excepthook
    _prev_excepthook = prev

    def _hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            display_error(text)
        except Exception:
            pass
        prev(exc_type, exc, tb)

    sys.excepthook = _hook
    _excepthook_installed = True


def uninstall_excepthook() -> None:
    """Restore the previous ``sys.excepthook`` (undo :func:`install_excepthook`)."""
    global _excepthook_installed, _prev_excepthook
    if not _excepthook_installed:
        return
    if _prev_excepthook is not None:
        sys.excepthook = _prev_excepthook
    _prev_excepthook = None
    _excepthook_installed = False


@contextmanager
def capture_stdio(*, stdout: bool = True, stderr: bool = True) -> Iterator[None]:
    """Redirect stdout/stderr into the output area (notebook stream outputs)."""
    out_buf = io.StringIO()
    err_buf = io.StringIO()

    def _flush_out() -> None:
        text = out_buf.getvalue()
        out_buf.seek(0)
        out_buf.truncate(0)
        if text.strip():
            display_stream(text)

    def _flush_err() -> None:
        text = err_buf.getvalue()
        err_buf.seek(0)
        err_buf.truncate(0)
        if text.strip():
            display_error(text, kind="stderr")

    class _Out(io.TextIOBase):
        def write(self, s: str) -> int:
            out_buf.write(s)
            if "\n" in s:
                _flush_out()
            return len(s)

        def flush(self) -> None:
            _flush_out()

    class _Err(io.TextIOBase):
        def write(self, s: str) -> int:
            err_buf.write(s)
            if "\n" in s:
                _flush_err()
            return len(s)

        def flush(self) -> None:
            _flush_err()

    stack: list[Any] = []
    if stdout:
        stack.append(redirect_stdout(_Out()))
    if stderr:
        stack.append(redirect_stderr(_Err()))
    for cm in stack:
        cm.__enter__()
    try:
        yield
    finally:
        for cm in reversed(stack):
            cm.__exit__(None, None, None)
        _flush_out()
        _flush_err()
