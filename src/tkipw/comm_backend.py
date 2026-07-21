"""Comm backend that bridges ipywidgets/anywidget to the active tkipw App."""

from __future__ import annotations

import base64
import json
import threading
from typing import Any

import comm
from comm.base_comm import BaseComm

_install_lock = threading.Lock()
_installed = False
_original_create_comm: Any | None = None
_original_widget_open: Any | None = None

# Widgets may be constructed before App() exists; queue until a bridge is ready.
_pending: list[dict[str, Any]] = []
# Stack of active App bridges. The top of the stack receives new comm traffic,
# so multiple Apps can coexist and destroying one restores the previous.
_bridge_stack: list[Any] = []
_comms: dict[str, TkwryComm] = {}


def get_bridge() -> Any | None:
    """Return the currently active App bridge (top of the stack)."""
    return _bridge_stack[-1] if _bridge_stack else None


def _flush_pending_to(app: Any) -> None:
    while _pending:
        msg = _pending.pop(0)
        app.send_to_js(msg)


def push_bridge(app: Any) -> None:
    """Activate *app* as the current bridge (moving it to the top if present)."""
    if app is None:
        return
    try:
        _bridge_stack.remove(app)
    except ValueError:
        pass
    _bridge_stack.append(app)
    _flush_pending_to(app)


def pop_bridge(app: Any) -> None:
    """Remove *app* from the bridge stack; the previous App becomes active."""
    try:
        _bridge_stack.remove(app)
    except ValueError:
        pass


def set_bridge(app: Any | None) -> None:
    """Replace the whole bridge stack with *app* (or clear it when ``None``).

    Kept for backwards compatibility; prefer :func:`push_bridge` /
    :func:`pop_bridge` when several Apps may be alive at once.
    """
    _bridge_stack.clear()
    if app is None:
        return
    _bridge_stack.append(app)
    _flush_pending_to(app)


def reset_comms() -> None:
    """Drop the comm registry and any queued-but-undelivered messages."""
    _comms.clear()
    _pending.clear()


def register_comm(c: TkwryComm) -> None:
    _comms[c.comm_id] = c


def unregister_comm(comm_id: str) -> None:
    _comms.pop(comm_id, None)


def get_comm(comm_id: str) -> TkwryComm | None:
    return _comms.get(comm_id)


def _encode_buffers(buffers: list[bytes] | None) -> list[str]:
    if not buffers:
        return []
    return [base64.b64encode(b).decode("ascii") for b in buffers]


def _decode_buffers(buffers: list[str] | None) -> list[bytes]:
    if not buffers:
        return []
    return [base64.b64decode(b) for b in buffers]


def _publish(msg: dict[str, Any]) -> None:
    if not _bridge_stack:
        _pending.append(msg)
        return
    # Fan-out live updates to every App that already hosts this model.
    # Window-mode pop-ups replay ``comm_open`` into a second JS manager; trait
    # / custom-message traffic must reach those managers too, not only the
    # currently active (usually host) bridge.
    msg_type = msg.get("msg_type")
    comm_id = msg.get("comm_id")
    if msg_type == "comm_msg" and isinstance(comm_id, str):
        targets = [
            bridge
            for bridge in _bridge_stack
            if comm_id in getattr(bridge, "_known_model_ids", ())
        ]
        if targets:
            for bridge in targets:
                bridge.send_to_js(msg)
            return
    _bridge_stack[-1].send_to_js(msg)


class TkwryComm(BaseComm):
    """BaseComm that serializes Jupyter comm messages over tkwry IPC."""

    def publish_msg(
        self,
        msg_type: str,
        data=None,
        metadata=None,
        buffers=None,
        **keys: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "channel": "comm",
            "msg_type": msg_type,
            "comm_id": self.comm_id,
            "data": data or {},
            "metadata": metadata or {},
            "buffers": _encode_buffers(buffers),
        }
        if "target_name" in keys:
            payload["target_name"] = keys["target_name"]
        if "target_module" in keys:
            payload["target_module"] = keys["target_module"]
        register_comm(self)
        _publish(payload)

    def deliver_from_js(
        self,
        data: dict[str, Any],
        buffers: list[str] | None = None,
    ) -> None:
        """Deliver a frontend comm_msg into the Python widget callbacks."""
        msg = {
            "content": {
                "comm_id": self.comm_id,
                "data": data,
            },
            "buffers": _decode_buffers(buffers),
        }
        self.handle_msg(msg)


def create_tkwry_comm(*args: Any, **kwargs: Any) -> TkwryComm:
    return TkwryComm(*args, **kwargs)


def _open_widget_with_deps(widget: Any, *args: Any, **kwargs: Any) -> Any:
    """Open dependency widgets before *widget* so nested ``IPY_MODEL`` refs resolve.

    ipycanvas shares a process-wide ``CanvasManager``. That manager may already
    hold a :class:`TkwryComm` from an earlier App; replaying its ``comm_open``
    into the active bridge must happen before ``Canvas`` itself opens, or the
    frontend falls back to an error widget.
    """
    if _original_widget_open is None:
        raise RuntimeError("widget open patch is not installed")
    bridge = get_bridge()
    for ref in _iter_widget_refs(widget):
        if ref is widget:
            continue
        current = getattr(ref, "comm", None)
        if isinstance(current, TkwryComm):
            register_comm(current)
            if bridge is not None:
                replay_widget_open(ref, bridge)
            continue
        # Nested open also runs this patched path (deps-of-deps first).
        ref.open()
    return _original_widget_open(widget, *args, **kwargs)


def install_comm_backend() -> None:
    """Replace ``comm.create_comm`` so new widgets use :class:`TkwryComm`."""
    global _installed, _original_create_comm, _original_widget_open
    with _install_lock:
        if _installed:
            return
        _original_create_comm = comm.create_comm
        comm.create_comm = create_tkwry_comm  # type: ignore[assignment]

        from ipywidgets import Widget

        _original_widget_open = Widget.open
        Widget.open = _open_widget_with_deps  # type: ignore[method-assign]
        _installed = True


def uninstall_comm_backend() -> None:
    """Restore the original ``comm.create_comm`` (undo :func:`install_comm_backend`)."""
    global _installed, _original_create_comm, _original_widget_open
    with _install_lock:
        if not _installed:
            return
        if _original_create_comm is not None:
            comm.create_comm = _original_create_comm  # type: ignore[assignment]
        _original_create_comm = None
        if _original_widget_open is not None:
            from ipywidgets import Widget

            Widget.open = _original_widget_open  # type: ignore[method-assign]
            _original_widget_open = None
        _installed = False


def ensure_widget_comm(widget: Any) -> None:
    """If a widget still has a DummyComm, reopen it on the tkwry backend."""
    from comm import DummyComm

    install_comm_backend()
    current = getattr(widget, "comm", None)
    if isinstance(current, TkwryComm):
        register_comm(current)
        return
    model_id = None
    if current is not None:
        model_id = getattr(current, "comm_id", None)
        try:
            # Avoid DummyComm publishing on close.
            if isinstance(current, DummyComm):
                current._closed = True  # noqa: SLF001
        except Exception:
            pass
        widget.comm = None
    if model_id is not None:
        widget._model_id = model_id
    widget.open()


def replay_widget_open(widget: Any, bridge: Any) -> None:
    """Send a widget's current ``comm_open`` state to another App.

    Widgets may be created while a host App is active and then displayed in a
    window-mode pop-up. Comms are process-global, but each App has an
    independent JavaScript manager, so the target App needs the model's open
    state replayed once.
    """
    comm_id = widget.model_id
    known = getattr(bridge, "_known_model_ids", None)
    if known is not None and comm_id in known:
        return

    from ipywidgets.widgets.widget import __protocol_version__, _remove_buffers

    state, buffer_paths, buffers = _remove_buffers(widget.get_state())
    bridge.send_to_js(
        {
            "channel": "comm",
            "msg_type": "comm_open",
            "comm_id": comm_id,
            "target_name": "jupyter.widget",
            "data": {"state": state, "buffer_paths": buffer_paths},
            "metadata": {"version": __protocol_version__},
            "buffers": _encode_buffers(buffers),
        }
    )


def _iter_widget_refs(widget: Any) -> list[Any]:
    """Return Widget-valued trait refs (scalars, sequences, and dict values)."""
    from ipywidgets import Widget

    refs: list[Any] = []
    try:
        names = widget.trait_names()
    except Exception:
        return refs
    for name in names:
        try:
            value = getattr(widget, name)
        except Exception:
            continue
        if isinstance(value, Widget):
            refs.append(value)
        elif isinstance(value, (list, tuple)):
            refs.extend(item for item in value if isinstance(item, Widget))
        elif isinstance(value, dict):
            refs.extend(item for item in value.values() if isinstance(item, Widget))
    return refs


def walk_widgets(root: Any) -> list[Any]:
    """Collect a widget tree in dependency order (refs before parents).

    Order matters when replaying ``comm_open`` into another App's JS manager:
    ``HTMLModel`` cannot instantiate until its ``Layout`` / ``Style`` models
    already exist. The same applies beyond ``children`` — e.g. ipyleaflet
    ``Map.layers`` / ``Map.controls`` / ``Map.default_style``.
    """
    from ipywidgets import Widget

    seen: set[str] = set()
    out: list[Any] = []

    def _add(w: Any) -> None:
        if w is None or not isinstance(w, Widget):
            return
        wid = getattr(w, "model_id", None) or id(w)
        key = str(wid)
        if key in seen:
            return
        seen.add(key)
        for ref in _iter_widget_refs(w):
            _add(ref)
        out.append(w)

    _add(root)
    return out


def dumps_safe(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
