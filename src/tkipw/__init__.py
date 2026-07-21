"""tkipw — ipywidgets / anywidget runtime on tkwry."""

from __future__ import annotations

from .app import App, Runtime
from .comm_backend import (
    install_comm_backend,
    uninstall_comm_backend,
)
from .display_mode import get_display_mode, set_display_mode
from .jupyter import (
    JupyterExtension,
    enable_extension,
    get_extension,
    install_jupyter_support,
    register_extension,
    uninstall_jupyter_support,
)
from .output import (
    Output,
    clear_output,
    display,
    display_error,
    to_widget,
)

# Install as early as possible so widgets created after ``import tkipw``
# use TkwryComm instead of DummyComm.
install_comm_backend()

__all__ = [
    "App",
    "Runtime",
    "Output",
    "clear_output",
    "display",
    "display_error",
    "to_widget",
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
__version__ = "0.0.2"


def __getattr__(name: str):
    if name in (
        "enable_matplotlib",
        "matplotlib_inline",
        "matplotlib_widget",
        "matplotlib_window",
    ):
        from .extensions.matplotlib import (
            enable_matplotlib,
            matplotlib_inline,
            matplotlib_widget,
            matplotlib_window,
        )

        return {
            "enable_matplotlib": enable_matplotlib,
            "matplotlib_inline": matplotlib_inline,
            "matplotlib_widget": matplotlib_widget,
            "matplotlib_window": matplotlib_window,
        }[name]
    if name == "enable_pyvista":
        from .extensions.pyvista import enable_pyvista

        return enable_pyvista
    if name == "enable_pillow":
        from .extensions.pillow import enable_pillow

        return enable_pillow
    if name == "enable_altair":
        from .extensions.altair import enable_altair

        return enable_altair
    if name == "enable_bokeh":
        from .extensions.bokeh import enable_bokeh

        return enable_bokeh
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
