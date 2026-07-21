"""Built-in display adapters in ``tkipw.extensions`` (no WebView required).

One class per adapter, mirroring ``src/tkipw/extensions/*.py``. Each adapter is
skipped when its third-party library is not installed.
"""

from __future__ import annotations

from unittest.mock import patch

import ipywidgets as widgets
import pytest

from tkipw.jupyter import install_jupyter_support
from tkipw.output import Output, to_widget


class TestIpyleaflet:
    def test_map_uses_bundled_jupyter_leaflet_module(self):
        ipyleaflet = pytest.importorskip("ipyleaflet")

        widget_map = ipyleaflet.Map(center=(35.68, 139.76), zoom=10)
        assert to_widget(widget_map) is widget_map
        assert widget_map._model_module == "jupyter-leaflet"
        assert widget_map._view_module == "jupyter-leaflet"
        assert widget_map._model_module_version.startswith("^0.20")


class TestIpycanvas:
    def test_canvas_uses_bundled_ipycanvas_module(self):
        ipycanvas = pytest.importorskip("ipycanvas")

        canvas = ipycanvas.Canvas(width=120, height=80)
        assert to_widget(canvas) is canvas
        assert canvas._model_module == "ipycanvas"
        assert canvas._view_module == "ipycanvas"
        assert canvas._model_module_version.startswith("^0.13")
        assert canvas._canvas_manager._model_module == "ipycanvas"


class TestBqplot:
    def test_figure_uses_bundled_bqplot_and_bqscales_modules(self):
        pytest.importorskip("bqplot")
        from bqplot import Axis, Figure, LinearScale, Scatter

        x_sc = LinearScale()
        y_sc = LinearScale()
        scatter = Scatter(x=[1, 2], y=[3, 4], scales={"x": x_sc, "y": y_sc})
        ax_y = Axis(scale=y_sc)
        ax_y.orientation = "vertical"
        fig = Figure(
            marks=[scatter],
            axes=[Axis(scale=x_sc), ax_y],
        )
        assert to_widget(fig) is fig
        assert fig._model_module == "bqplot"
        assert fig._view_module == "bqplot"
        assert fig._model_module_version.startswith("^0.6")
        assert x_sc._model_module == "bqscales"
        assert x_sc._view_module == "bqscales"


class TestMatplotlib:
    def test_figure_is_transformed_to_png(self):
        pytest.importorskip("matplotlib")
        install_jupyter_support()
        from matplotlib.figure import Figure

        widget = to_widget(Figure())
        assert isinstance(widget, widgets.HTML)
        assert "data:image/png;base64," in widget.value

    def test_inline_mode_routes_show_to_display(self):
        pytest.importorskip("matplotlib")
        install_jupyter_support()
        from matplotlib import pyplot as plt

        from tkipw.extensions.matplotlib import enable_matplotlib

        enable_matplotlib(mode="inline")
        fig = plt.figure()
        with patch("tkipw.output.display") as display:
            plt.show()
        display.assert_called_once()
        assert fig.number not in plt.get_fignums()

    def test_window_mode_uses_tkagg_without_patching_show(self):
        pytest.importorskip("matplotlib")
        install_jupyter_support()
        import matplotlib
        from matplotlib import pyplot as plt

        from tkipw.extensions.matplotlib import enable_matplotlib

        # Start from a known patched inline state, then switch to window.
        enable_matplotlib(mode="inline")
        patched = plt.show
        enable_matplotlib(mode="window")

        if "tkagg" not in matplotlib.get_backend().lower():
            enable_matplotlib(mode="inline")
            pytest.skip("TkAgg backend unavailable in this environment")
        assert plt.show is not patched

        # Restore default for later tests.
        enable_matplotlib(mode="inline")

    def test_mode_can_switch_at_runtime(self):
        pytest.importorskip("matplotlib")
        install_jupyter_support()
        import matplotlib
        from matplotlib import pyplot as plt

        from tkipw.display_mode import set_display_mode
        from tkipw.jupyter import get_extension

        set_display_mode("inline")
        assert get_extension("matplotlib").mode == "inline"  # type: ignore[union-attr]

        set_display_mode("window")
        assert get_extension("matplotlib").mode == "window"  # type: ignore[union-attr]
        if "tkagg" not in matplotlib.get_backend().lower():
            set_display_mode("inline")
            pytest.skip("TkAgg backend unavailable in this environment")

        set_display_mode("inline")
        fig = plt.figure()
        with patch("tkipw.output.display") as display_mock:
            plt.show()
        display_mock.assert_called()
        assert fig.number not in plt.get_fignums()

    def test_invalid_mode_raises(self):
        pytest.importorskip("matplotlib")
        from tkipw.display_mode import set_display_mode

        with pytest.raises(ValueError, match="inline"):
            set_display_mode("popup")  # type: ignore[arg-type]


class TestPyVista:
    def test_enable_sets_notebook_theme(self):
        pytest.importorskip("pyvista")
        import pyvista as pv
        import scooby

        from tkipw.extensions.pyvista import enable_pyvista

        enable_pyvista()
        assert pv.global_theme.notebook is True
        assert scooby.in_ipykernel() is True
        # Plotter must take the Jupyter path (not a native VTK window).
        plotter = pv.Plotter()
        try:
            assert plotter.notebook is True
            assert plotter.off_screen is True
        finally:
            plotter.close()

    def test_remaps_unsafe_backends_to_client(self):
        pytest.importorskip("pyvista")
        from tkipw.extensions.pyvista import PyVistaExtension

        ext = PyVistaExtension()
        ext._trame_available = True
        with pytest.warns(RuntimeWarning, match="client"):
            assert ext._coerce_backend("trame") == "client"
        with pytest.warns(RuntimeWarning, match="client"):
            assert ext._coerce_backend("server") == "client"
        assert ext._coerce_backend("client") == "client"
        assert ext._coerce_backend("html") == "html"
        assert ext._coerce_backend(None) == "client"

    def test_falls_back_to_html_without_trame(self):
        pytest.importorskip("pyvista")
        from tkipw.extensions.pyvista import PyVistaExtension

        ext = PyVistaExtension()
        ext._trame_available = False
        with pytest.warns(RuntimeWarning, match="html"):
            assert ext._coerce_backend("client") == "html"

    def test_transform_uses_loopback_html_host(self):
        pytest.importorskip("pyvista")
        from tkipw.extensions.pyvista import PyVistaExtension

        srcdoc_iframe = (
            '<iframe srcdoc="&lt;!doctype html&gt;'
            "&lt;script type=&quot;module&quot;&gt;"
            'x=1&lt;/script&gt;" class="pyvista" '
            'style="width: 99%; height: 600px; '
            'border: 1px solid rgb(221,221,221);"></iframe>'
        )

        class FakePv(widgets.HTML):
            pass

        FakePv.__module__ = "pyvista.trame.jupyter"
        viewer = FakePv(value=srcdoc_iframe)

        out = PyVistaExtension().transform(viewer)
        assert "srcdoc" not in out.value
        assert "http://127.0.0.1:" in out.value
        assert 'src="' in out.value


class TestPillow:
    def test_image_transforms_to_png_widget(self):
        Image = pytest.importorskip("PIL.Image")
        from tkipw.extensions.pillow import PillowExtension

        image = Image.new("RGBA", (8, 6), (255, 0, 0, 128))
        widget = PillowExtension().transform(image)

        assert isinstance(widget, widgets.HTML)
        assert "data:image/png;base64," in widget.value
        assert "Pillow image" in widget.value
        assert 'class="tkipw-raster"' in widget.value

    def test_show_routes_to_output(self):
        Image = pytest.importorskip("PIL.Image")
        from tkipw.extensions.pillow import enable_pillow

        enable_pillow()
        output = Output()
        image = Image.new("RGB", (4, 4), "blue")
        with output:
            image.show()

        assert len(output.children) == 1
        assert "data:image/png;base64," in output.children[0].value


class TestAltair:
    def test_chart_transforms_to_hosted_iframe(self):
        alt = pytest.importorskip("altair")
        from support import FakeApp

        from tkipw.comm_backend import set_bridge
        from tkipw.display_mode import infer_window_size
        from tkipw.extensions.altair import AltairExtension, window_frame_size

        chart = (
            alt.Chart(alt.Data(values=[{"x": 1, "y": 2}, {"x": 2, "y": 4}]))
            .mark_point()
            .encode(x="x:Q", y="y:Q")
            .properties(title="demo", width=400, height=240)
        )

        set_bridge(FakeApp(display_mode="window"))
        widget = AltairExtension().transform(chart)
        win_w, win_h = window_frame_size(chart)
        assert isinstance(widget, widgets.HTML)
        assert f"width:{win_w}px" in widget.value
        assert f"height:{win_h}px" in widget.value
        assert infer_window_size(chart) == (win_w, win_h)
        # Data rectangle is smaller than the framed window (axes + title).
        assert win_w > 400
        assert win_h > 240

        set_bridge(FakeApp(display_mode="inline"))
        inline = AltairExtension().transform(chart)
        assert "width:100%" in inline.value
        set_bridge(None)


class TestBokeh:
    def test_figure_transforms_to_hosted_iframe(self):
        pytest.importorskip("bokeh")
        from bokeh.plotting import figure
        from support import FakeApp

        from tkipw.comm_backend import set_bridge
        from tkipw.display_mode import infer_window_size
        from tkipw.extensions.bokeh import BokehExtension, window_frame_size

        # Default toolbar is on the right → pad width, not height.
        plot = figure(width=300, height=200)
        plot.scatter([1, 2], [3, 4])
        assert plot.toolbar_location == "right"

        set_bridge(FakeApp(display_mode="window"))
        widget = BokehExtension().transform(plot)
        win_w, win_h = window_frame_size(plot)
        assert isinstance(widget, widgets.HTML)
        assert "tkipw-hosted-html" in widget.value
        assert f"width:{win_w}px" in widget.value
        assert f"height:{win_h}px" in widget.value
        assert infer_window_size(plot) == (win_w, win_h)
        assert win_w > 300  # right toolbar
        assert win_h == 202  # canvas height + tiny doc pad

        above = figure(width=300, height=200, toolbar_location="above")
        above.scatter([1, 2], [3, 4])
        aw, ah = window_frame_size(above)
        assert aw == 302
        assert ah > 200

        set_bridge(FakeApp(display_mode="inline"))
        inline = BokehExtension().transform(plot)
        assert "width:100%" in inline.value
        assert plot.sizing_mode != "stretch_width"  # restored after transform
        set_bridge(None)

    def test_preimported_show_routes_to_output(self):
        pytest.importorskip("bokeh")
        from bokeh.plotting import figure
        from bokeh.plotting import show as imported_show

        from tkipw.extensions.bokeh import BokehExtension

        extension = BokehExtension()
        extension.setup()
        plot = figure(width=200, height=120)
        try:
            with patch("tkipw.output.display") as display:
                imported_show(plot)
            display.assert_called_once_with(plot)
        finally:
            extension.teardown()


class TestFolium:
    def test_pixel_map_uses_fixed_hosted_iframe(self):
        pytest.importorskip("folium")
        import folium
        from support import FakeApp

        from tkipw.comm_backend import set_bridge
        from tkipw.display_mode import infer_window_size
        from tkipw.extensions.folium import FoliumExtension

        m = folium.Map(location=[35.68, 139.76], zoom_start=12, width=800, height=400)

        set_bridge(FakeApp(display_mode="window"))
        widget = FoliumExtension().transform(m)
        assert isinstance(widget, widgets.HTML)
        assert "tkipw-hosted-html" in widget.value
        assert "width:800px" in widget.value
        assert "height:400px" in widget.value
        assert infer_window_size(m) == (800, 400)

        set_bridge(FakeApp(display_mode="inline"))
        inline = FoliumExtension().transform(m)
        assert isinstance(inline, widgets.HTML)
        # Inline: pane width wins, height follows Map aspect (800×400 → 2/1).
        assert "width:100%" in inline.value
        assert "aspect-ratio:800 / 400" in inline.value
        assert "height:auto" in inline.value
        assert "width:800px" not in inline.value
        set_bridge(None)

    def test_responsive_map_keeps_notebook_html(self):
        pytest.importorskip("folium")
        import folium

        from tkipw.display_mode import infer_window_size
        from tkipw.extensions.folium import FoliumExtension

        m = folium.Map(location=[35.68, 139.76], zoom_start=12)
        out = FoliumExtension().transform(m)
        assert out is m
        assert infer_window_size(m) == (720, 432)
