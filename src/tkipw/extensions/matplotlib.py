"""Matplotlib adapter for tkipw's Jupyter compatibility layer."""

from __future__ import annotations

import base64
import io
import sys
from collections.abc import Callable
from typing import Any, Literal

MatplotlibDisplayMode = Literal["inline", "window"]


class MatplotlibExtension:
    """Matplotlib display adapter.

    Follows the active :class:`tkipw.App`'s ``display_mode``:

    * ``inline`` — ``plt.show()`` renders PNG into the notebook-style output
      area (Agg backend). Same spirit as ``%matplotlib inline``.
    * ``window`` — ``plt.show()`` opens native Tk figure windows (TkAgg).
      Same spirit as ``%matplotlib tk``. Interactive zoom/pan stay with
      Matplotlib; tkipw does not intercept ``show``.
    """

    name = "matplotlib"

    def __init__(
        self,
        *,
        mode: MatplotlibDisplayMode | None = None,
        force_agg: bool | None = None,
    ) -> None:
        if force_agg is not None:
            mode = "inline" if force_agg else "window"
        if mode is None:
            from ..display_mode import get_display_mode

            mode = get_display_mode()
        self.mode: MatplotlibDisplayMode = _validate_mode(mode)
        self.force_agg = self.mode == "inline"
        self._setup = False
        self._original_show: Callable[..., Any] | None = None
        self._original_figure: Callable[..., Any] | None = None
        self._window_ui_scale = 1.0

    def set_mode(self, mode: MatplotlibDisplayMode) -> None:
        """Switch between ``inline`` and ``window``, re-applying the backend."""
        mode = _validate_mode(mode)
        if mode == self.mode and self._setup:
            return
        was_setup = self._setup
        # Teardown under the *new* mode flag only for cleanup that is
        # mode-specific; clear figures before flipping so a failed TkAgg load
        # cannot hang ``plt.close("all")`` during the next switch.
        if was_setup:
            self.teardown()
        self.mode = mode
        self.force_agg = mode == "inline"
        if was_setup:
            self.setup()

    def setup(self) -> None:
        if self._setup:
            return

        import matplotlib

        if self.mode == "window":
            try:
                matplotlib.use("TkAgg", force=True)
            except Exception:
                # Headless / missing Tk builds cannot host interactive windows.
                # Leave the previous backend; ``show`` stays unpatched so the
                # native Matplotlib path still runs when Tk is available later.
                self._setup = True
                return
            # DPI figure scaling is Windows-only (process awareness is a no-op
            # elsewhere). Never import tkface on the critical Linux CI path.
            if sys.platform == "win32":
                try:
                    import tkface
                    from matplotlib import pyplot as plt

                    self._window_ui_scale = float(
                        tkface.win.get_windows_scale_factor()
                    )
                    if (
                        not tkface.win.is_process_dpi_aware()
                        and self._window_ui_scale != 1.0
                        and self._original_figure is None
                    ):
                        self._original_figure = plt.figure
                        scale = self._window_ui_scale
                        original_figure = self._original_figure

                        def figure(*args: Any, **kwargs: Any) -> Any:
                            dpi = kwargs.get("dpi")
                            if dpi is None:
                                dpi = matplotlib.rcParams.get("figure.dpi", 100)
                            try:
                                kwargs["dpi"] = float(dpi) * scale
                            except (TypeError, ValueError):
                                pass
                            return original_figure(*args, **kwargs)

                        plt.figure = figure  # type: ignore[assignment]
                except Exception:
                    self._window_ui_scale = 1.0
            self._setup = True
            return

        if self.force_agg:
            try:
                matplotlib.use("Agg", force=True)
            except Exception:
                pass

        from matplotlib import pyplot as plt

        self._original_show = plt.show
        extension = self

        def show(*_args: Any, **_kwargs: Any) -> None:
            from ..output import display

            figs = [plt.figure(n) for n in plt.get_fignums()]  # type: ignore[misc]
            if not figs:
                if extension._original_show is not None:
                    return extension._original_show(*_args, **_kwargs)
                return
            to_show = list(figs)
            try:
                display(*to_show)
            finally:
                for fig in to_show:
                    plt.close(fig)

        plt.show = show  # type: ignore[assignment]
        self._setup = True

    def teardown(self) -> None:
        if not self._setup:
            return
        # Prefer Agg for cleanup so a half-initialized TkAgg cannot block CI.
        if self.mode == "window":
            try:
                import matplotlib

                matplotlib.use("Agg", force=True)
            except Exception:
                pass
            _close_all_figures()
        if self._original_figure is not None:
            from matplotlib import pyplot as plt

            plt.figure = self._original_figure  # type: ignore[assignment]
            self._original_figure = None
            self._window_ui_scale = 1.0
        if self._original_show is not None:
            from matplotlib import pyplot as plt

            plt.show = self._original_show  # type: ignore[assignment]
            self._original_show = None
        self._setup = False

    def transform(self, obj: Any) -> Any:
        # Explicit ``display(fig)`` / ``to_widget(fig)`` always get a PNG, even
        # in window mode — useful when embedding a figure into an Output cell.
        from matplotlib.figure import Figure

        if isinstance(obj, Figure):
            import ipywidgets as widgets

            buffer = io.BytesIO()
            obj.savefig(buffer, format="png", bbox_inches="tight")
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return widgets.HTML(
                value=(
                    '<img alt="figure" '
                    'style="max-width:100%;height:auto;display:block" '
                    f'src="data:image/png;base64,{encoded}"/>'
                )
            )
        return obj


def _close_all_figures() -> None:
    try:
        from matplotlib import pyplot as plt

        plt.close("all")
    except Exception:
        pass


def _validate_mode(mode: str) -> MatplotlibDisplayMode:
    if mode not in ("inline", "window"):
        raise ValueError(
            f"matplotlib display mode must be 'inline' or 'window', got {mode!r}"
        )
    return mode  # type: ignore[return-value]


def enable_matplotlib(
    *,
    mode: MatplotlibDisplayMode | None = None,
    force_agg: bool | None = None,
) -> None:
    """Enable Matplotlib and update the active App's display mode.

    Prefer ``App(display_mode=...)`` for new code; this helper remains for
    ``%matplotlib inline`` / ``tk`` style muscle memory and runtime changes.

    Parameters
    ----------
    mode:
        ``"inline"`` or ``"window"``. Defaults to the active App's mode.
    force_agg:
        Deprecated alias: ``True`` → ``inline``, ``False`` → ``window``.
    """
    from ..display_mode import set_display_mode
    from ..jupyter import get_extension, register_extension

    if force_agg is not None:
        mode = "inline" if force_agg else "window"
    if mode is None:
        from ..display_mode import get_display_mode

        mode = get_display_mode()
    mode = _validate_mode(mode)

    existing = get_extension("matplotlib")
    if not isinstance(existing, MatplotlibExtension):
        # Register without enabling yet; the mode setter enables + syncs.
        register_extension(MatplotlibExtension(mode=mode), enable=False)

    set_display_mode(mode)


def matplotlib_inline() -> None:
    """Switch the active App to inline mode with Matplotlib enabled."""
    enable_matplotlib(mode="inline")


def matplotlib_window() -> None:
    """Switch the active App to window mode — ``%matplotlib tk`` style."""
    enable_matplotlib(mode="window")
