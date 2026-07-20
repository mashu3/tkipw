"""PyVista adapter for tkipw's generic Jupyter compatibility layer."""

from __future__ import annotations

import atexit
import warnings
from types import MethodType
from typing import Any

from ..html_host import demote_module_scripts, host_srcdoc_iframe

# Modes that keep PyVista's Jupyter/trame stack but avoid a native VTK
# OpenGL window (Cocoa SIGTRAP under WKWebView; also unwanted on Windows).
_UNSAFE_LIVE_BACKENDS = frozenset({"trame", "server"})


class PyVistaExtension:
    """Make PyVista's notebook API render in the tkipw output area.

    Uses the same call chain as Jupyter::

        handle_plotter → show_trame → ipywidgets.Widget → IPython.display

    ``trame`` / ``server`` are remapped to ``client`` because server-side VTK
    rendering opens a native OpenGL window instead of the WebView. ``html``
    stays on the offline vtk.js path and does not need trame.
    """

    name = "pyvista"

    def __init__(self, *, backend: str | None = None) -> None:
        self.backend = backend
        self._setup = False
        self._trame_available = False
        self._servers: list[Any] = []
        self._shutdown_registered = False
        self._original_handle: Any = None
        self._original_launch_server: Any = None
        self._original_in_ipykernel: Any = None

    def setup(self) -> None:
        if self._setup:
            return
        import sys

        pv = sys.modules.get("pyvista")
        if pv is None:
            import pyvista as pv  # noqa: PLC0415

        import scooby
        from pyvista.jupyter import notebook as pv_notebook

        # PyVista only honors jupyter_backend when Plotter.notebook is True.
        # Outside ipykernel that defaults to False and a native VTK window opens
        # (the "Ignoring jupyter_backend" warning). Force notebook mode first so
        # a missing trame install cannot skip this step.
        pv.global_theme.notebook = True
        if self._original_in_ipykernel is None:
            self._original_in_ipykernel = scooby.in_ipykernel
            scooby.in_ipykernel = lambda: True  # type: ignore[assignment]

        original_handle = pv_notebook.handle_plotter
        self._original_handle = original_handle
        extension = self

        def handle_plotter(
            plotter: Any,
            backend: str | None = None,
            **kwargs: Any,
        ) -> Any:
            # Scripts may reset the theme; keep notebook mode sticky.
            pv.global_theme.notebook = True
            backend = extension._coerce_backend(backend)
            viewer = original_handle(plotter, backend=backend, **kwargs)
            return extension.transform(viewer)

        pv_notebook.handle_plotter = handle_plotter  # type: ignore[assignment]

        try:
            from pyvista.trame import jupyter as pv_jupyter
        except ImportError:
            self._trame_available = False
            self._apply_preferred_backend(pv)
            self._setup = True
            return

        self._trame_available = True
        from ..jupyter import get_jupyter_event_loop

        original_launch_server = pv_jupyter.launch_server
        self._original_launch_server = original_launch_server

        def elegantly_launch(*args: Any, **kwargs: Any) -> Any:
            """Launch trame on the persistent loop Jupyter normally provides."""

            async def launch() -> Any:
                server_arg = args[0] if args else kwargs.get("server")
                if server_arg is None:
                    server_arg = pv.global_theme.trame.jupyter_server_name
                server = (
                    pv_jupyter.get_server(server_arg)
                    if isinstance(server_arg, str)
                    else server_arg
                )
                original_start = server.start

                def start_with_no_signals(
                    _server_self: Any,
                    *start_args: Any,
                    **start_kwargs: Any,
                ) -> Any:
                    # Helper-thread loop: aiohttp must not install signals.
                    start_kwargs["thread"] = True
                    return original_start(*start_args, **start_kwargs)

                server.start = MethodType(start_with_no_signals, server)
                try:
                    launched = original_launch_server(*args, **kwargs)
                finally:
                    server.start = original_start
                await launched.ready
                if server not in extension._servers:
                    extension._servers.append(server)
                return launched

            loop = get_jupyter_event_loop()
            if not extension._shutdown_registered:
                atexit.register(extension._shutdown)
                extension._shutdown_registered = True
            return loop.submit(launch()).result(timeout=30)

        pv_jupyter.elegantly_launch = elegantly_launch
        self._apply_preferred_backend(pv)
        self._setup = True

    def teardown(self) -> None:
        if not self._setup:
            return
        import scooby
        from pyvista.jupyter import notebook as pv_notebook

        self._shutdown()
        if self._original_handle is not None:
            pv_notebook.handle_plotter = self._original_handle
        if self._trame_available and self._original_launch_server is not None:
            from pyvista.trame import jupyter as pv_jupyter

            pv_jupyter.elegantly_launch = self._original_launch_server
        if self._original_in_ipykernel is not None:
            scooby.in_ipykernel = self._original_in_ipykernel
        self._original_handle = None
        self._original_launch_server = None
        self._original_in_ipykernel = None
        self._trame_available = False
        self._setup = False

    def _apply_preferred_backend(self, pv: Any) -> None:
        preferred = self._coerce_backend(self.backend)
        if preferred is None:
            return
        try:
            pv.set_jupyter_backend(preferred)
        except Exception:
            pass

    def _coerce_backend(self, backend: str | None) -> str | None:
        if backend in _UNSAFE_LIVE_BACKENDS:
            warnings.warn(
                f"pyvista jupyter_backend={backend!r} opens a native VTK window; "
                "using jupyter_backend='client' for the WebView path.",
                RuntimeWarning,
                stacklevel=3,
            )
            backend = "client"

        if backend is None:
            try:
                import pyvista as pv

                current = pv.global_theme.jupyter_backend
            except Exception:
                current = None
            if current in _UNSAFE_LIVE_BACKENDS or current is None:
                backend = "client"
            else:
                backend = current

        if backend in ("client", "trame", "server") and not self._trame_available:
            warnings.warn(
                "pyvista trame extras are not installed; "
                "using jupyter_backend='html'. "
                'Install with: pip install "pyvista[jupyter]"',
                RuntimeWarning,
                stacklevel=3,
            )
            return "html"

        return backend

    def _shutdown(self) -> None:
        if not self._servers:
            return
        from ..jupyter import get_jupyter_event_loop

        loop = get_jupyter_event_loop()
        for server in tuple(self._servers):
            try:
                loop.submit(server.stop()).result(timeout=3)
            except Exception:
                pass
        self._servers.clear()

    def transform(self, obj: Any) -> Any:
        module = type(obj).__module__ or ""
        value = getattr(obj, "value", None)
        if "pyvista" not in module or not isinstance(value, str):
            return obj
        # Offline html backend only: rewrite large srcdoc → loopback URL.
        # Live client/trame widgets already use http://localhost from show_trame.
        hosted = host_srcdoc_iframe(
            value,
            document_transform=demote_module_scripts,
        )
        if hosted is not None:
            obj.value = hosted
        return obj


def enable_pyvista(*, jupyter_backend: str | None = None) -> None:
    """Public convenience API for enabling the built-in adapter."""
    from ..jupyter import register_extension

    register_extension(PyVistaExtension(backend=jupyter_backend))
