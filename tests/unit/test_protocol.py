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
