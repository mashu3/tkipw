"""Classic AMD / nbextension widget front ends.

:func:`register_widget_module` takes an explicit local path.
:func:`discover_widget_modules` scans Jupyter ``nbextensions`` directories
(``jupyter_path`` when available). Lab Module Federation is out of scope.
"""

from __future__ import annotations

import json
import os
import sys
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
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

    Prefer :func:`discover_widget_modules` (or just creating an ``App``) when
    the package already installed an nbextension. Use this for an explicit path.
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


def nbextension_dirs() -> list[Path]:
    """Directories Jupyter searches for classic nbextensions (first wins)."""
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Jupyter is migrating its paths",
                category=DeprecationWarning,
            )
            from jupyter_core.paths import jupyter_path

            return [Path(p) for p in jupyter_path("nbextensions")]
    except ImportError:
        return _fallback_nbextension_dirs()


def iter_nbextension_modules(
    paths: Iterable[str | Path] | None = None,
) -> list[tuple[str, Path]]:
    """Return ``(module_name, directory)`` pairs that look like widget AMD.

    Only directories that contain ``index.js`` are included. Bundled runtime
    names are skipped. Earlier paths win when the same name appears twice.
    """
    roots = [Path(p) for p in paths] if paths is not None else nbextension_dirs()
    found: OrderedDict[str, Path] = OrderedDict()
    for root in roots:
        try:
            if not root.is_dir():
                continue
            children = list(root.iterdir())
        except OSError:
            continue
        for child in sorted(children, key=lambda p: p.name):
            if not child.is_dir() or child.name.startswith("."):
                continue
            name = child.name
            if name in _RESERVED_MODULE_NAMES:
                continue
            if not (child / "index.js").is_file():
                continue
            found.setdefault(name, child)
    return list(found.items())


def discover_widget_modules(
    *,
    paths: Iterable[str | Path] | None = None,
) -> list[str]:
    """Register classic AMD modules found under Jupyter nbextension dirs.

    Names already passed to :func:`register_widget_module` are left unchanged.
    Returns the module names newly registered. Does not fetch from a CDN.
    """
    added: list[str] = []
    for name, directory in iter_nbextension_modules(paths):
        if name in _registry:
            continue
        try:
            register_widget_module(name, directory)
        except (ValueError, OSError):
            continue
        added.append(name)
    return added


def _fallback_nbextension_dirs() -> list[Path]:
    dirs: list[Path] = []
    extra = os.environ.get("JUPYTER_PATH")
    if extra:
        for raw in extra.split(os.pathsep):
            text = raw.strip()
            if text:
                dirs.append(Path(text) / "nbextensions")
    dirs.append(_user_jupyter_dir() / "nbextensions")
    dirs.append(Path(sys.prefix) / "share" / "jupyter" / "nbextensions")
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in dirs:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _user_jupyter_dir() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "jupyter"
        return Path.home() / "AppData" / "Roaming" / "jupyter"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Jupyter"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "jupyter"
    return Path.home() / ".local" / "share" / "jupyter"


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
