"""Altair adapter: host Vega-Lite's complete HTML document in an iframe."""

from __future__ import annotations

from typing import Any

from ..html_host import host_html_document

# Vega-Lite width/height describe the *data rectangle*. Axes, title, and
# embed chrome sit outside that box — window / iframe sizing must include them.
_AXIS_PAD_W = 72
_AXIS_PAD_H = 56
_TITLE_PAD_H = 36


def chart_pixels(obj: Any) -> tuple[int, int]:
    """Read ``.properties(width=…, height=…)`` when they are concrete pixels."""
    width = getattr(obj, "width", None)
    height = getattr(obj, "height", None)
    try:
        w = int(width) if width is not None and width != "container" else 480
    except (TypeError, ValueError):
        w = 480
    try:
        h = int(height) if height is not None else 320
    except (TypeError, ValueError):
        h = 320
    return max(w, 120), max(h, 120)


def window_frame_size(obj: Any) -> tuple[int, int]:
    """Tk / iframe pixel size that fits the rendered Vega view."""
    width_px, height_px = chart_pixels(obj)
    title = getattr(obj, "title", None)
    has_title = bool(title) and title not in ("", None)
    pad_h = _AXIS_PAD_H + (_TITLE_PAD_H if has_title else 0)
    return width_px + _AXIS_PAD_W, height_px + pad_h


def _window_document(document: str) -> str:
    """Shrink-wrap the embed to the SVG (avoid ``width:100%`` flex stretch)."""
    override = (
        "<style>"
        "html,body{margin:0;padding:0;overflow:hidden;background:#fff;}"
        "#vis.vega-embed{width:fit-content!important;display:block;}"
        "</style>"
    )
    if "</head>" in document:
        return document.replace("</head>", override + "</head>", 1)
    return override + document


class AltairExtension:
    """Render Altair charts through their official standalone HTML export.

    * **window** — iframe matches the chart's pixel size plus axis/title chrome
    * **inline** — export with ``width="container"`` so the chart fills the pane
    """

    name = "altair"

    def setup(self) -> None:
        # Importing validates availability; Altair needs no global patch.
        import altair  # noqa: F401

    def transform(self, obj: Any) -> Any:
        module = type(obj).__module__ or ""
        to_html = getattr(obj, "to_html", None)
        if not module.startswith("altair.") or not callable(to_html):
            return obj

        import ipywidgets as widgets

        from ..display_mode import get_display_mode

        _width_px, height_px = chart_pixels(obj)

        if get_display_mode() == "inline":
            # Fill the output pane; keep the author's height.
            export = obj.properties(width="container", height=height_px)
            document = export.to_html()
            iframe_w = "100%"
            iframe_h = f"{height_px + _AXIS_PAD_H + _TITLE_PAD_H}px"
        else:
            document = _window_document(to_html())
            win_w, win_h = window_frame_size(obj)
            iframe_w = f"{win_w}px"
            iframe_h = f"{win_h}px"

        return widgets.HTML(
            value=host_html_document(
                document,
                width=iframe_w,
                height=iframe_h,
                title="Altair chart",
            )
        )


def enable_altair() -> None:
    """Enable Altair chart display."""
    from ..jupyter import register_extension

    register_extension(AltairExtension())
