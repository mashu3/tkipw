"""Per-App display mode: ``inline`` (notebook output) vs ``window`` (pop-ups).

* **inline** — ``display()`` / library ``show()`` routes into the active App's
  notebook-style output area (Playground default).
* **window** — each ``display()`` opens a separate Tk ``Toplevel`` with its own
  embedded WebView. Matplotlib is special-cased to native TkAgg figure windows
  (``%matplotlib tk`` style) instead of a WebView PNG.
"""

from __future__ import annotations

from typing import Any, Literal

DisplayMode = Literal["inline", "window"]

_default_display_mode: DisplayMode = "inline"
_window_serial = 0

# Readable default for Markdown documents / other unsized HTML output.
# Folium's common 60% aspect stays as the generic fallback below.
_MARKDOWN_WINDOW_SIZE = (720, 560)
_DEFAULT_WINDOW_SIZE = (720, 432)


def _cloak_window(win: Any) -> bool:
    """Hide *win* while keeping it mapped so an embedded WebView can load.

    ``withdraw()`` leaves geometry at 1×1 until first map, which blocks tkwry
    creation. Transparent ``-alpha`` avoids an empty flash on Windows/macOS.
    Returns whether cloaking succeeded.
    """
    try:
        win.attributes("-alpha", 0.0)
        return True
    except Exception:
        return False


def _reveal_window(win: Any) -> None:
    """Undo :func:`_cloak_window` and ensure the window is mapped."""
    try:
        win.attributes("-alpha", 1.0)
    except Exception:
        pass
    try:
        win.deiconify()
    except Exception:
        pass


def get_display_mode() -> DisplayMode:
    """Return the active App's display mode (``inline`` without an App)."""
    try:
        from .comm_backend import get_bridge

        app = get_bridge()
        mode = getattr(app, "display_mode", None)
        if mode in ("inline", "window"):
            return mode
    except Exception:
        pass
    return _default_display_mode


def set_display_mode(mode: DisplayMode) -> None:
    """Change the active App's mode at runtime.

    New code should normally pass ``display_mode=`` to :class:`tkipw.App`.
    When no App exists, this changes the default used by subsequently created
    Apps, preserving the standalone setter as a convenience API.
    """
    global _default_display_mode
    mode = validate_display_mode(mode)
    try:
        from .comm_backend import get_bridge

        app = get_bridge()
    except Exception:
        app = None
    if app is not None:
        app.display_mode = mode
        _sync_host_visibility(app)
    else:
        _default_display_mode = mode
    sync_matplotlib(mode)


def _sync_host_visibility(app: Any) -> None:
    """Hide an owned root in window mode; show it again for inline."""
    if not getattr(app, "_owns_root", False):
        return
    root = getattr(app, "root", None)
    if root is None:
        return
    try:
        if app.display_mode == "window":
            root.withdraw()
        else:
            root.deiconify()
    except Exception:
        pass


def validate_display_mode(mode: str) -> DisplayMode:
    """Validate and narrow a display-mode value."""
    if mode not in ("inline", "window"):
        raise ValueError(f"display mode must be 'inline' or 'window', got {mode!r}")
    return mode  # type: ignore[return-value]


def sync_matplotlib(mode: DisplayMode) -> None:
    """Keep the Matplotlib adapter aligned with the active App."""
    try:
        from .extensions.matplotlib import MatplotlibExtension
        from .jupyter import enable_extension, get_extension
    except Exception:
        return

    existing = get_extension("matplotlib")
    if isinstance(existing, MatplotlibExtension):
        existing.set_mode(mode)
        enable_extension(existing.name)


def open_display_window(
    *widgets: Any,
    title: str | None = None,
    width: int | None = None,
    height: int | None = None,
    sources: tuple[Any, ...] | list[Any] | None = None,
) -> Any:
    """Open a ``Toplevel`` hosting a fresh App and mount *widgets* in it.

    The previously active App is re-activated afterwards so the host remains
    the default bridge for subsequent ``display()`` calls. When the host owns
    a withdrawn root (window mode), closing the last pop-up quits the host.

    Window geometry prefers sizes declared on *sources* / *widgets* (Folium
    ``Map(width=…, height=…)``, Pillow images, Bokeh figures, …). Pop-ups use
    a compact shell with no padding so the content fills the frame.
    """
    import tkinter as tk

    from .app import App
    from .comm_backend import get_bridge

    host = get_bridge()
    if host is None:
        raise RuntimeError(
            "window display mode requires an active tkipw App "
            "(create App() before display())"
        )

    global _window_serial
    _window_serial += 1
    win_title = title or f"tkipw · window {_window_serial}"

    inferred = infer_window_size(*(sources or ()), *widgets)
    win_w = width if width is not None else inferred[0]
    win_h = height if height is not None else inferred[1]

    top = tk.Toplevel(host.root)
    # Cloak before the idle map so Windows does not flash an empty shell.
    cloaked = _cloak_window(top)
    top.title(win_title)
    # Keep large tables usable on the current monitor; compact tables retain
    # their natural inferred size.
    max_w = max(min(top.winfo_screenwidth() - 80, 1200), 320)
    max_h = max(min(top.winfo_screenheight() - 120, 800), 240)
    win_w = min(max(int(win_w), 180), max_w)
    win_h = min(max(int(win_h), 100), max_h)
    top.geometry(f"{win_w}x{win_h}")

    frame = tk.Frame(top)
    frame.pack(fill="both", expand=True)

    popup = App(
        parent=frame,
        title=win_title,
        width=win_w,
        height=win_h,
        display_mode="inline",
        compact=True,
    )

    windows: list[Any] = getattr(host, "_display_windows", None) or []
    host._display_windows = windows
    windows.append(popup)

    def _close() -> None:
        try:
            popup.destroy()
        finally:
            try:
                top.destroy()
            except tk.TclError:
                pass
            try:
                windows.remove(popup)
            except ValueError:
                pass
            # Window-mode host is withdrawn — quit when the last figure closes.
            if (
                getattr(host, "_owns_root", False)
                and getattr(host, "display_mode", None) == "window"
                and not windows
                and not getattr(host, "_destroyed", False)
            ):
                host.destroy()

    top.protocol("WM_DELETE_WINDOW", _close)
    if widgets:
        popup.display(*widgets)

    if cloaked:
        # Reveal after runtime ready + outbound flush (see App.when_ready).
        popup.when_ready(lambda: _reveal_window(top))

    # Keep the host App as the active bridge for the next display()/show().
    host.activate()
    return popup


def infer_window_size(*objs: Any) -> tuple[int, int]:
    """Best-effort pixel size from displayed objects (content wins over chrome)."""
    for obj in objs:
        size = _size_from_object(obj)
        if size is not None:
            return size
    return _DEFAULT_WINDOW_SIZE


def _size_from_object(obj: Any) -> tuple[int, int] | None:
    # Folium Map: (amount, unit) pairs.
    module = type(obj).__module__ or ""
    if module.startswith("folium"):
        return _folium_size(obj)

    # Altair chart properties(width=…, height=…).
    if module.startswith("altair"):
        return _altair_size(obj)

    # ipyleaflet is a live widget rather than hosted HTML. Its common layout
    # only declares height (width is 100%), so give window mode a useful width.
    if module.startswith("ipyleaflet"):
        return _ipyleaflet_size(obj)

    # IPython Markdown / any object that only exposes markdown (no pixel size).
    if _is_markdown_object(obj):
        return _MARKDOWN_WINDOW_SIZE

    # Pillow / anything with a raster ``size`` of ints.
    size = getattr(obj, "size", None)
    if (
        isinstance(size, tuple)
        and len(size) == 2
        and all(isinstance(v, int) for v in size)
        and size[0] > 0
        and size[1] > 0
    ):
        return int(size[0]), int(size[1])

    # Bokeh figures: canvas size + toolbar (outside width/height).
    if module.startswith("bokeh"):
        w = getattr(obj, "width", None)
        h = getattr(obj, "height", None)
        try:
            if w is not None and h is not None:
                from .extensions.bokeh import window_frame_size

                return window_frame_size(obj)
        except (TypeError, ValueError):
            pass

    # ipywidgets HTML: prefer fixed iframe dimensions in the markup.
    value = getattr(obj, "value", None)
    if isinstance(value, str):
        parsed = _size_from_html(value)
        if parsed is not None:
            return parsed

    # Layout traits in pixels (rare, but cheap to check).
    layout = getattr(obj, "layout", None)
    if layout is not None:
        parsed = _size_from_layout(layout)
        if parsed is not None:
            return parsed

    return None


def _altair_size(obj: Any) -> tuple[int, int] | None:
    width = getattr(obj, "width", None)
    height = getattr(obj, "height", None)
    try:
        w = int(width) if width is not None and width != "container" else None
        h = int(height) if height is not None else None
    except (TypeError, ValueError):
        return None
    if w is None and h is None:
        return None
    from .extensions.altair import window_frame_size

    return window_frame_size(obj)


def _folium_size(obj: Any) -> tuple[int, int] | None:
    width = _dim_pair(getattr(obj, "width", None))
    height = _dim_pair(getattr(obj, "height", None))
    if width is None:
        return None
    w_amt, w_unit = width
    if w_unit == "px":
        win_w = max(int(w_amt), 200)
    else:
        win_w = 720

    if height is not None:
        h_amt, h_unit = height
        if h_unit == "px":
            return win_w, max(int(h_amt), 160)
        if h_unit == "%":
            # Folium's notebook HTML uses padding-bottom:60% for the common
            # ``height="100%"`` default — treat that as the 60% aspect box,
            # not a square window.
            ratio = 0.6 if h_amt >= 100 else (h_amt / 100.0)
            return win_w, max(int(win_w * ratio), 160)

    # Notebook HTML uses padding-bottom: 60% when height is not absolute.
    return win_w, max(int(win_w * 0.6), 160)


def _ipyleaflet_size(obj: Any) -> tuple[int, int]:
    layout = getattr(obj, "layout", None)
    if layout is None:
        return 720, 480

    def px(value: Any) -> int | None:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.endswith("px"):
            try:
                return int(float(value[:-2]))
            except ValueError:
                return None
        return None

    width = px(getattr(layout, "width", None)) or 720
    height = px(getattr(layout, "height", None)) or 480
    return max(width, 320), max(height, 240)


def _dim_pair(value: Any) -> tuple[float, str] | None:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            return float(value[0]), str(value[1])
        except (TypeError, ValueError):
            return None
    if isinstance(value, (int, float)):
        return float(value), "px"
    return None


def _is_markdown_object(obj: Any) -> bool:
    """Return True for IPython Markdown (and similar) display objects."""
    name = type(obj).__name__
    module = type(obj).__module__ or ""
    if name == "Markdown" and (
        module.startswith("IPython") or module.endswith(".display")
    ):
        return True
    # Prefer explicit markdown over HTML when both exist.
    if callable(getattr(obj, "_repr_markdown_", None)) and not callable(
        getattr(obj, "_repr_html_", None)
    ):
        return True
    return False


def _size_from_html(html: str) -> tuple[int, int] | None:
    import re

    # Rendered Markdown may contain tables; those must not shrink the window
    # to the table's natural size — use a document-sized fallback instead.
    if 'class="tkipw-markdown"' in html or "class='tkipw-markdown'" in html:
        return _MARKDOWN_WINDOW_SIZE

    table = _size_from_table_html(html)
    if table is not None:
        return table

    # Fixed hosted iframe: style="width:800px;height:400px"
    match = re.search(
        r'style="[^"]*width:\s*(\d+)px[^"]*height:\s*(\d+)px',
        html,
        re.IGNORECASE,
    )
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(
        r'style="[^"]*height:\s*(\d+)px[^"]*width:\s*(\d+)px',
        html,
        re.IGNORECASE,
    )
    if match:
        return int(match.group(2)), int(match.group(1))

    # Folium notebook embed: padding-bottom:60% at full width.
    pad = re.search(r"padding-bottom:\s*(\d+(?:\.\d+)?)%", html, re.IGNORECASE)
    if pad:
        return 720, max(int(720 * float(pad.group(1)) / 100.0), 160)
    return None


def _size_from_table_html(html: str) -> tuple[int, int] | None:
    """Estimate a natural window size from the rendered HTML table cells."""
    import html as html_lib
    import re
    import unicodedata

    if not re.search(r"<table\b", html, re.IGNORECASE):
        return None

    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL)
    if not rows:
        return None

    parsed: list[list[str]] = []
    for row in rows:
        cells = re.findall(
            r"<(?:th|td)\b[^>]*>(.*?)</(?:th|td)>",
            row,
            re.IGNORECASE | re.DOTALL,
        )
        parsed.append(
            [
                html_lib.unescape(
                    re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell))
                ).strip()
                for cell in cells
            ]
        )

    columns = max((len(row) for row in parsed), default=0)
    if columns == 0:
        return None

    def display_units(text: str) -> int:
        return sum(
            2 if unicodedata.east_asian_width(char) in {"W", "F", "A"} else 1
            for char in text
        )

    widths: list[int] = []
    for index in range(columns):
        longest = max(
            (display_units(row[index]) for row in parsed if index < len(row)),
            default=1,
        )
        # Approximate browser font metrics plus cell padding. Very long values
        # are capped per column; the table/window then scrolls.
        widths.append(min(max(longest * 7 + 24, 52), 280))

    # 12px compact-shell padding on each side; row height includes borders.
    desired_width = sum(widths) + 24
    desired_height = len(rows) * 30 + 24
    return min(max(desired_width, 180), 1100), min(max(desired_height, 100), 720)


def _size_from_layout(layout: Any) -> tuple[int, int] | None:
    def px(value: Any) -> int | None:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.endswith("px"):
            try:
                return int(float(value[:-2]))
            except ValueError:
                return None
        return None

    w = px(getattr(layout, "width", None))
    h = px(getattr(layout, "height", None))
    if w and h:
        return w, h
    return None


def display_title_for(obj: Any) -> str:
    """Best-effort window title from a displayed object."""
    name = type(obj).__name__
    module = (type(obj).__module__ or "").split(".", 1)[0]
    if module and module not in {"builtins", "ipywidgets"}:
        return f"tkipw · {module} · {name}"
    return f"tkipw · {name}"
