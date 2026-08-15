"""Explicit registration of classic AMD / nbextension widget front ends.

Discovery (``jupyter_path`` / Lab federation) is out of scope. Call
:func:`register_widget_module` with a local JS file or directory. The
runtime serves that tree over loopback and loads it from ``loadClass``.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import quote

from .html_host import get_html_host

# Names already provided by the bundled ``runtime.js``. Overriding them would
# split ``@jupyter-widgets/base`` across two copies and break Comm.
_RESERVED_MODULE_NAMES = frozenset(
    {
        "@jupyter-widgets/base",
        "@jupyter-widgets/controls",
        "jupyter-js-widgets",
        "anywidget",
        "jupyter-leaflet",
        "ipycanvas",
        "bqplot",
        "bqscales",
        "jupyter-matplotlib",
    }
)

_registry: OrderedDict[str, dict[str, str]] = OrderedDict()
_listeners: list[Callable[[Mapping[str, Mapping[str, str]]], None]] = []


def register_widget_module(
    name: str,
    path: str | Path,
    *,
    style: str | Path | None = None,
) -> None:
    """Load a classic Jupyter widget JS module from a local path.

    *path* is a ``.js`` file or a directory containing ``index.js`` /
    ``extension.js`` / ``{name}.js``. Sibling assets (CSS, images, wasm) are
    served from the same directory. This does **not** fetch from a CDN.

    Example::

        from pathlib import Path
        import ipydatagrid
        from tkipw import register_widget_module

        register_widget_module(
            "ipydatagrid",
            Path(ipydatagrid.__file__).parent / "nbextension",
        )
    """
    key = _normalize_name(name)
    if key in _RESERVED_MODULE_NAMES:
        raise ValueError(f"{key!r} is bundled in tkipw; do not re-register it")
    entry = _resolve_entry(key, Path(path))
    style_path = _resolve_style(entry, style)
    host = get_html_host()
    public_path = host.mount_directory(entry.parent)
    spec = {
        "url": f"{public_path}{quote(entry.name)}",
        "publicPath": public_path,
    }
    if style_path is not None:
        spec["style"] = f"{public_path}{quote(style_path.name)}"
    previous = _registry.get(key)
    _registry[key] = spec
    if previous is not None:
        host.unmount_directory(previous["publicPath"])
    _emit()


def unregister_widget_module(name: str) -> None:
    """Drop a module registered by :func:`register_widget_module`."""
    key = _normalize_name(name)
    spec = _registry.pop(key, None)
    if spec is None:
        return
    get_html_host().unmount_directory(spec["publicPath"])
    _emit()


def registered_widget_modules() -> dict[str, dict[str, str]]:
    """Return a copy of the registered module map (name → urls)."""
    return {name: dict(spec) for name, spec in _registry.items()}


def widget_modules_js() -> str:
    """JSON object literal safe to embed in a ``<script>`` tag."""
    payload = json.dumps(
        registered_widget_modules(),
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return payload.replace("<", "\\u003c")


def watch_widget_modules(
    callback: Callable[[Mapping[str, Mapping[str, str]]], None],
) -> Callable[[], None]:
    """Call *callback* whenever the registry changes. Returns an unwatch fn."""
    _listeners.append(callback)

    def unwatch() -> None:
        try:
            _listeners.remove(callback)
        except ValueError:
            pass

    return unwatch


def _emit() -> None:
    snapshot = registered_widget_modules()
    for callback in list(_listeners):
        try:
            callback(snapshot)
        except Exception:
            pass


def _normalize_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("module name must be a non-empty string")
    return name.strip()


def _resolve_entry(name: str, path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.is_file():
        return resolved
    if resolved.is_dir():
        for candidate in (
            resolved / "index.js",
            resolved / "extension.js",
            resolved / f"{name}.js",
        ):
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(f"no index.js / extension.js / {name}.js in {resolved}")
    raise FileNotFoundError(f"widget module path not found: {resolved}")


def _resolve_style(entry: Path, style: str | Path | None) -> Path | None:
    if style is not None:
        resolved = Path(style).expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"widget module style not found: {resolved}")
        if resolved.parent != entry.parent:
            raise ValueError("style file must live next to the widget JS entry")
        return resolved
    sibling = entry.with_suffix(".css")
    return sibling if sibling.is_file() else None
