"""``tkipw.jupyter``: extension registry, IPython bridge, install/uninstall.

No WebView required. Individual built-in adapters live in ``test_extensions.py``.
"""

from __future__ import annotations

import IPython.display as ipy_display
import ipywidgets as widgets
import pytest
from support import FakeApp

from tkipw.comm_backend import set_bridge
from tkipw.jupyter import (
    install_jupyter_support,
    register_extension,
    transform_display_object,
)
from tkipw.output import clear_output, to_widget


def test_ipython_display_bridge_forwards_to_output():
    install_jupyter_support()
    app = FakeApp()
    set_bridge(app)
    clear_output()

    w = widgets.HTML(value="<b>hi</b>")
    ipy_display.display(w)
    assert w in app._cell_output.children

    set_bridge(None)


def test_custom_extension_can_transform_objects():
    class Marker:
        pass

    class Extension:
        name = "test-marker"

        def setup(self) -> None:
            pass

        def transform(self, obj):
            return "transformed" if isinstance(obj, Marker) else obj

    register_extension(Extension())

    assert transform_display_object(Marker()) == "transformed"
    widget = to_widget(Marker())
    assert isinstance(widget, widgets.HTML)
    assert "transformed" in widget.value


def test_missing_optional_extension_does_not_block_install():
    class MissingExtension:
        name = "test-missing-optional"

        def setup(self) -> None:
            raise ImportError("optional dependency is unavailable")

        def transform(self, obj):
            raise AssertionError("disabled extension must not transform objects")

    register_extension(MissingExtension(), enable=False)

    install_jupyter_support()
    marker = object()
    assert transform_display_object(marker) is marker


def test_pyvista_extension_not_enabled_until_import():
    import sys

    from tkipw import jupyter as jupyter_mod

    jupyter_mod.uninstall_jupyter_support()
    try:
        install_jupyter_support()
        assert jupyter_mod._pyvista_import_hook_installed
        if "pyvista" not in sys.modules:
            assert "pyvista" not in jupyter_mod._enabled
    finally:
        jupyter_mod.uninstall_jupyter_support()


def test_pyvista_import_hook_waits_for_full_module_init():
    pytest.importorskip("pyvista")
    from tkipw import jupyter as jupyter_mod

    jupyter_mod.uninstall_jupyter_support()
    try:
        install_jupyter_support()
        import pyvista as pv  # noqa: F401

        assert "pyvista" in jupyter_mod._enabled
        assert pv.global_theme.notebook is True
    finally:
        jupyter_mod.uninstall_jupyter_support()


def test_install_uninstall_restores_ipython_display():
    ipy = pytest.importorskip("IPython.display")
    from tkipw.jupyter import uninstall_jupyter_support

    # Start clean so ``original`` is the genuine IPython display function.
    uninstall_jupyter_support()
    original = ipy.display

    install_jupyter_support()
    assert ipy.display is not original

    uninstall_jupyter_support()
    assert ipy.display is original
