"""tkipw — ipywidgets / anywidget runtime on tkwry.

Heavy deps (``ipywidgets``, markdown renderers, App/WebView) load on first
attribute access. ``install_comm_backend()`` still runs at import so widgets
created after ``import tkipw`` use TkwryComm instead of DummyComm.
"""

from __future__ import annotations

from typing import Any

from .comm_backend import (
    install_comm_backend,
    uninstall_comm_backend,
)

# Install as early as possible so widgets created after ``import tkipw``
# use TkwryComm instead of DummyComm.
install_comm_backend()

__all__ = [
    "App",
    "Runtime",
    "WidgetFrame",
    "Output",
    "clear_output",
    "display",
    "display_error",
    "to_widget",
    "DisplayHandle",
    "update_display",
    "register_mime_renderer",
    "unregister_mime_renderer",
    "register_widget_module",
    "unregister_widget_module",
    "discover_widget_modules",
    "get_display_mode",
    "set_display_mode",
    "install_comm_backend",
    "uninstall_comm_backend",
    "JupyterExtension",
    "register_extension",
    "enable_extension",
    "get_extension",
    "install_jupyter_support",
    "uninstall_jupyter_support",
    # Lazy extension helpers (enable_matplotlib, …) are available via
    # ``from tkipw import enable_*`` / ``__getattr__``, but omitted here so
    # ``from tkipw import *`` does not pull optional heavy dependencies.
]
__version__ = "0.0.3"

_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "App": (".app", "App"),
    "Runtime": (".app", "Runtime"),
    "WidgetFrame": (".app", "WidgetFrame"),
    "Output": (".output", "Output"),
    "clear_output": (".output", "clear_output"),
    "display": (".output", "display"),
    "display_error": (".output", "display_error"),
    "to_widget": (".output", "to_widget"),
    "DisplayHandle": (".output", "DisplayHandle"),
    "update_display": (".output", "update_display"),
    "register_mime_renderer": (".output", "register_mime_renderer"),
    "unregister_mime_renderer": (".output", "unregister_mime_renderer"),
    "register_widget_module": (".widget_modules", "register_widget_module"),
    "unregister_widget_module": (".widget_modules", "unregister_widget_module"),
    "discover_widget_modules": (".widget_modules", "discover_widget_modules"),
    "get_display_mode": (".display_mode", "get_display_mode"),
    "set_display_mode": (".display_mode", "set_display_mode"),
    "JupyterExtension": (".jupyter", "JupyterExtension"),
    "register_extension": (".jupyter", "register_extension"),
    "enable_extension": (".jupyter", "enable_extension"),
    "get_extension": (".jupyter", "get_extension"),
    "install_jupyter_support": (".jupyter", "install_jupyter_support"),
    "uninstall_jupyter_support": (".jupyter", "uninstall_jupyter_support"),
    "enable_matplotlib": (".extensions.matplotlib", "enable_matplotlib"),
    "matplotlib_inline": (".extensions.matplotlib", "matplotlib_inline"),
    "matplotlib_widget": (".extensions.matplotlib", "matplotlib_widget"),
    "matplotlib_window": (".extensions.matplotlib", "matplotlib_window"),
    "enable_pyvista": (".extensions.pyvista", "enable_pyvista"),
    "enable_pillow": (".extensions.pillow", "enable_pillow"),
    "enable_altair": (".extensions.altair", "enable_altair"),
    "enable_bokeh": (".extensions.bokeh", "enable_bokeh"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    mod = import_module(module_name, __name__)
    value = getattr(mod, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_LAZY_ATTRS})
