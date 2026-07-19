"""Shared pytest fixtures and Tk event-loop helpers.

Most tests are pure-Python and need no display. The WebView end-to-end tests
in ``test_e2e_webview.py`` use ``tk_root`` plus the ``pump`` / ``wait_until``
helpers below to drive a real Tk + tkwry WebView.
"""

from __future__ import annotations

import glob
import os
import sys
import time
from collections.abc import Callable

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "e2e: requires a display and a native tkwry WebView (opt in with TKIPW_E2E=1)",
    )
    _ensure_windows_tcl_env()


def _ensure_windows_tcl_env() -> None:
    """Point Tcl/Tk at the bundled runtime (CI can fail to auto-detect)."""
    if os.name != "nt":
        return
    tcl_root = os.path.join(sys.prefix, "tcl")
    if not os.path.isdir(tcl_root):
        return
    if "TCL_LIBRARY" not in os.environ:
        hits = glob.glob(os.path.join(tcl_root, "tcl*", "init.tcl"))
        if hits:
            os.environ["TCL_LIBRARY"] = os.path.dirname(hits[0])
    if "TK_LIBRARY" not in os.environ:
        hits = glob.glob(os.path.join(tcl_root, "tk*", "tk.tcl"))
        if hits:
            os.environ["TK_LIBRARY"] = os.path.dirname(hits[0])


def _create_tk_root():
    import tkinter as tk

    _ensure_windows_tcl_env()
    last_err: tk.TclError | None = None
    for attempt in range(5):
        try:
            root = tk.Tk()
            root.geometry("640x480")
            return root
        except tk.TclError as exc:  # pragma: no cover - environment dependent
            last_err = exc
            if attempt + 1 < 5:
                time.sleep(0.25 * (attempt + 1))
    assert last_err is not None
    raise last_err


@pytest.fixture
def tk_root():
    import tkinter as tk

    try:
        root = _create_tk_root()
    except tk.TclError as exc:  # pragma: no cover - no display available
        pytest.skip(f"Tk unavailable: {exc}")
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def pump(root, *, steps: int = 80, delay_ms: int = 40) -> None:
    """Drive the Tk (and, on Linux, GTK) event loop for up to *steps* iterations."""
    for _ in range(steps):
        root.update_idletasks()
        root.update()
        if sys.platform == "linux":
            try:
                from tkwry._core import ensure_gtk_init, pump_events

                ensure_gtk_init()
                pump_events()
            except Exception:
                pass
        root.after(delay_ms)
        root.update()


def wait_until(root, predicate: Callable[[], bool], *, steps: int = 200) -> bool:
    """Return True once *predicate* is truthy, else False after *steps* pumps."""
    for _ in range(steps):
        if predicate():
            return True
        pump(root, steps=1, delay_ms=25)
    return predicate()
