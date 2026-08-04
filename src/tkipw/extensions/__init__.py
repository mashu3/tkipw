"""Built-in adapters for libraries that normally target Jupyter.

Submodules are imported on attribute access so ``install_jupyter_support``
does not pull matplotlib / folium / bokeh / … just to register one adapter.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AltairExtension",
    "BokehExtension",
    "FoliumExtension",
    "MatplotlibExtension",
    "matplotlib_inline",
    "matplotlib_widget",
    "matplotlib_window",
    "sync_matplotlib_from_source",
    "PillowExtension",
    "PyVistaExtension",
]

_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "AltairExtension": (".altair", "AltairExtension"),
    "BokehExtension": (".bokeh", "BokehExtension"),
    "FoliumExtension": (".folium", "FoliumExtension"),
    "MatplotlibExtension": (".matplotlib", "MatplotlibExtension"),
    "matplotlib_inline": (".matplotlib", "matplotlib_inline"),
    "matplotlib_widget": (".matplotlib", "matplotlib_widget"),
    "matplotlib_window": (".matplotlib", "matplotlib_window"),
    "sync_matplotlib_from_source": (".matplotlib", "sync_matplotlib_from_source"),
    "PillowExtension": (".pillow", "PillowExtension"),
    "PyVistaExtension": (".pyvista", "PyVistaExtension"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
