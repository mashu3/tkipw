"""``tkipw.comm_backend`` protocol: comm message shapes, buffers, routing.

Covers the Python <-> JS wire format and the ``create_comm`` monkey-patch, all
without a WebView. Bridge-stack *lifecycle* (multi-App, teardown) lives in
``test_lifecycle.py``; this module is about the protocol a single bridge sees.
"""

from __future__ import annotations

import base64

import comm
import ipywidgets as widgets
import pytest
from support import RecordingBridge

from tkipw.comm_backend import (
    TkwryComm,
    _decode_buffers,
    _encode_buffers,
    ensure_widget_comm,
    install_comm_backend,
    reset_comms,
    set_bridge,
    walk_widgets,
)


@pytest.fixture(autouse=True)
def _backend():
    """Install the comm backend and isolate the global bridge / pending queue."""
    set_bridge(None)
    reset_comms()
    install_comm_backend()
    yield
    set_bridge(None)
    reset_comms()


def test_install_replaces_create_comm():
    c = comm.create_comm(target_name="jupyter.widget", data={"state": {}})
    assert isinstance(c, TkwryComm)


def test_comm_open_and_msg_shape():
    bridge = RecordingBridge()
    set_bridge(bridge)

    channel = TkwryComm(
        target_name="jupyter.widget",
        data={
            "state": {"_model_name": "IntSliderModel", "value": 3},
            "buffer_paths": [],
        },
        metadata={"version": "2.1.0"},
    )

    opens = bridge.messages_of_type("comm_open")
    assert len(opens) == 1
    assert opens[0]["channel"] == "comm"
    assert opens[0]["target_name"] == "jupyter.widget"
    assert opens[0]["metadata"]["version"] == "2.1.0"
    assert opens[0]["data"]["state"]["value"] == 3

    before = len(bridge.messages)
    channel.send(data={"method": "update", "state": {"value": 9}, "buffer_paths": []})
    assert bridge.messages[-1]["msg_type"] == "comm_msg"
    assert len(bridge.messages) == before + 1


def test_pending_messages_flush_when_bridge_arrives():
    # No bridge yet -> comm_open is queued until one is set.
    _ = widgets.IntSlider(value=1)
    bridge = RecordingBridge()
    set_bridge(bridge)
    assert bridge.messages_of_type("comm_open")


def test_buffers_roundtrip():
    raw = [b"hello", bytes([0, 1, 2, 255])]
    encoded = _encode_buffers(raw)
    assert all(isinstance(x, str) for x in encoded)
    assert _decode_buffers(encoded) == raw
    assert base64.b64decode(encoded[0]) == b"hello"


def test_deliver_from_js_updates_trait():
    bridge = RecordingBridge()
    set_bridge(bridge)

    slider = widgets.IntSlider(value=0)
    ensure_widget_comm(slider)
    assert isinstance(slider.comm, TkwryComm)

    slider.comm.deliver_from_js(
        {"method": "update", "state": {"value": 42}, "buffer_paths": []}
    )
    assert slider.value == 42


def test_existing_widget_state_is_replayed_to_another_app():
    """A widget created in the host must also open in a window-mode pop-up."""
    from tkipw.manager import prepare_widgets

    host = RecordingBridge("host")
    popup = RecordingBridge("popup")
    set_bridge(host)
    slider = widgets.IntSlider(value=37)
    assert slider.model_id in host._known_model_ids

    prepare_widgets([slider], bridge=popup)

    opens = popup.messages_of_type("comm_open")
    root_open = next(m for m in opens if m["comm_id"] == slider.model_id)
    assert root_open["data"]["state"]["value"] == 37


def test_walk_widgets_includes_children_and_layout():
    a = widgets.IntSlider()
    b = widgets.Button()
    box = widgets.VBox([a, b])

    found = walk_widgets(box)
    ids = {w.model_id for w in found}
    assert {box.model_id, a.model_id, b.model_id, box.layout.model_id} <= ids
    # Dependencies (children / layout) must precede the parent for replay.
    assert found.index(a) < found.index(box)
    assert found.index(b) < found.index(box)
    assert found.index(box.layout) < found.index(box)


def test_walk_widgets_orders_html_dependencies_first():
    html = widgets.HTML(value="<b>hi</b>")
    found = walk_widgets(html)
    assert found[-1] is html
    assert found.index(html.layout) < found.index(html)
    assert found.index(html.style) < found.index(html)


def test_walk_widgets_includes_ipyleaflet_layers_and_controls():
    pytest.importorskip("ipyleaflet")
    from ipyleaflet import Map, Marker

    widget_map = Map(center=(35.68, 139.76), zoom=10)
    marker = Marker(location=(35.68, 139.76))
    widget_map.add(marker)

    found = walk_widgets(widget_map)
    ids = {w.model_id for w in found}
    assert widget_map.model_id in ids
    assert marker.model_id in ids
    for layer in widget_map.layers:
        assert layer.model_id in ids
        assert found.index(layer) < found.index(widget_map)
    for control in widget_map.controls:
        assert control.model_id in ids
        assert found.index(control) < found.index(widget_map)
    for style_attr in ("style", "default_style", "dragging_style"):
        style = getattr(widget_map, style_attr)
        assert style.model_id in ids
        assert found.index(style) < found.index(widget_map)
    assert found[-1] is widget_map


def test_walk_widgets_includes_ipycanvas_manager():
    pytest.importorskip("ipycanvas")
    from ipycanvas import Canvas

    canvas = Canvas(width=100, height=80)
    found = walk_widgets(canvas)
    ids = {w.model_id for w in found}
    assert canvas.model_id in ids
    assert canvas._canvas_manager.model_id in ids
    assert found.index(canvas._canvas_manager) < found.index(canvas)
    assert found[-1] is canvas


def test_walk_widgets_includes_bqplot_marks_and_scales():
    pytest.importorskip("bqplot")
    from bqplot import Axis, Figure, LinearScale, Scatter

    x_sc = LinearScale()
    y_sc = LinearScale()
    scatter = Scatter(x=[1, 2], y=[3, 4], scales={"x": x_sc, "y": y_sc})
    ax_x = Axis(scale=x_sc)
    ax_y = Axis(scale=y_sc)
    ax_y.orientation = "vertical"
    fig = Figure(marks=[scatter], axes=[ax_x, ax_y])

    found = walk_widgets(fig)
    ids = {w.model_id for w in found}
    assert fig.model_id in ids
    assert scatter.model_id in ids
    assert x_sc.model_id in ids
    assert y_sc.model_id in ids
    assert ax_x.model_id in ids
    assert ax_y.model_id in ids
    assert found.index(x_sc) < found.index(scatter)
    assert found.index(scatter) < found.index(fig)
    assert found[-1] is fig


def test_frontend_comm_open_registers_bqplot_panzoom_for_ipy_model_refs():
    """Toolbar-created PanZoom must resolve as Figure.interaction, not a string."""
    pytest.importorskip("bqplot")
    from bqplot import Figure
    from ipywidgets import Widget
    from ipywidgets.widgets.widget import _instances

    from tkipw.comm_backend import accept_comm_open_from_js, get_comm

    bridge = RecordingBridge()
    set_bridge(bridge)
    fig = Figure()
    panzoom_id = "frontend-panzoom-test-id"

    accept_comm_open_from_js(
        {
            "msg_type": "comm_open",
            "comm_id": panzoom_id,
            "target_name": "jupyter.widget",
            "metadata": {"version": "2.1.0"},
            "data": {
                "state": {
                    "_model_module": "bqplot",
                    "_model_module_version": "^0.6.1",
                    "_model_name": "PanZoomModel",
                    "_view_module": "bqplot",
                    "_view_module_version": "^0.6.1",
                    "_view_name": "PanZoom",
                }
            },
        }
    )

    assert get_comm(panzoom_id) is not None
    assert panzoom_id in _instances
    panzoom = _instances[panzoom_id]
    assert isinstance(panzoom, Widget)
    assert panzoom._model_name == "PanZoomModel"
    # Registered so Widget.close → Comm.close → unregister_comm does not KeyError.
    import comm

    assert comm.get_comm_manager().get_comm(panzoom_id) is not None

    # Same path as a JS state update: serialized widget ref must deserialize.
    fig.set_state({"interaction": f"IPY_MODEL_{panzoom_id}"})
    assert fig.interaction is panzoom

    panzoom.close()
    assert comm.get_comm_manager().get_comm(panzoom_id) is None
