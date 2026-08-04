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
_enabling: set[str] = set()
_bridge_installed = False
_builtins_loaded = False
_original_ipython_display: Any | None = None
_original_builtins_import: Any | None = None
_lazy_import_hook_installed = False
_pyvista_enabling = False
_pyvista_import_depth = 0
_ipympl_enabling = False
_ipympl_import_depth = 0
_lazy_import_depths: dict[str, int] = {}


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
    if name in _enabled or name in _enabling:
        return
    extension = _extensions[name]
    _enabling.add(name)
    try:
        extension.setup()
        _enabled.add(name)
    finally:
        _enabling.discard(name)


def get_extension(name: str) -> JupyterExtension | None:
    """Return a registered extension by name, or ``None``."""
    return _extensions.get(name)


def transform_display_object(obj: Any) -> Any:
    """Apply enabled display transforms in registration order."""
    _ensure_extension_for_object(obj)
    current = obj
    for name, extension in tuple(_extensions.items()):
        if name in _enabled:
            current = extension.transform(current)
    return current


def install_jupyter_support() -> None:
    """Install IPython display routing; load library adapters on demand.

    Does **not** import matplotlib / folium / bokeh / pyvista / … up front.
    Those adapters register+enable when the matching package is imported or
    when ``transform_display_object`` sees an object from that package.
    """
    _install_ipython_display_bridge()
    _install_lazy_import_hook()
    # Packages already imported before the App (common in tests / scripts).
    _enable_extensions_for_imported_packages()


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
    _enabling.clear()
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
    """Deprecated no-op — builtins register on demand via ``_register_builtin``."""
    global _builtins_loaded
    _builtins_loaded = True


def _register_builtin(name: str) -> bool:
    """Import and register one built-in adapter module (does not enable)."""
    if name in _extensions:
        return True
    try:
        if name == "matplotlib":
            from .display_mode import get_display_mode
            from .extensions.matplotlib import MatplotlibExtension

            register_extension(
                MatplotlibExtension(mode=get_display_mode()), enable=False
            )
        elif name == "pyvista":
            from .extensions.pyvista import PyVistaExtension

            register_extension(PyVistaExtension(), enable=False)
        elif name == "pillow":
            from .extensions.pillow import PillowExtension

            register_extension(PillowExtension(), enable=False)
        elif name == "folium":
            from .extensions.folium import FoliumExtension

            register_extension(FoliumExtension(), enable=False)
        elif name == "altair":
            from .extensions.altair import AltairExtension

            register_extension(AltairExtension(), enable=False)
        elif name == "bokeh":
            from .extensions.bokeh import BokehExtension

            register_extension(BokehExtension(), enable=False)
        else:
            return False
    except ImportError:
        return False
    return name in _extensions


def _enable_builtin(name: str) -> None:
    """Register+enable one adapter; ignore missing optional dependencies."""
    if not _register_builtin(name):
        return
    try:
        enable_extension(name)
    except ImportError:
        pass


def _ensure_extension_for_object(obj: Any) -> None:
    """Enable the adapter that matches ``type(obj).__module__`` when needed."""
    module = type(obj).__module__ or ""
    if module.startswith("folium"):
        _enable_builtin("folium")
    elif module.startswith("ipympl"):
        _try_enable_ipympl()
    elif module.startswith("matplotlib") or module == "pylab":
        _enable_builtin("matplotlib")
    elif module.startswith("bokeh"):
        _enable_builtin("bokeh")
    elif module.startswith("altair"):
        _enable_builtin("altair")
    elif module.startswith(("PIL", "pillow")):
        _enable_builtin("pillow")
    elif module.startswith("pyvista"):
        _enable_builtin("pyvista")


def _package_key_for_import(name: str, *, level: int = 0) -> str | None:
    """Map an absolute third-party import name to a built-in adapter key.

    Relative imports (``level != 0``) and ``tkipw.*`` imports are ignored so
    loading ``tkipw.extensions.folium`` does not look like ``import folium``.
    """
    if level != 0:
        return None
    if name == "tkipw" or name.startswith("tkipw."):
        return None
    if name == "matplotlib" or name.startswith("matplotlib."):
        return "matplotlib"
    if name == "folium" or name.startswith("folium."):
        return "folium"
    if name == "bokeh" or name.startswith("bokeh."):
        return "bokeh"
    if name == "altair" or name.startswith("altair."):
        return "altair"
    if name in {"PIL", "Pillow"} or name.startswith("PIL."):
        return "pillow"
    if name == "pyvista" or name.startswith("pyvista."):
        return "pyvista"
    if name == "ipympl" or name.startswith("ipympl."):
        return "ipympl"
    return None


def _enable_extensions_for_imported_packages() -> None:
    """Enable adapters for third-party libs already present in ``sys.modules``."""
    import sys

    modules = sys.modules
    if any(k == "matplotlib" or k.startswith("matplotlib.") for k in modules):
        _enable_builtin("matplotlib")
    if any(k == "folium" or k.startswith("folium.") for k in modules):
        _enable_builtin("folium")
    if any(k == "bokeh" or k.startswith("bokeh.") for k in modules):
        _enable_builtin("bokeh")
    if any(k == "altair" or k.startswith("altair.") for k in modules):
        _enable_builtin("altair")
    if any(k == "PIL" or k.startswith("PIL.") for k in modules):
        _enable_builtin("pillow")
    if any(k == "pyvista" or k.startswith("pyvista.") for k in modules):
        _enable_builtin("pyvista")
    _try_enable_ipympl()
    _try_enable_pyvista()


def _try_enable_pyvista() -> None:
    """Enable the PyVista adapter once the library is imported."""
    global _pyvista_enabling
    if _pyvista_enabling or "pyvista" in _enabled:
        return
    if not _register_builtin("pyvista"):
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
    if _ipympl_enabling:
        return
    import sys

    if "ipympl" not in sys.modules and not any(
        name.startswith("ipympl.") for name in sys.modules
    ):
        return
    if not _register_builtin("matplotlib"):
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
    """Enable matching adapters when optional libraries are imported."""
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
        assert _original_builtins_import is not None
        key = _package_key_for_import(name, level=level)
        if key is not None:
            _lazy_import_depths[key] = _lazy_import_depths.get(key, 0) + 1
        try:
            module = _original_builtins_import(name, globals, locals, fromlist, level)
        finally:
            if key is not None:
                depth = _lazy_import_depths.get(key, 1) - 1
                if depth <= 0:
                    _lazy_import_depths.pop(key, None)
                    if key == "ipympl":
                        _try_enable_ipympl()
                    elif key == "pyvista":
                        _try_enable_pyvista()
                    elif (
                        key == "matplotlib" and _lazy_import_depths.get("ipympl", 0) > 0
                    ):
                        # Nested under ``import ipympl`` — do not enable the
                        # inline Agg adapter first; ``_try_enable_ipympl``
                        # switches straight to widget mode when ipympl finishes.
                        pass
                    else:
                        _enable_builtin(key)
                else:
                    _lazy_import_depths[key] = depth
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
    _lazy_import_depths.clear()
