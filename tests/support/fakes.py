"""Reusable test doubles for the display-free (unit) tests.

These stand in for a real :class:`tkipw.App` so protocol / routing / display
logic can be exercised without a Tk window or a native WebView.
"""

from __future__ import annotations

from typing import Any


class RecordingBridge:
    """Minimal bridge that records every message sent to the frontend.

    Use as the active bridge (via ``push_bridge`` / ``set_bridge``) to assert on
    the protocol messages a widget or comm produces.
    """

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.messages: list[dict[str, Any]] = []
        self._known_model_ids: set[str] = set()

    def send_to_js(self, msg: dict[str, Any]) -> None:
        if msg.get("msg_type") == "comm_open":
            comm_id = msg.get("comm_id")
            if isinstance(comm_id, str):
                self._known_model_ids.add(comm_id)
        self.messages.append(msg)

    def messages_of_type(self, msg_type: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m.get("msg_type") == msg_type]


class FakeApp:
    """App stand-in with an :class:`~tkipw.output.Output`-backed cell area.

    Enough surface for the display / IPython-bridge tests: ``send_to_js`` plus
    the ``_append_output`` / ``_clear_output`` hooks ``tkipw.output`` calls.
    """

    def __init__(self, *, display_mode: str = "inline") -> None:
        from tkipw.output import Output

        self.display_mode = display_mode
        self._cell_output = Output()
        self._cell_output_mounted = True
        self.messages: list[dict[str, Any]] = []

    def _append_output(self, items: list[Any]) -> None:
        self._cell_output._append(items)

    def _clear_output(self, wait: bool = False) -> None:
        self._cell_output.clear_output(wait=wait)

    def send_to_js(self, msg: dict[str, Any]) -> None:
        self.messages.append(msg)
