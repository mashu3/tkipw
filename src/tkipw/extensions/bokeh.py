"""Bokeh adapter: route ``show()`` to a hosted standalone document."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..html_host import host_html_document

# Bokeh's figure width/height cover the canvas (axes + title), not the toolbar.
# See: https://docs.bokeh.org/en/latest/docs/user_guide/styling/plots.html
_TOOLBAR_PAD = 36
_DOC_PAD = 2


def _is_bokeh_object(obj: Any) -> bool:
    from bokeh.document import Document
    from bokeh.model import Model

    return isinstance(obj, (Model, Document))


def chart_pixels(obj: Any) -> tuple[int, int]:
    """Read concrete ``width`` / ``height`` from a Bokeh model when available."""
    width = getattr(obj, "width", None)
    height = getattr(obj, "height", None)
    try:
        w = int(width) if width is not None else 640
    except (TypeError, ValueError):
        w = 640
    try:
        h = int(height) if height is not None else 400
    except (TypeError, ValueError):
        h = 400
    return max(w, 120), max(h, 120)


def window_frame_size(obj: Any) -> tuple[int, int]:
    """Tk / iframe size that fits the rendered figure including its toolbar."""
    width_px, height_px = chart_pixels(obj)
    location = getattr(obj, "toolbar_location", None)
    if location in ("left", "right"):
        return width_px + _TOOLBAR_PAD + _DOC_PAD, height_px + _DOC_PAD
    if location in ("above", "below"):
        return width_px + _DOC_PAD, height_px + _TOOLBAR_PAD + _DOC_PAD
    return width_px + _DOC_PAD, height_px + _DOC_PAD


def _window_document(document: str) -> str:
    """Avoid ``body { height:100% }`` stretching the plot inside the iframe."""
    override = (
        "<style>"
        "html,body{margin:0;padding:0;overflow:hidden;"
        "height:auto!important;background:#fff;}"
        ".bk-root{height:auto!important;}"
        "</style>"
    )
    if "</head>" in document:
        return document.replace("</head>", override + "</head>", 1)
    return override + document


class BokehExtension:
    """Render Bokeh models and patch the common ``bokeh.*.show`` entry points."""

    name = "bokeh"

    def __init__(self) -> None:
        self._setup = False
        self._original_shows: dict[str, Callable[..., Any]] = {}

    def setup(self) -> None:
        if self._setup:
            return

        import bokeh.io
        import bokeh.io.showing
        import bokeh.plotting

        self._original_shows = {
            "showing": bokeh.io.showing.show,
            "with_state": bokeh.io.showing._show_with_state,
            "io": bokeh.io.show,
            "plotting": bokeh.plotting.show,
        }
        original = bokeh.io.showing.show
        original_with_state = bokeh.io.showing._show_with_state

        def show(obj: Any, *args: Any, **kwargs: Any) -> Any:
            if not _is_bokeh_object(obj):
                return original(obj, *args, **kwargs)
            from ..output import display

            display(obj)
            return None

        def show_with_state(
            obj: Any,
            state: Any,
            browser: Any,
            new: Any,
            notebook_handle: bool = False,
        ) -> Any:
            if not _is_bokeh_object(obj):
                return original_with_state(
                    obj,
                    state,
                    browser,
                    new,
                    notebook_handle=notebook_handle,
                )
            from ..output import display

            display(obj)
            return None

        bokeh.io.showing.show = show
        # Pre-imported ``from bokeh.plotting import show`` still resolves this
        # module-global delegate at call time, so it is safe before App().
        bokeh.io.showing._show_with_state = show_with_state
        bokeh.io.show = show
        bokeh.plotting.show = show
        self._setup = True

    def teardown(self) -> None:
        if not self._setup:
            return
        import bokeh.io
        import bokeh.io.showing
        import bokeh.plotting

        bokeh.io.showing.show = self._original_shows["showing"]
        bokeh.io.showing._show_with_state = self._original_shows["with_state"]
        bokeh.io.show = self._original_shows["io"]
        bokeh.plotting.show = self._original_shows["plotting"]
        self._original_shows.clear()
        self._setup = False

    def transform(self, obj: Any) -> Any:
        if not _is_bokeh_object(obj):
            return obj

        import ipywidgets as widgets
        from bokeh.embed import file_html
        from bokeh.resources import CDN

        from ..display_mode import get_display_mode

        inline = get_display_mode() == "inline"
        restore: tuple[Any, Any] | None = None
        if inline and hasattr(obj, "sizing_mode"):
            restore = (obj.sizing_mode, getattr(obj, "width", None))
            # Stretch to the output pane while keeping the author's height.
            obj.sizing_mode = "stretch_width"

        try:
            document = file_html(obj, CDN, title="Bokeh plot")
            if inline:
                _w, height_px = chart_pixels(obj)
                location = getattr(obj, "toolbar_location", None)
                pad_h = _TOOLBAR_PAD if location in ("above", "below") else 0
                return widgets.HTML(
                    value=host_html_document(
                        document,
                        width="100%",
                        height=f"{height_px + pad_h + _DOC_PAD}px",
                        title="Bokeh plot",
                    )
                )

            document = _window_document(document)
            win_w, win_h = window_frame_size(obj)
            return widgets.HTML(
                value=host_html_document(
                    document,
                    width=f"{win_w}px",
                    height=f"{win_h}px",
                    title="Bokeh plot",
                )
            )
        finally:
            if restore is not None:
                obj.sizing_mode, prev_width = restore
                if prev_width is not None:
                    obj.width = prev_width


def enable_bokeh() -> None:
    """Enable Bokeh model display and the ``show()`` bridge."""
    from ..jupyter import register_extension

    register_extension(BokehExtension())
