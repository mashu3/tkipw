"""End-to-end tests against a real tkwry WebView + bundled widget runtime.

These exercise the boundary the pure-Python tests cannot: the JavaScript
runtime booting, the Python -> JS comm/display path rendering real DOM, and the
JS -> Python comm path updating a Python trait.

They need a display and a native WebView, so they are opt-in:

    TKIPW_E2E=1 pytest tests/e2e

On CI this runs under Xvfb (Linux) / the system WebView (macOS). No network is
required for the core runtime — ``runtime.js`` is bundled and inlined into the
shell HTML. Extension suites may still pull CDN assets inside hosted iframes.
"""

from __future__ import annotations

import json
import os

import ipywidgets as widgets
import pytest

from e2e.helpers import (
    dom_text,
    pump,
    query_count,
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


def test_runtime_boots_and_reports_ready(app):
    """JS -> Python IPC: the bundled runtime posts ``ready`` back to Python."""
    assert app._ready


def test_display_renders_widget_dom(app):
    """Python -> JS: displaying a widget mounts real ipywidgets DOM."""
    slider = widgets.IntSlider(value=0, min=0, max=100, description="n")
    app.display(slider)
    assert wait_for_selector(app, "#tkipw-widgets .jupyter-widgets"), (
        "no widget DOM was rendered"
    )


def test_python_to_js_state_update_reflects_in_dom(app):
    """Python -> JS comm_msg: changing a trait updates the rendered widget."""
    slider = widgets.IntSlider(value=0, min=0, max=100)
    app.display(slider)
    assert wait_for_selector(app, "#tkipw-widgets .jupyter-widgets")

    slider.value = 77
    assert wait_until(app.root, lambda: "77" in dom_text(app)), (
        "value update did not reach the DOM"
    )


def test_js_to_python_comm_updates_trait(app):
    """JS -> Python comm_msg: model.save_changes() propagates to the Python trait."""
    slider = widgets.IntSlider(value=0, min=0, max=100)
    app.display(slider)
    assert wait_for_selector(app, "#tkipw-widgets .jupyter-widgets")

    model_id = json.dumps(slider.model_id)
    pump(app.root, steps=4)
    app.webview.eval_js(
        f"window.__tkipwManager.get_model({model_id}).then(function(m){{"
        "m.set('value', 13); m.save_changes();"
        "});"
    )

    assert wait_until(app.root, lambda: slider.value == 13), (
        f"trait not updated from JS; value={slider.value}"
    )


def test_multiple_widgets_remain_mounted(app):
    """Sequential display keeps earlier widgets alive in the shell."""
    app.display(widgets.Label(value="first-e2e"))
    app.display(widgets.Label(value="second-e2e"))
    assert wait_until(app.root, lambda: "first-e2e" in dom_text(app))
    assert wait_until(app.root, lambda: "second-e2e" in dom_text(app))
    assert query_count(app, "#tkipw-widgets .jupyter-widgets") >= 2
