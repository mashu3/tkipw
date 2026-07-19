"""Folium adapter: prefer the map's declared size over notebook aspect-ratio HTML."""

from __future__ import annotations

from typing import Any


def _size_pair(value: Any) -> tuple[float, str] | None:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        amount, unit = value
        try:
            return float(amount), str(unit)
        except (TypeError, ValueError):
            return None
    if isinstance(value, (int, float)):
        return float(value), "px"
    return None


class FoliumExtension:
    """Render Folium maps using their declared pixel size when available.

    Folium's notebook ``_repr_html_`` always uses a responsive
    ``padding-bottom: 60%`` box. In a desktop pop-up that leaves empty bands
    and ignores ``Map(width=…, height=…)``. When both dimensions are pixels,
    we host the standalone map document in a sized iframe instead.

    Inline width stretching is handled generically by ``host_html_document``
    (pane width wins over declared pixels).
    """

    name = "folium"

    def setup(self) -> None:
        import folium  # noqa: F401

    def transform(self, obj: Any) -> Any:
        module = type(obj).__module__ or ""
        if not module.startswith("folium"):
            return obj
        if not hasattr(obj, "get_root") or not hasattr(obj, "width"):
            return obj

        width = _size_pair(getattr(obj, "width", None))
        height = _size_pair(getattr(obj, "height", None))
        if width is None or height is None:
            return obj
        if width[1] != "px" or height[1] != "px":
            # Percentage / responsive maps keep Folium's notebook HTML.
            return obj

        import ipywidgets as widgets

        from ..html_host import host_html_document

        w_px = max(int(width[0]), 1)
        h_px = max(int(height[0]), 1)
        document = obj.get_root().render()
        return widgets.HTML(
            value=host_html_document(
                document,
                width=f"{w_px}px",
                height=f"{h_px}px",
                title="Folium map",
            )
        )


def enable_folium() -> None:
    """Enable Folium map display with pixel-size preference."""
    from ..jupyter import register_extension

    register_extension(FoliumExtension())
