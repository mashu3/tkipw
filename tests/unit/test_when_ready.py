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


def test_when_failed_queues_until_create_failed():
    app = App.__new__(App)
    app._destroyed = False
    app._creation_failed = False
    app._creation_error = None
    app._failed_callbacks = []
    app.root = MagicMock()
    scheduled: list[object] = []
    app.root.after_idle.side_effect = lambda cb: scheduled.append(cb)

    calls: list[str] = []
    app.when_failed(lambda exc: calls.append(str(exc)))
    assert calls == []
    assert len(app._failed_callbacks) == 1

    err = RuntimeError("no webview2")
    app._on_webview_create_failed(err)
    assert app._creation_failed
    assert app._failed_callbacks == []
    assert len(scheduled) == 1
    scheduled[0]()
    assert calls == ["no webview2"]


def test_when_failed_runs_after_idle_if_already_failed():
    app = App.__new__(App)
    app._destroyed = False
    app._creation_failed = True
    app._creation_error = RuntimeError("create failed")
    app._failed_callbacks = []
    app.root = MagicMock()
    scheduled: list[object] = []
    app.root.after_idle.side_effect = lambda cb: scheduled.append(cb)

    calls: list[str] = []
    app.when_failed(lambda exc: calls.append(str(exc)))
    assert app._failed_callbacks == []
    assert len(scheduled) == 1
    scheduled[0]()
    assert calls == ["create failed"]


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
