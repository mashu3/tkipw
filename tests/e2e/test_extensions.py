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
    style = eval_json(
        app,
        "(function(){var t=document.querySelector('table.dataframe');"
        "if(!t)return null;var cs=getComputedStyle(t);"
        "var td=t.querySelector('td');"
        "return {collapse:cs.borderCollapse, border:cs.borderTopWidth,"
        "pad:td&&getComputedStyle(td).padding};})()",
        steps=8,
    )
    assert isinstance(style, dict)
    assert style.get("collapse") == "collapse"
    assert style.get("border") in ("0px", "0")


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


def test_ipympl_canvas_renders(app):
    pytest.importorskip("ipympl")
    import ipympl  # noqa: F401
    from matplotlib import pyplot as plt

    from tkipw.extensions.matplotlib import enable_matplotlib
    from tkipw.output import display

    try:
        fig, ax = plt.subplots(figsize=(4.0, 3.0), dpi=80)
        ax.plot([1, 2, 3], [1, 4, 9], color="#2563eb")
        fig.tight_layout()
        display(fig.canvas)
        assert wait_for_selector(
            app, "#tkipw-widgets .jupyter-matplotlib", steps=200
        ), "ipympl canvas DOM missing"
        assert wait_for_selector(
            app, "#tkipw-widgets .jupyter-matplotlib-canvas-div canvas", steps=200
        ), "ipympl drawing canvas missing"
        layout = eval_json(
            app,
            "(function(){"
            "var div=document.querySelector("
            "'.jupyter-matplotlib-canvas-div');"
            "var cvs=div&&div.querySelector('canvas');"
            "if(!div||!cvs)return null;"
            "var dr=div.getBoundingClientRect();"
            "var cr=cvs.getBoundingClientRect();"
            "return {dw:dr.width,dh:dr.height,cw:cr.width,ch:cr.height};})()",
            steps=8,
        )
        assert isinstance(layout, dict)
        assert float(layout.get("dw") or 0) >= float(layout.get("cw") or 0) - 4, (
            f"ipympl canvas clipped by parent: {layout!r}"
        )
        assert float(layout.get("cw") or 0) >= 200, f"ipympl canvas too narrow: {layout!r}"
        # Figure shell must track the canvas width (not shrink via max-width:100%
        # or stretch-and-clip inside an overflow:hidden Output VBox).
        shell = eval_json(
            app,
            "(function(){"
            "var fig=document.querySelector('.jupyter-matplotlib-figure');"
            "var mpl=document.querySelector('.jupyter-matplotlib');"
            "var div=document.querySelector('.jupyter-matplotlib-canvas-div');"
            "if(!fig||!mpl||!div)return null;"
            "var fr=fig.getBoundingClientRect();"
            "var mr=mpl.getBoundingClientRect();"
            "var dr=div.getBoundingClientRect();"
            "return {fw:fr.width,mw:mr.width,dw:dr.width};})()",
            steps=8,
        )
        assert isinstance(shell, dict)
        assert float(shell.get("fw") or 0) >= float(shell.get("dw") or 0) - 4, (
            f"ipympl figure narrower than canvas: {shell!r}"
        )
        assert float(shell.get("mw") or 0) >= float(shell.get("dw") or 0) - 4, (
            f"ipympl widget narrower than canvas: {shell!r}"
        )
    finally:
        plt.close("all")
        enable_matplotlib(mode="inline")


def test_ipympl_clear_output_removes_dom(app):
    """ipympl must not leave orphaned figure nodes after clear_output."""
    pytest.importorskip("ipympl")
    import ipympl  # noqa: F401
    from matplotlib import pyplot as plt

    from tkipw.extensions.matplotlib import enable_matplotlib
    from tkipw.output import Output, clear_output, display

    results = Output()
    app.display(results)
    try:
        with results:
            fig, ax = plt.subplots(figsize=(3.0, 2.0), dpi=80)
            ax.plot([1, 2, 3], [1, 4, 9])
            display(fig.canvas)
        assert wait_for_selector(
            app, "#tkipw-widgets .jupyter-matplotlib", steps=200
        ), "ipympl canvas DOM missing"
        with results:
            clear_output(wait=False)
        assert wait_until(
            app.root,
            lambda: query_count(app, ".jupyter-matplotlib") == 0,
            steps=200,
        ), "clear_output left orphaned ipympl DOM"
    finally:
        plt.close("all")
        enable_matplotlib(mode="inline")


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
        pad = eval_json(
            popup,
            "(function(){var m=document.querySelector('#tkipw-widgets');"
            "return m&&getComputedStyle(m).padding;})()",
            steps=8,
        )
        assert pad in ("0px", "0"), (
            f"window-mode canvas should be edge-to-edge, got {pad!r}"
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


def test_bqplot_renders_and_updates(app, tmp_path, monkeypatch):
    pytest.importorskip("bqplot")
    from bqplot import Axis, Figure, LinearScale, Scatter
    from ipywidgets import Layout

    from tkipw.output import display

    x_sc = LinearScale()
    y_sc = LinearScale()
    scatter = Scatter(
        x=[1, 2, 3],
        y=[1, 4, 9],
        scales={"x": x_sc, "y": y_sc},
        colors=["#2563eb"],
    )
    ax_y = Axis(scale=y_sc)
    ax_y.orientation = "vertical"
    fig = Figure(
        marks=[scatter],
        axes=[Axis(scale=x_sc), ax_y],
        title="e2e-bqplot",
        layout=Layout(width="480px", height="320px"),
    )
    display(fig)
    assert wait_for_selector(app, "#tkipw-widgets .bqplot .svg-figure"), (
        "bqplot DOM missing"
    )

    def marks_drawn() -> bool:
        sample = eval_json(
            app,
            "(function(){"
            "var dots=document.querySelectorAll('#tkipw-widgets .bqplot .dot.element');"
            "var svg=document.querySelector('#tkipw-widgets .bqplot svg');"
            "if(!svg)return null;"
            "var r=svg.getBoundingClientRect();"
            "return {n:dots.length,w:r.width,h:r.height};})()",
            steps=8,
        )
        return (
            isinstance(sample, dict)
            and int(sample.get("n") or 0) >= 3
            and float(sample.get("w") or 0) > 0
            and float(sample.get("h") or 0) > 0
        )

    assert wait_until(app.root, marks_drawn, steps=200), "bqplot marks not drawn"

    before = eval_json(
        app,
        "(function(){return [].map.call("
        "document.querySelectorAll('#tkipw-widgets .bqplot .dot.element'),"
        "function(d){var r=d.getBoundingClientRect();return [r.x,r.y];});})()",
        steps=8,
    )
    scatter.y = [2, 3, 5]

    def mark_moved() -> bool:
        after = eval_json(
            app,
            "(function(){return [].map.call("
            "document.querySelectorAll('#tkipw-widgets .bqplot .dot.element'),"
            "function(d){var r=d.getBoundingClientRect();return [r.x,r.y];});})()",
            steps=8,
        )
        return isinstance(after, list) and after != before

    assert wait_until(app.root, mark_moved, steps=200), (
        "bqplot mark update did not reach the frontend"
    )

    # Toolbar PanZoom: interaction layer must mount (regression for early iopub idle).
    eval_json(
        app,
        "(function(){"
        "var tb=document.querySelector('.toolbar_div');"
        "if(!tb)return false;"
        "tb.style.display='unset';tb.style.visibility='visible';tb.style.opacity='1';"
        "var btn=document.querySelector('button[title=PanZoom]');"
        "if(!btn)return false;"
        "btn.click();"
        "return true;})()",
        steps=8,
    )

    def panzoom_layer() -> bool:
        sample = eval_json(
            app,
            "(function(){"
            "var r=document.querySelector("
            "'#tkipw-widgets .bqplot svg.svg-figure rect[style*=\"cursor: move\"]');"
            "return !!(r && r.getAttribute('pointer-events')==='all');})()",
            steps=8,
        )
        return sample is True

    assert wait_until(app.root, panzoom_layer, steps=200), (
        "bqplot PanZoom interaction layer did not mount"
    )
    from bqplot.interacts import PanZoom

    assert isinstance(fig.interaction, PanZoom)

    # Save uses ``<a download>``; desktop WebViews ignore that — bridge to Tk.
    out = tmp_path / "bqplot-save.png"
    monkeypatch.setattr(
        "tkipw.app.filedialog.asksaveasfilename",
        lambda **_kwargs: str(out),
    )
    eval_json(
        app,
        "(function(){"
        "var tb=document.querySelector('.toolbar_div');"
        "if(!tb)return false;"
        "tb.style.display='unset';tb.style.visibility='visible';tb.style.opacity='1';"
        "var btn=document.querySelector('button[title=Save]');"
        "if(!btn)return false;"
        "btn.click();"
        "return true;})()",
        steps=8,
    )
    assert wait_until(
        app.root,
        lambda: out.is_file() and out.stat().st_size > 32,
        steps=200,
    ), "bqplot Save did not write a PNG via the download bridge"


@pytest.mark.skipif(
    sys.platform.startswith("linux"),
    reason=("WebKitGTK stalls creating a WebView under a withdrawn window-mode host"),
)
def test_bqplot_renders_in_window_mode():
    pytest.importorskip("bqplot")
    from bqplot import Axis, Figure, LinearScale, Scatter
    from ipywidgets import Layout

    from tkipw import App
    from tkipw.output import display

    host = App(title="tkipw-e2e-bqplot-window", display_mode="window")
    try:
        x_sc = LinearScale()
        y_sc = LinearScale()
        scatter = Scatter(
            x=[1, 2, 3],
            y=[1, 4, 9],
            scales={"x": x_sc, "y": y_sc},
            colors=["#f59e0b"],
        )
        ax_y = Axis(scale=y_sc)
        ax_y.orientation = "vertical"
        fig = Figure(
            marks=[scatter],
            axes=[Axis(scale=x_sc), ax_y],
            layout=Layout(width="480px", height="320px"),
        )
        display(fig)
        assert host._display_windows, "window-mode pop-up was not created"
        popup = host._display_windows[-1]
        assert wait_until(popup.root, lambda: popup._ready, steps=200), (
            "popup runtime never became ready"
        )
        assert wait_for_selector(
            popup,
            "#tkipw-widgets .bqplot .svg-figure",
            steps=200,
        ), "bqplot DOM missing in window mode"
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
