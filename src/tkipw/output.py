"""Notebook-like ``display`` / ``clear_output`` / ``Output`` for tkipw.

This is the generic “area under the cell”: matplotlib, HTML, widgets, etc. all
go through the same path — nothing matplotlib-specific in the App shell.

``ipywidgets`` is imported lazily so ``import tkipw.app`` / ``App()`` shell
create does not pay that cost until ``Output`` / ``display`` / ``to_widget``.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import sys
import traceback
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Any

MimeRenderer = Callable[[Any], str | None]

# Stack of active output targets (``Output`` widgets). Empty → App default area.
_output_stack: list[Any] = []
# Separate stack for stdout/stderr/errors/logging. Unlike ``_output_stack``,
# this does not capture ordinary ``display()`` calls.
_stream_output_stack: list[Any] = []
_logging_installed = False
_excepthook_installed = False
_log_handler: DisplayLogHandler | None = None
_prev_excepthook: Any | None = None
_OutputClass: type | None = None

_ERROR_STYLE = "padding:8px 10px;border-radius:4px;overflow:auto;white-space:pre-wrap"
_STDERR_STYLE = _ERROR_STYLE

# Jupyter-like MIME preference. User-registered types sit after HTML/Markdown
# and before raster/JSON/plain so a custom chart MIME wins over JSON dumps.
_BUILTIN_MIME_BEFORE: tuple[str, ...] = ("text/html", "text/markdown")
_BUILTIN_MIME_AFTER: tuple[str, ...] = (
    "image/svg+xml",
    "image/png",
    "image/jpeg",
    "application/json",
    "text/plain",
)
_builtin_mime_renderers: dict[str, MimeRenderer] = {}
_user_mime_renderers: OrderedDict[str, MimeRenderer] = OrderedDict()


def _widgets() -> Any:
    from .comm_backend import _ensure_widget_open_patch

    _ensure_widget_open_patch()
    import ipywidgets as widgets

    return widgets


def _is_widget(obj: Any) -> bool:
    # Cheap reject before importing ipywidgets (render_html of plain objects).
    if not hasattr(obj, "model_id"):
        return False
    from ipywidgets import Widget

    return isinstance(obj, Widget)


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
    if _is_widget(obj):
        value = getattr(obj, "value", None)
        if isinstance(value, str):
            return value
        return f"<pre>{_escape(repr(obj))}</pre>"

    html = _call_repr(obj, "_repr_html_")
    if html is not None:
        return str(html)

    markdown = _call_repr(obj, "_repr_markdown_")
    if markdown is not None:
        return _render_markdown(str(markdown))

    mime = getattr(obj, "_repr_mimebundle_", None)
    if callable(mime):
        try:
            data = mime(include=None, exclude=None)
            if isinstance(data, tuple):
                data = data[0]
            if isinstance(data, dict):
                html = _render_mimebundle(data)
                if html is not None:
                    return html
        except Exception:
            pass

    svg = _call_repr(obj, "_repr_svg_")
    if svg is not None:
        return _render_svg(svg)
    png = _call_repr(obj, "_repr_png_")
    if png is not None:
        return _render_raster("image/png", png)
    jpeg = _call_repr(obj, "_repr_jpeg_")
    if jpeg is not None:
        return _render_raster("image/jpeg", jpeg)
    data = _call_repr(obj, "_repr_json_")
    if data is not None:
        return _render_json(data)

    if isinstance(obj, str):
        return f'<pre class="tkipw-stream tkipw-stdout">{_escape(obj)}</pre>'

    return f'<pre class="tkipw-stream tkipw-stdout">{_escape(repr(obj))}</pre>'


def _call_repr(obj: Any, name: str) -> Any | None:
    fn = getattr(obj, name, None)
    if not callable(fn):
        return None
    try:
        return fn()
    except Exception:
        return None


def register_mime_renderer(mime: str, renderer: MimeRenderer) -> None:
    """Register a ``_repr_mimebundle_`` MIME type that returns an HTML fragment.

    Built-in types keep their Jupyter-like priority; passing one replaces only
    the callable. New types are tried after ``text/html`` / ``text/markdown``
    and before images, JSON, and ``text/plain``. Return ``None`` to fall through.
    """
    key = _normalize_mime(mime)
    if not callable(renderer):
        raise TypeError("renderer must be callable")
    _ensure_builtin_mime_renderers()
    if key in _builtin_mime_renderers:
        _builtin_mime_renderers[key] = renderer
        return
    _user_mime_renderers[key] = renderer


def unregister_mime_renderer(mime: str) -> None:
    """Drop a user MIME renderer, or restore a replaced built-in."""
    key = _normalize_mime(mime)
    _user_mime_renderers.pop(key, None)
    if key in _BUILTIN_MIME_BEFORE or key in _BUILTIN_MIME_AFTER:
        _ensure_builtin_mime_renderers()
        _builtin_mime_renderers[key] = _default_builtin_mime_renderers()[key]


def _normalize_mime(mime: str) -> str:
    if not isinstance(mime, str) or not mime.strip():
        raise ValueError("mime type must be a non-empty string")
    return mime.strip()


def _default_builtin_mime_renderers() -> dict[str, MimeRenderer]:
    return {
        "text/html": lambda raw: str(raw),
        "text/markdown": lambda raw: _render_markdown(str(raw)),
        "image/svg+xml": _render_svg,
        "image/png": lambda raw: _render_raster("image/png", raw),
        "image/jpeg": lambda raw: _render_raster("image/jpeg", raw),
        "application/json": _render_json,
        "text/plain": lambda raw: f"<pre>{_escape(str(raw))}</pre>",
    }


def _ensure_builtin_mime_renderers() -> None:
    if _builtin_mime_renderers:
        return
    _builtin_mime_renderers.update(_default_builtin_mime_renderers())


def _iter_mime_renderers() -> Iterator[tuple[str, MimeRenderer]]:
    _ensure_builtin_mime_renderers()
    for mime in _BUILTIN_MIME_BEFORE:
        yield mime, _builtin_mime_renderers[mime]
    yield from _user_mime_renderers.items()
    for mime in _BUILTIN_MIME_AFTER:
        yield mime, _builtin_mime_renderers[mime]


def _render_mimebundle(data: dict[str, Any]) -> str | None:
    """Pick a Jupyter-like MIME from *data* and return an HTML fragment."""
    for mime, renderer in _iter_mime_renderers():
        if mime not in data:
            continue
        try:
            html = renderer(data[mime])
        except Exception:
            continue
        if html is not None:
            return html
    return None


def _render_raster(mime: str, raw: Any) -> str:
    if not isinstance(raw, str):
        raw = base64.b64encode(bytes(raw)).decode("ascii")
    return f'<img style="max-width:100%;height:auto" src="data:{mime};base64,{raw}"/>'


def _render_svg(raw: Any) -> str:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            b64 = base64.b64encode(raw).decode("ascii")
            return (
                '<img style="max-width:100%;height:auto" '
                f'src="data:image/svg+xml;base64,{b64}"/>'
            )
    else:
        text = str(raw)
    stripped = text.lstrip()
    if stripped.startswith("<"):
        return f'<div class="tkipw-svg" style="max-width:100%">{stripped}</div>'
    return (
        '<img style="max-width:100%;height:auto" '
        f'src="data:image/svg+xml;base64,{text}"/>'
    )


def _render_json(raw: Any) -> str:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return f'<pre class="tkipw-json">{_escape(raw)}</pre>'
    text = json.dumps(raw, indent=2, ensure_ascii=False, default=str)
    return f'<pre class="tkipw-json">{_escape(text)}</pre>'


def _render_markdown(source: str) -> str:
    """Convert Jupyter ``text/markdown`` into a themed HTML fragment."""
    import markdown

    body = markdown.markdown(
        source,
        extensions=["extra", "sane_lists"],
        output_format="html5",
    )
    return f'<article class="tkipw-markdown">{body}</article>'


def to_widget(obj: Any) -> Any:
    """Apply Jupyter extensions, then convert an object to a Widget.

    This is the single display gateway used by ``tkipw.display``,
    ``App.display`` and the IPython display bridge.
    """
    from .jupyter import transform_display_object

    widgets = _widgets()
    obj = transform_display_object(obj)
    if _is_widget(obj):
        return obj
    return widgets.HTML(value=render_html(obj))


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def display_error(text: str, *, kind: str = "error") -> None:
    """Show an error / stderr message in the active output area."""
    widgets = _widgets()
    display_stream(widgets.HTML(value=error_html(text, kind=kind)))


def _current_output() -> Any | None:
    return _output_stack[-1] if _output_stack else None


def _current_stream_output() -> Any | None:
    return _stream_output_stack[-1] if _stream_output_stack else None


class DisplayHandle:
    """Notebook-like handle for updating a previous ``display()``."""

    def __init__(self, display_id: str) -> None:
        self.display_id = display_id

    def update(self, *objs: Any) -> None:
        display(*objs, display_id=self.display_id, update=True)

    def display(self, *objs: Any) -> None:
        display(*objs, display_id=self.display_id, update=False)


def _resolve_display_id(display_id: str | bool | None) -> str | None:
    if display_id is True:
        return str(uuid.uuid4())
    if display_id is False or display_id is None:
        return None
    return str(display_id)


def display_stream(*objs: Any) -> None:
    """Display stdout/stderr/error/logging, honoring a stream-only target."""
    target = _current_stream_output()
    if target is not None:
        target._append([to_widget(o) for o in objs])
        return
    display(*objs)


def display(
    *objs: Any,
    display_id: str | bool | None = None,
    update: bool = False,
    **_ignored: Any,
) -> DisplayHandle | None:
    """Send objects to the active notebook-style output area or a pop-up window.

    Prefer an ``Output`` context; otherwise follow :func:`get_display_mode`:

    * ``inline`` — App default output area
    * ``window`` — a new Tk ``Toplevel`` per call (or the existing one when
      ``update=True`` and ``display_id`` matches)

    ``display_id=True`` allocates an id and returns a :class:`DisplayHandle`.
    ``handle.update(obj)`` replaces that output in place.
    """
    from .comm_backend import get_bridge
    from .display_mode import (
        display_title_for,
        get_display_mode,
        open_display_window,
    )

    slot = _resolve_display_id(display_id)
    if update and slot is None:
        raise ValueError("update=True requires display_id")
    handle = DisplayHandle(slot) if slot is not None else None
    if not objs:
        return handle

    converted = [to_widget(o) for o in objs]
    target = _current_output()
    if target is not None:
        target._append(converted, display_id=slot, update=update)
        return handle

    if get_display_mode() == "window":
        app = get_bridge()
        if (
            update
            and slot is not None
            and _update_display_window(app, converted, display_id=slot)
        ):
            return handle
        prefix = str(getattr(app, "title", None) or "tkipw") if app else "tkipw"
        if len(objs) == 1:
            title = display_title_for(objs[0], app_title=prefix)
        else:
            title = f"{prefix} · output"
        open_display_window(
            *converted,
            title=title,
            sources=objs,
            display_id=slot,
        )
        return handle

    app = get_bridge()
    if app is None:
        raise RuntimeError("display() requires an active tkipw App (or Output context)")
    app._append_output(converted, display_id=slot, update=update)
    return handle


def update_display(*objs: Any, display_id: str, **kwargs: Any) -> None:
    """Replace a previous ``display(..., display_id=)`` output."""
    kwargs.pop("update", None)
    display(*objs, display_id=display_id, update=True, **kwargs)


def _update_display_window(
    host: Any,
    items: list[Any],
    *,
    display_id: str,
) -> bool:
    """Update an existing window-mode pop-up. Return False if none is open."""
    if host is None:
        return False
    handles = getattr(host, "_display_id_windows", None) or {}
    popup = handles.get(display_id)
    if popup is None or getattr(popup, "_destroyed", False):
        return False
    tracked = getattr(popup, "_tracked_output", None)
    if tracked is None:
        return False
    tracked._append(items, display_id=display_id, update=True)
    return True


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


def _ensure_output_class() -> type:
    """Build ``Output`` on first use (subclasses ``ipywidgets.VBox``)."""
    global _OutputClass
    if _OutputClass is not None:
        return _OutputClass

    widgets = _widgets()

    class Output(widgets.VBox):
        """Notebook-like output region (``display`` / ``plt.show`` capture target)."""

        def __init__(self, **kwargs: Any) -> None:
            kwargs.setdefault("layout", widgets.Layout(width="100%"))
            super().__init__(children=(), **kwargs)
            self._wait_clear = False
            self._id_widgets: dict[str, tuple[Any, ...]] = {}

        def clear_output(self, wait: bool = False) -> None:
            if wait:
                self._wait_clear = True
                return
            self._wait_clear = False
            self._id_widgets.clear()
            self.children = ()

        def _append(
            self,
            items: list[Any],
            *,
            display_id: str | None = None,
            update: bool = False,
        ) -> None:
            if self._wait_clear:
                self._id_widgets.clear()
                self.children = tuple(items)
                self._wait_clear = False
                if display_id:
                    self._id_widgets[display_id] = tuple(items)
                return
            if display_id and update:
                old = self._id_widgets.get(display_id)
                if old and self._replace_span(old, items):
                    html_inplace = (
                        len(old) == 1
                        and len(items) == 1
                        and isinstance(old[0], widgets.HTML)
                        and isinstance(items[0], widgets.HTML)
                    )
                    self._id_widgets[display_id] = old if html_inplace else tuple(items)
                    return
            self.children = tuple(self.children) + tuple(items)
            if display_id:
                self._id_widgets[display_id] = tuple(items)

        def _replace_span(self, old: tuple[Any, ...], new: list[Any]) -> bool:
            if (
                len(old) == 1
                and len(new) == 1
                and isinstance(old[0], widgets.HTML)
                and isinstance(new[0], widgets.HTML)
            ):
                old[0].value = new[0].value
                return True
            children = list(self.children)
            n = len(old)
            if n == 0:
                return False
            for i in range(len(children) - n + 1):
                if tuple(children[i : i + n]) == old:
                    self.children = tuple(children[:i] + list(new) + children[i + n :])
                    return True
            return False

        def __enter__(self) -> Any:
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

    _OutputClass = Output
    return Output


def __getattr__(name: str) -> Any:
    if name == "Output":
        return _ensure_output_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@contextmanager
def output_context(out: Any) -> Iterator[Any]:
    """Explicit context manager alias for ``with Output():``."""
    with out:
        yield out


@contextmanager
def stream_context(out: Any) -> Iterator[Any]:
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
