"""App.when_ready scheduling (no WebView boot required)."""

from __future__ import annotations

from unittest.mock import MagicMock

from tkipw.app import App


def test_when_ready_queues_until_ready_channel():
    app = App.__new__(App)
    app._destroyed = False
    app._ready = False
    app._ready_callbacks = []
    app.root = MagicMock()
    scheduled: list[object] = []
    app.root.after_idle.side_effect = lambda cb: scheduled.append(cb)

    calls: list[str] = []
    app.when_ready(lambda: calls.append("a"))
    assert calls == []
    assert len(app._ready_callbacks) == 1

    app._fire_ready_callbacks()
    assert app._ready_callbacks == []
    assert len(scheduled) == 1
    scheduled[0]()
    assert calls == ["a"]


def test_when_ready_runs_after_idle_if_already_ready():
    app = App.__new__(App)
    app._destroyed = False
    app._ready = True
    app._ready_callbacks = []
    app.root = MagicMock()
    scheduled: list[object] = []
    app.root.after_idle.side_effect = lambda cb: scheduled.append(cb)

    calls: list[str] = []
    app.when_ready(lambda: calls.append("b"))
    assert app._ready_callbacks == []
    assert len(scheduled) == 1
    scheduled[0]()
    assert calls == ["b"]
