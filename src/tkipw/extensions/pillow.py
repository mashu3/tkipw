"""Pillow adapter: render ``Image.show()`` inside the tkipw output area."""

from __future__ import annotations

import base64
import io
from collections.abc import Callable
from typing import Any


class PillowExtension:
    """Route Pillow images and ``Image.show()`` to notebook-style output."""

    name = "pillow"

    def __init__(self) -> None:
        self._setup = False
        self._original_show: Callable[..., Any] | None = None

    def setup(self) -> None:
        if self._setup:
            return
        from PIL import Image

        self._original_show = Image.Image.show

        def show(image: Any, title: str | None = None) -> None:
            from ..output import display

            del title  # The output area has no native viewer window title.
            display(image)

        Image.Image.show = show  # type: ignore[assignment]
        self._setup = True

    def teardown(self) -> None:
        if not self._setup or self._original_show is None:
            return
        from PIL import Image

        Image.Image.show = self._original_show  # type: ignore[assignment]
        self._original_show = None
        self._setup = False

    def transform(self, obj: Any) -> Any:
        from PIL import Image

        if not isinstance(obj, Image.Image):
            return obj

        import ipywidgets as widgets

        # PNG preserves alpha and avoids Pillow's external temp-file viewer.
        image = obj
        if image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
            image = image.convert("RGBA")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return widgets.HTML(
            value=(
                '<img class="tkipw-raster" alt="Pillow image" '
                'style="display:block;width:100%;height:auto" '
                f'src="data:image/png;base64,{encoded}"/>'
            )
        )


def enable_pillow() -> None:
    """Enable Pillow image display and the ``Image.show()`` bridge."""
    from ..jupyter import register_extension

    register_extension(PillowExtension())
