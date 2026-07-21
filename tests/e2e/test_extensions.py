"""Real-WebView regression for display extensions and notebook-style output.

These complement ``test_webview.py`` (runtime/comm) by mounting the objects
that go through ``to_widget`` / Jupyter adapters and asserting the DOM that
users actually see.
"""

from __future__ import annotations

import json
import os
import sys

import ipywidgets as widgets
import pytest
from IPython.display import Markdown

from e2e.helpers import (
    dom_text,
    eval_json,
    pump,
    query_count,
    wait_for_html,
    wait_for_selector,
    wait_until,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("TKIPW_E2E") != "1",
        reason="set TKIPW_E2E=1 to run the real-WebView end-to-end tests",
    ),
]


def test_markdown_renders_in_output_pane(app):
    from tkipw.output import display

    display(Markdown("# E2E Markdown\n\nHello **tkipw**."))
    assert wait_for_selector(app, ".tkipw-markdown h1"), "markdown heading missing"
    assert wait_for_html(app, "tkipw"), "markdown body missing"


def test_display_error_and_clear_output(app):
    from tkipw.output import clear_output, display_error

    display_error("boom-from-e2e")
    assert wait_for_selector(app, ".tkipw-error"), "error block missing"
    assert wait_for_html(app, "boom-from-e2e")

    clear_output()
    assert wait_until(
        app.root,
        lambda: query_count(app, ".tkipw-error") == 0,
        steps=200,
    ), "clear_output did not remove the error block"


def test_theme_switch_updates_document_attribute(app):
    app.set_theme("dark")
    assert wait_until(
        app.root,
        lambda: (
            eval_json(app, "document.documentElement.getAttribute('data-theme')")
            == "dark"
        ),
    )
    app.set_theme("light")
    assert wait_until(
        app.root,
        lambda: (
            eval_json(app, "document.documentElement.getAttribute('data-theme')")
            == "light"
        ),
    )


def test_matplotlib_figure_renders_png(app):
    pytest.importorskip("matplotlib")
    from matplotlib.figure import Figure

    from tkipw.output import display

    fig = Figure(figsize=(3, 2), dpi=80)
    ax = fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 0])
    display(fig)

    assert wait_for_selector(app, '#tkipw-widgets img[src*="data:image/png"]'), (
        "matplotlib PNG was not rendered"
    )


def test_pillow_image_show_renders_png(app):
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    from tkipw.output import display

    image = Image.new("RGB", (120, 80), "#eff6ff")
    ImageDraw.Draw(image).rectangle((10, 10, 110, 70), outline="#2563eb", width=3)
    display(image)

    assert wait_for_selector(app, '#tkipw-widgets img[src*="data:image/png"]'), (
        "Pillow PNG was not rendered"
    )


def test_pandas_dataframe_renders_table(app):
    pd = pytest.importorskip("pandas")
    from tkipw.output import display

    display(pd.DataFrame({"city": ["Tokyo", "Osaka"], "sales": [120, 88]}))
    assert wait_for_selector(app, "#tkipw-widgets table"), "pandas table missing"
    assert wait_for_html(app, "Tokyo")


def test_altair_chart_hosts_iframe(app):
    pytest.importorskip("altair")
    import altair as alt

    from tkipw.output import display

    chart = (
        alt.Chart(alt.Data(values=[{"x": 1, "y": 2}, {"x": 2, "y": 3}]))
        .mark_point()
        .encode(x="x:Q", y="y:Q")
        .properties(width=240, height=160)
    )
    display(chart)
    assert wait_for_selector(app, "#tkipw-widgets iframe.tkipw-hosted-html"), (
        "Altair hosted iframe missing"
    )


def test_bokeh_figure_hosts_iframe(app):
    pytest.importorskip("bokeh")
    from bokeh.plotting import figure

    from tkipw.output import display

    plot = figure(width=320, height=200, title="e2e-bokeh")
    plot.line([1, 2, 3], [1, 4, 9])
    display(plot)
    assert wait_for_selector(app, "#tkipw-widgets iframe.tkipw-hosted-html"), (
        "Bokeh hosted iframe missing"
    )


def test_folium_map_hosts_iframe(app):
    pytest.importorskip("folium")
    import folium

    from tkipw.output import display

    m = folium.Map(location=[35.68, 139.76], zoom_start=11, width=480, height=320)
    display(m)
    assert wait_for_selector(app, "#tkipw-widgets iframe.tkipw-hosted-html"), (
        "Folium hosted iframe missing"
    )


def test_ipyleaflet_map_renders_live_widget_and_updates(app):
    pytest.importorskip("ipyleaflet")
    from ipyleaflet import Map, Marker
    from ipywidgets import Layout

    from tkipw.output import display

    center = (35.6812, 139.7671)
    widget_map = Map(
        center=center,
        zoom=10,
        layout=Layout(width="100%", height="320px"),
    )
    widget_map.add(Marker(location=center, title="Tokyo Station"))
    display(widget_map)

    assert wait_for_selector(app, "#tkipw-widgets .leaflet-container"), (
        "ipyleaflet map DOM missing"
    )
    assert wait_for_selector(app, "#tkipw-widgets .leaflet-marker-icon"), (
        "ipyleaflet marker DOM missing"
    )

    model_id = widget_map.model_id
    widget_map.zoom = 13

    def frontend_zoom_is_updated() -> bool:
        # Read repeatedly: the first get_model() can resolve before the
        # comm_msg carrying the Python trait update reaches the frontend.
        app.webview.eval_js(
            f"window.__tkipwManager.get_model({json.dumps(model_id)}).then(function(m){{"
            "window.__tkipwLeafletZoom = m.get('zoom');"
            "});"
        )
        pump(app.root, steps=1)
        return eval_json(app, "window.__tkipwLeafletZoom", steps=8) == 13

    assert wait_until(
        app.root,
        frontend_zoom_is_updated,
    ), "ipyleaflet zoom update did not reach the frontend"


@pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason=(
        "WebKitGTK stalls creating a WebView under a withdrawn window-mode "
        "host and/or polling Leaflet tiles via eval_js_with_callback"
    ),
)
def test_ipyleaflet_map_renders_in_window_mode():
    """Window pop-ups must replay nested leaflet layers/controls to the new manager."""
    pytest.importorskip("ipyleaflet")
    from ipyleaflet import Map, Marker
    from ipywidgets import Layout

    from tkipw import App
    from tkipw.output import display

    # Window-mode host root is withdrawn; its WebView may never become ready.
    # Content lives in the pop-up App created by display().
    host = App(
        title="tkipw-e2e-leaflet-window",
        display_mode="window",
        width=200,
        height=120,
    )
    try:
        pump(host.root, steps=5)
        center = (35.6812, 139.7671)
        widget_map = Map(
            center=center,
            zoom=11,
            layout=Layout(width="640px", height="360px"),
        )
        widget_map.add(Marker(location=center, title="Tokyo Station"))
        display(widget_map)

        windows = getattr(host, "_display_windows", []) or []
        assert windows, "window-mode display did not open a pop-up"
        popup = windows[-1]
        assert wait_until(popup.root, lambda: popup._ready, steps=200), (
            "popup runtime never became ready"
        )
        assert wait_for_selector(
            popup, "#tkipw-widgets .leaflet-container", steps=200
        ), "ipyleaflet map DOM missing in window mode"
        assert wait_for_selector(
            popup, "#tkipw-widgets .leaflet-marker-icon", steps=200
        ), "ipyleaflet marker DOM missing in window mode"
        assert "javascript error" not in dom_text(popup).lower()

        # Compact-shell CSS must not force ``img { width/height: 100% }`` onto
        # Leaflet tiles — that collapses them to 0×0 (grey map chrome only).
        def tiles_have_size() -> bool:
            size = eval_json(
                popup,
                "(function(){var t=document.querySelector('.leaflet-tile');"
                "if(!t)return null;var r=t.getBoundingClientRect();"
                "return {w:r.width,h:r.height,"
                "loaded:t.complete&&t.naturalWidth>0};})()",
                steps=8,
            )
            return (
                isinstance(size, dict)
                and size.get("loaded")
                and float(size.get("w") or 0) > 0
                and float(size.get("h") or 0) > 0
            )

        assert wait_until(popup.root, tiles_have_size, steps=200), (
            "ipyleaflet tiles are present but have zero layout size"
        )
    finally:
        for popup in list(getattr(host, "_display_windows", []) or []):
            try:
                popup.destroy()
            except Exception:
                pass
        host.destroy()


def test_ipycanvas_renders_and_draws(app):
    pytest.importorskip("ipycanvas")
    from ipycanvas import Canvas, hold_canvas

    from tkipw.output import display

    canvas = Canvas(width=240, height=160)
    display(canvas)
    assert wait_for_selector(app, "#tkipw-widgets canvas"), "ipycanvas DOM missing"

    with hold_canvas():
        canvas.fill_style = "#2563eb"
        canvas.fill_rect(0, 0, canvas.width, canvas.height)

    def canvas_is_filled() -> bool:
        sample = eval_json(
            app,
            "(function(){var c=document.querySelector('#tkipw-widgets canvas');"
            "if(!c)return null;var ctx=c.getContext('2d');"
            "var p=ctx.getImageData(10,10,1,1).data;"
            "return {w:c.width,h:c.height,r:p[0],g:p[1],b:p[2],a:p[3]};})()",
            steps=8,
        )
        return (
            isinstance(sample, dict)
            and sample.get("w") == 240
            and sample.get("h") == 160
            and sample.get("r") == 37
            and sample.get("g") == 99
            and sample.get("b") == 235
            and sample.get("a") == 255
        )

    assert wait_until(app.root, canvas_is_filled, steps=200), (
        "ipycanvas fill_rect did not reach the frontend"
    )


@pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason=(
        "WebKitGTK stalls creating a WebView under a withdrawn window-mode "
        "host and/or polling canvas pixels via eval_js_with_callback"
    ),
)
def test_ipycanvas_renders_in_window_mode():
    """Window pop-ups must replay Canvas + CanvasManager to the new manager."""
    pytest.importorskip("ipycanvas")
    from ipycanvas import Canvas, hold_canvas

    from tkipw import App
    from tkipw.output import display

    host = App(
        title="tkipw-e2e-ipycanvas-window",
        display_mode="window",
        width=200,
        height=120,
    )
    try:
        pump(host.root, steps=5)
        canvas = Canvas(width=320, height=200)
        display(canvas)

        windows = getattr(host, "_display_windows", []) or []
        assert windows, "window-mode display did not open a pop-up"
        popup = windows[-1]
        assert wait_until(popup.root, lambda: popup._ready, steps=200), (
            "popup runtime never became ready"
        )
        assert wait_for_selector(popup, "#tkipw-widgets canvas", steps=200), (
            "ipycanvas DOM missing in window mode"
        )

        with hold_canvas():
            canvas.fill_style = "#f59e0b"
            canvas.fill_rect(0, 0, canvas.width, canvas.height)

        assert "javascript error" not in dom_text(popup).lower()

        def canvas_is_filled() -> bool:
            sample = eval_json(
                popup,
                "(function(){var c=document.querySelector('#tkipw-widgets canvas');"
                "if(!c)return null;var ctx=c.getContext('2d');"
                "var p=ctx.getImageData(5,5,1,1).data;"
                "return {w:c.width,h:c.height,r:p[0],g:p[1],b:p[2],a:p[3]};})()",
                steps=8,
            )
            return (
                isinstance(sample, dict)
                and sample.get("w") == 320
                and sample.get("h") == 200
                and sample.get("r") == 245
                and sample.get("g") == 158
                and sample.get("b") == 11
                and sample.get("a") == 255
            )

        assert wait_until(popup.root, canvas_is_filled, steps=200), (
            "ipycanvas drawing missing in window-mode pop-up"
        )
    finally:
        for popup in list(getattr(host, "_display_windows", []) or []):
            try:
                popup.destroy()
            except Exception:
                pass
        host.destroy()


def test_html_widget_and_label_stack(app):
    from tkipw.output import display

    display(widgets.HTML(value="<strong id='e2e-html'>stacked</strong>"))
    display(widgets.Label(value="label-e2e"))
    assert wait_for_selector(app, "#e2e-html"), "HTML widget missing"
    assert wait_until(app.root, lambda: "label-e2e" in dom_text(app))


def test_output_context_captures_display(app):
    from tkipw.output import Output, display

    target = Output()
    app.display(target)
    pump(app.root, steps=6)
    with target:
        display(Markdown("## inside-output"))
    assert wait_for_selector(app, ".tkipw-markdown h2")
    assert wait_for_html(app, "inside-output")
