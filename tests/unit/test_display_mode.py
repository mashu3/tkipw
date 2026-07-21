"""Per-App ``inline`` / ``window`` display mode (no WebView required)."""

from __future__ import annotations

from unittest.mock import patch

import ipywidgets as widgets
import pytest
from support import FakeApp

from tkipw.comm_backend import set_bridge
from tkipw.display_mode import get_display_mode, set_display_mode
from tkipw.output import Output, display


@pytest.fixture(autouse=True)
def _reset_mode():
    set_bridge(None)
    yield
    set_bridge(None)


def test_set_display_mode_rejects_invalid():
    with pytest.raises(ValueError, match="inline"):
        set_display_mode("popup")  # type: ignore[arg-type]


def test_inline_display_appends_to_app_output():
    app = FakeApp(display_mode="inline")
    set_bridge(app)

    display(widgets.HTML(value="<b>hi</b>"))
    assert len(app._cell_output.children) == 1
    assert "hi" in app._cell_output.children[0].value


def test_window_mode_routes_through_open_display_window():
    app = FakeApp(display_mode="window")
    set_bridge(app)

    with patch("tkipw.display_mode.open_display_window") as open_window:
        display(widgets.Label("popup"))

    open_window.assert_called_once()
    assert app._cell_output.children == ()


def test_output_context_still_captures_in_window_mode():
    """``with Output():`` always captures, even for a window-mode App."""
    app = FakeApp(display_mode="window")
    set_bridge(app)
    out = Output()

    with patch("tkipw.display_mode.open_display_window") as open_window:
        with out:
            display(widgets.Label("captured"))

    open_window.assert_not_called()
    assert len(out.children) == 1


def test_runtime_setter_changes_active_app_and_matplotlib_backend():
    pytest.importorskip("matplotlib")
    import matplotlib

    from tkipw.jupyter import install_jupyter_support

    app = FakeApp(display_mode="inline")
    set_bridge(app)
    install_jupyter_support()
    set_display_mode("window")
    assert app.display_mode == "window"
    assert get_display_mode() == "window"
    if "tkagg" not in matplotlib.get_backend().lower():
        pytest.skip("TkAgg backend unavailable in this environment")

    set_display_mode("inline")
    assert app.display_mode == "inline"
    assert get_display_mode() == "inline"
    assert "agg" in matplotlib.get_backend().lower()


def test_active_app_determines_mode():
    inline = FakeApp(display_mode="inline")
    window = FakeApp(display_mode="window")

    set_bridge(inline)
    assert get_display_mode() == "inline"

    set_bridge(window)
    assert get_display_mode() == "window"


def test_small_html_table_gets_compact_window():
    from tkipw.display_mode import infer_window_size

    table = widgets.HTML(
        value=(
            "<table><thead><tr><th>city</th><th>sales</th></tr></thead>"
            "<tbody><tr><td>Tokyo</td><td>120</td></tr>"
            "<tr><td>Osaka</td><td>88</td></tr></tbody></table>"
        )
    )
    width, height = infer_window_size(table)
    assert 180 <= width < 500
    assert 100 <= height < 250


def test_pillow_image_keeps_raster_pixel_size():
    pytest.importorskip("PIL")
    from PIL import Image

    from tkipw.display_mode import _has_raster_pixel_size, infer_window_size

    im = Image.new("RGB", (640, 320), "white")
    assert infer_window_size(im) == (640, 320)
    assert _has_raster_pixel_size(im) is True
    assert _has_raster_pixel_size(widgets.HTML(value="<p>x</p>")) is False


def test_large_html_table_is_capped_and_scrollable_sized():
    from tkipw.display_mode import infer_window_size

    cells = "".join(
        "<tr>" + "".join(f"<td>{'x' * 100}</td>" for _ in range(12)) + "</tr>"
        for _ in range(100)
    )
    table = widgets.HTML(value=f"<table>{cells}</table>")
    assert infer_window_size(table) == (1100, 720)


def test_pandas_window_tracks_rendered_table_size():
    pd = pytest.importorskip("pandas")
    from tkipw.display_mode import infer_window_size
    from tkipw.output import to_widget

    small = pd.DataFrame({"city": ["Tokyo", "Osaka"], "sales": [120, 88]})
    large = pd.DataFrame(
        {f"column_{i}": [f"value-{row}-{i}" for row in range(40)] for i in range(8)}
    )

    small_size = infer_window_size(to_widget(small))
    large_size = infer_window_size(to_widget(large))
    assert large_size[0] > small_size[0]
    assert large_size[1] > small_size[1]
    assert large_size[0] <= 1100
    assert large_size[1] <= 720


def test_markdown_window_uses_document_default_not_table():
    from IPython.display import Markdown

    from tkipw.display_mode import _MARKDOWN_WINDOW_SIZE, infer_window_size
    from tkipw.output import to_widget

    source = Markdown(
        "# Title\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\nMore text below."
    )
    widget = to_widget(source)
    assert infer_window_size(source) == _MARKDOWN_WINDOW_SIZE
    assert infer_window_size(widget) == _MARKDOWN_WINDOW_SIZE
    # display() passes sources then converted widgets — sources must win.
    assert infer_window_size(source, widget) == _MARKDOWN_WINDOW_SIZE


def test_cloak_window_hides_via_alpha_when_supported():
    import tkinter as tk

    from tkipw.display_mode import _cloak_window, _reveal_window

    root = tk.Tk()
    root.withdraw()
    top = tk.Toplevel(root)
    try:
        if not _cloak_window(top):
            pytest.skip("window alpha not supported on this Tk build")
        assert float(top.attributes("-alpha")) == 0.0
        _reveal_window(top)
        assert float(top.attributes("-alpha")) == 1.0
    finally:
        top.destroy()
        root.destroy()


def test_ipyleaflet_window_uses_map_layout_or_readable_default():
    ipyleaflet = pytest.importorskip("ipyleaflet")
    from ipywidgets import Layout

    from tkipw.display_mode import infer_window_size

    assert infer_window_size(ipyleaflet.Map()) == (720, 480)
    sized = ipyleaflet.Map(layout=Layout(width="800px", height="520px"))
    assert infer_window_size(sized) == (800, 520)
    responsive = ipyleaflet.Map(layout=Layout(width="100%", height="360px"))
    assert infer_window_size(responsive) == (720, 360)


def test_ipycanvas_window_uses_canvas_pixel_size():
    ipycanvas = pytest.importorskip("ipycanvas")

    from tkipw.display_mode import infer_window_size

    assert infer_window_size(ipycanvas.Canvas(width=640, height=360)) == (640, 360)
    assert infer_window_size(ipycanvas.Canvas()) == (700, 500)
