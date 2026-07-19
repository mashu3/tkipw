"""Bridge-stack lifecycle: multiple Apps, routing, and patch teardown.

Pure-Python (no WebView). Covers the "multiple App / global monkey-patch /
teardown" behaviour: which bridge a new widget's comm routes to, and that the
comm backend can be cleanly uninstalled.
"""

from __future__ import annotations

import comm
import ipywidgets as widgets
import pytest
from support import RecordingBridge

from tkipw.comm_backend import (
    TkwryComm,
    get_bridge,
    install_comm_backend,
    pop_bridge,
    push_bridge,
    reset_comms,
    set_bridge,
    uninstall_comm_backend,
)


@pytest.fixture(autouse=True)
def _clean_bridge_state():
    """Isolate the global bridge stack / comm backend across tests."""
    set_bridge(None)
    install_comm_backend()
    yield
    set_bridge(None)
    reset_comms()
    install_comm_backend()


class TestBridgeStack:
    def test_push_pop_activates_top(self):
        a = RecordingBridge("a")
        b = RecordingBridge("b")

        push_bridge(a)
        assert get_bridge() is a

        push_bridge(b)
        assert get_bridge() is b

        pop_bridge(b)  # destroying the top restores the previous App
        assert get_bridge() is a

        pop_bridge(a)
        assert get_bridge() is None

    def test_push_existing_moves_it_to_top(self):
        a = RecordingBridge("a")
        b = RecordingBridge("b")
        push_bridge(a)
        push_bridge(b)

        push_bridge(a)  # re-activate a
        assert get_bridge() is a

        pop_bridge(a)
        assert get_bridge() is b


class TestRouting:
    def test_new_widget_comm_routes_to_active_bridge(self):
        a = RecordingBridge("a")
        b = RecordingBridge("b")
        push_bridge(a)
        push_bridge(b)

        # Widget created while B is active -> comm_open goes to B, not A.
        _ = widgets.IntSlider(value=5)
        assert b.messages_of_type("comm_open")
        assert not a.messages_of_type("comm_open")

        pop_bridge(b)
        pop_bridge(a)

    def test_pending_messages_flush_to_first_pushed_bridge(self):
        set_bridge(None)
        # No bridge yet -> comm_open is queued.
        _ = widgets.IntSlider(value=1)
        bridge = RecordingBridge()
        push_bridge(bridge)
        assert bridge.messages_of_type("comm_open")


class TestCommBackendTeardown:
    def test_uninstall_restores_create_comm(self):
        install_comm_backend()
        assert isinstance(
            comm.create_comm(target_name="jupyter.widget", data={}), TkwryComm
        )

        uninstall_comm_backend()
        restored = comm.create_comm(target_name="jupyter.widget", data={})
        assert not isinstance(restored, TkwryComm)

        # Re-install for the rest of the suite (autouse fixture also does this).
        install_comm_backend()
        assert isinstance(
            comm.create_comm(target_name="jupyter.widget", data={}), TkwryComm
        )
