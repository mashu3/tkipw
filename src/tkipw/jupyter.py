"""Jupyter compatibility layer and display-extension registry."""

from __future__ import annotations

import asyncio
import atexit
import builtins
import threading
from collections import OrderedDict
from typing import Any, Protocol


class JupyterExtension(Protocol):
    """Adapter for a library's Jupyter display behavior."""

    name: str

    def setup(self) -> None:
        """Configure the library for a notebook-like frontend."""

    def transform(self, obj: Any) -> Any:
        """Prepare a display object for tkipw's WebView."""


_extensions: OrderedDict[str, JupyterExtension] = OrderedDict()
_enabled: set[str] = set()
_bridge_installed = False
_builtins_loaded = False
_original_ipython_display: Any | None = None
_original_builtins_import: Any | None = None
_lazy_import_hook_installed = False
_pyvista_enabling = False
_pyvista_import_depth = 0
_ipympl_enabling = False
_ipympl_import_depth = 0


class JupyterEventLoop:
    """Persistent asyncio loop for Jupyter backends inside a Tk application."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="tkipw-jupyter-event-loop",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def submit(self, coroutine: Any):
        """Run a coroutine on the persistent loop."""
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def stop(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=3)
        if not self._loop.is_running() and not self._loop.is_closed():
            self._loop.close()


_event_loop: JupyterEventLoop | None = None
_event_loop_lock = threading.Lock()


def get_jupyter_event_loop() -> JupyterEventLoop:
    """Return the shared asyncio loop used by live Jupyter backends."""
    global _event_loop
    with _event_loop_lock:
        if _event_loop is None:
            _event_loop = JupyterEventLoop()
            atexit.register(_event_loop.stop)
        return _event_loop


def register_extension(
    extension: JupyterExtension,
    *,
    enable: bool = True,
) -> None:
    """Register a Jupyter adapter, optionally enabling it immediately."""
    existing = _extensions.get(extension.name)
    if existing is not None:
        if type(existing) is not type(extension):
            raise ValueError(
                f"Jupyter extension {extension.name!r} is already registered"
            )
        extension = existing
    _extensions[extension.name] = extension
    if enable:
        enable_extension(extension.name)


def enable_extension(name: str) -> None:
    """Enable a registered extension once."""
    if name in _enabled:
        return
    extension = _extensions[name]
    extension.setup()
    _enabled.add(name)


def get_extension(name: str) -> JupyterExtension | None:
    """Return a registered extension by name, or ``None``."""
    return _extensions.get(name)


def transform_display_object(obj: Any) -> Any:
    """Apply enabled display transforms in registration order."""
    current = obj
    for name, extension in tuple(_extensions.items()):
        if name in _enabled:
            current = extension.transform(current)
    return current


def install_jupyter_support() -> None:
    """Install IPython display routing and available built-in adapters."""
    _install_ipython_display_bridge()
    _load_builtin_extensions()
    # Defer PyVista / ipympl side effects until those packages are imported.
    _install_lazy_import_hook()
    # Re-enable registered extensions after a previous teardown.
    for name in tuple(_extensions):
        if name == "pyvista":
            # PyVista pulls in VTK/trame/aiohttp at setup time. Loading that
            # stack during App startup races WebView2 creation on Windows.
            continue
        try:
            enable_extension(name)
        except ImportError:
            # Built-in adapters target optional dependencies. An unavailable
            # library must not prevent the remaining display bridge from
            # being installed.
            continue
    # If ipympl was imported before the App, switch Matplotlib now.
    _try_enable_ipympl()


def _install_ipython_display_bridge() -> None:
    global _bridge_installed, _original_ipython_display
    if _bridge_installed:
        return
    try:
        import IPython.display as ipy_display
    except ImportError:
        return

    from .output import display as tkipw_display

    _original_ipython_display = ipy_display.display

    def _bridged(*objs: Any, **_kwargs: Any) -> None:
        if objs:
            # ``output.to_widget`` is the canonical transform gateway.
            tkipw_display(*objs)

    ipy_display.display = _bridged  # type: ignore[assignment]
    _bridge_installed = True


def uninstall_jupyter_support() -> None:
    """Restore ``IPython.display.display`` (undo the display bridge)."""
    global _bridge_installed, _original_ipython_display
    for name in reversed(tuple(_extensions)):
        if name not in _enabled:
            continue
        teardown = getattr(_extensions[name], "teardown", None)
        if callable(teardown):
            try:
                teardown()
            except Exception:
                pass
    _enabled.clear()
    _uninstall_lazy_import_hook()

    if not _bridge_installed:
        return
    try:
        import IPython.display as ipy_display
    except ImportError:
        _bridge_installed = False
        _original_ipython_display = None
        return
    if _original_ipython_display is not None:
        ipy_display.display = _original_ipython_display  # type: ignore[assignment]
    _bridge_installed = False
    _original_ipython_display = None


def _load_builtin_extensions() -> None:
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True

    try:
        from .display_mode import get_display_mode
        from .extensions.matplotlib import MatplotlibExtension

        register_extension(MatplotlibExtension(mode=get_display_mode()), enable=False)
    except ImportError:
        pass

    try:
        from .extensions.pyvista import PyVistaExtension

        register_extension(PyVistaExtension(), enable=False)
    except ImportError:
        pass

    try:
        from .extensions.pillow import PillowExtension

        register_extension(PillowExtension(), enable=False)
    except ImportError:
        pass

    try:
        from .extensions.folium import FoliumExtension

        register_extension(FoliumExtension(), enable=False)
    except ImportError:
        pass

    try:
        from .extensions.altair import AltairExtension

        register_extension(AltairExtension(), enable=False)
    except ImportError:
        pass

    try:
        from .extensions.bokeh import BokehExtension

        register_extension(BokehExtension(), enable=False)
    except ImportError:
        pass


def _try_enable_pyvista() -> None:
    """Enable the PyVista adapter once the library is imported."""
    global _pyvista_enabling
    if _pyvista_enabling or "pyvista" not in _extensions or "pyvista" in _enabled:
        return
    import sys

    if "pyvista" not in sys.modules:
        return
    pv = sys.modules.get("pyvista")
    if pv is None or not hasattr(pv, "global_theme"):
        return
    _pyvista_enabling = True
    try:
        enable_extension("pyvista")
    except ImportError:
        pass
    finally:
        _pyvista_enabling = False


def _try_enable_ipympl() -> None:
    """Switch Matplotlib to the ipympl WebView backend after ``import ipympl``.

    Plain ``import matplotlib`` keeps the App's inline PNG / window TkAgg path.
    """
    global _ipympl_enabling
    if _ipympl_enabling or "matplotlib" not in _extensions:
        return
    import sys

    if "ipympl" not in sys.modules and not any(
        name.startswith("ipympl.") for name in sys.modules
    ):
        return

    from .extensions.matplotlib import MatplotlibExtension

    existing = get_extension("matplotlib")
    if (
        isinstance(existing, MatplotlibExtension)
        and existing.mode == "widget"
        and getattr(existing, "_setup", False)
    ):
        return

    _ipympl_enabling = True
    try:
        from .extensions.matplotlib import enable_matplotlib

        enable_matplotlib(mode="widget")
    except ImportError:
        pass
    finally:
        _ipympl_enabling = False


def _install_lazy_import_hook() -> None:
    """Defer PyVista / ipympl setup until those packages are imported."""
    global _lazy_import_hook_installed, _original_builtins_import
    if _lazy_import_hook_installed:
        return
    _original_builtins_import = builtins.__import__

    def _hooked_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        global _pyvista_import_depth, _ipympl_import_depth
        assert _original_builtins_import is not None
        track_pyvista = name == "pyvista" or name.startswith("pyvista.")
        track_ipympl = name == "ipympl" or name.startswith("ipympl.")
        if track_pyvista:
            _pyvista_import_depth += 1
        if track_ipympl:
            _ipympl_import_depth += 1
        try:
            module = _original_builtins_import(name, globals, locals, fromlist, level)
        finally:
            if track_pyvista:
                _pyvista_import_depth -= 1
                if _pyvista_import_depth == 0:
                    _try_enable_pyvista()
            if track_ipympl:
                _ipympl_import_depth -= 1
                if _ipympl_import_depth == 0:
                    _try_enable_ipympl()
        return module

    builtins.__import__ = _hooked_import  # type: ignore[assignment]
    _lazy_import_hook_installed = True


def _uninstall_lazy_import_hook() -> None:
    global _lazy_import_hook_installed, _original_builtins_import
    if not _lazy_import_hook_installed or _original_builtins_import is None:
        return
    builtins.__import__ = _original_builtins_import
    _original_builtins_import = None
    _lazy_import_hook_installed = False
