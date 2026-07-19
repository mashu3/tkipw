"""Widget display helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .comm_backend import ensure_widget_comm, replay_widget_open, walk_widgets
from .output import to_widget


def prepare_widgets(objs: Iterable[Any], *, bridge: Any | None = None) -> list[str]:
    """Ensure live comms for a widget tree; return root model ids."""
    model_ids: list[str] = []
    for obj in objs:
        widget = to_widget(obj)
        for w in walk_widgets(widget):
            ensure_widget_comm(w)
            if bridge is not None:
                replay_widget_open(w, bridge)
        model_ids.append(widget.model_id)
    return model_ids
