"""Environment diagnostics for ``python -m tkipw doctor``.

Does not create a Tk window or a native WebView. Classic AMD widgets are
loaded from ``register_widget_module`` or Jupyter ``nbextensions`` discovery
(Lab Module Federation is out of scope).
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_HTML_DIR = Path(__file__).resolve().parent / "html"

_REQUIRED_PACKAGES = (
    "tkipw",
    "tkwry",
    "tkface",
    "ipywidgets",
    "comm",
    "traitlets",
    "markdown",
)
_OPTIONAL_PACKAGES = (
    "anywidget",
    "ipyleaflet",
    "ipycanvas",
    "bqplot",
    "ipympl",
)
_CORE_WIDGET_MODULES = (
    "@jupyter-widgets/base",
    "@jupyter-widgets/controls",
    "anywidget",
)
_WIDGET_PACK_ASSETS = (
    "pack-leaflet.js",
    "pack-ipycanvas.js",
    "pack-bqplot.js",
    "pack-ipympl.js",
)
_PACK_WIDGET_MODULES = (
    ("jupyter-leaflet", "pack-leaflet.js"),
    ("ipycanvas", "pack-ipycanvas.js"),
    ("bqplot", "pack-bqplot.js"),
    ("bqscales", "pack-bqplot.js"),
    ("jupyter-matplotlib", "pack-ipympl.js"),
)


@dataclass(frozen=True)
class DoctorLine:
    """One row in the doctor report."""

    name: str
    detail: str
    ok: bool
    required: bool = True


@dataclass
class DoctorReport:
    packages: list[DoctorLine]
    webview: DoctorLine
    shell: list[DoctorLine]
    widgets: list[DoctorLine]
    extras: list[DoctorLine]
    nbextensions: list[DoctorLine]

    @property
    def ok(self) -> bool:
        required: Iterable[DoctorLine] = (
            *self.packages,
            self.webview,
            *self.shell,
            *self.widgets,
        )
        return all(line.ok for line in required if line.required)

    def format(self) -> str:
        blocks = [
            _section("Packages", self.packages),
            _section("WebView", [self.webview]),
            _section("Shell", self.shell),
            _section("Widget runtime", self.widgets),
            _section("Python extras (optional)", self.extras),
        ]
        if self.nbextensions:
            blocks.append(_section("Classic nbextensions", self.nbextensions))
        return "\n".join(blocks) + "\n"


def collect_report(*, html_dir: Path | None = None) -> DoctorReport:
    """Gather diagnostics without creating a WebView."""
    root = html_dir if html_dir is not None else _HTML_DIR
    js_ok, js_detail = _asset_status(root / "runtime.js", min_bytes=50_000)
    css_ok, css_detail = _asset_status(root / "runtime.css", min_bytes=100)
    shell = [
        DoctorLine("runtime.js", js_detail, js_ok),
        DoctorLine("runtime.css", css_detail, css_ok),
    ]
    for name in _WIDGET_PACK_ASSETS:
        ok, detail = _asset_status(root / name, min_bytes=1_000)
        shell.append(DoctorLine(name, detail, ok))
    widgets = [
        DoctorLine(name, "core" if js_ok else "runtime.js missing", js_ok)
        for name in _CORE_WIDGET_MODULES
    ]
    for name, pack_file in _PACK_WIDGET_MODULES:
        ok, detail = _asset_status(root / pack_file, min_bytes=1_000)
        widgets.append(DoctorLine(name, "lazy pack" if ok else detail, ok))
    return DoctorReport(
        packages=[_package_line(name, required=True) for name in _REQUIRED_PACKAGES],
        webview=_webview_line(),
        shell=shell,
        widgets=widgets,
        extras=[_package_line(name, required=False) for name in _OPTIONAL_PACKAGES],
        nbextensions=_nbextension_lines(),
    )


def run_doctor(*, file: object | None = None) -> int:
    """Print a report. Return 0 when required checks pass, else 1."""
    report = collect_report()
    print(report.format(), end="", file=file)
    return 0 if report.ok else 1


def _nbextension_lines() -> list[DoctorLine]:
    from .widget_modules import iter_nbextension_modules

    try:
        found = iter_nbextension_modules()
    except Exception:
        return []
    return [
        DoctorLine(name, "nbextension", True, required=False) for name, _path in found
    ]


def _package_line(name: str, *, required: bool) -> DoctorLine:
    ver = _package_version(name)
    if ver is None:
        return DoctorLine(name, "missing", False, required=required)
    return DoctorLine(name, ver, True, required=required)


def _package_version(name: str) -> str | None:
    if name == "tkipw":
        from tkipw import __version__

        return str(__version__)
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _asset_status(path: Path, *, min_bytes: int) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    size = path.stat().st_size
    if size < min_bytes:
        return False, f"{_fmt_size(size)} (too small)"
    return True, _fmt_size(size)


def _fmt_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / 1024:.0f} KB"


def _tkwry_importable() -> bool:
    try:
        import tkwry  # noqa: F401
    except Exception:
        return False
    return True


def _webview_line() -> DoctorLine:
    plat = sys.platform
    if plat == "darwin":
        ok = _tkwry_importable()
        return DoctorLine("macOS", "WKWebView", ok)
    if plat == "win32":
        try:
            from tkwry._win32 import is_webview2_runtime_available

            ok = bool(is_webview2_runtime_available())
        except Exception:
            ok = False
        return DoctorLine("Windows", "WebView2", ok)
    if plat.startswith("linux"):
        ok = _tkwry_importable()
        return DoctorLine("Linux", "WebKitGTK", ok)
    return DoctorLine(plat, "unknown engine", False)


def _section(title: str, lines: list[DoctorLine]) -> str:
    rows = "\n".join(_format_line(line) for line in lines)
    return f"{title}\n{rows}"


def _format_line(line: DoctorLine) -> str:
    status = "OK" if line.ok else "missing"
    return f"  {line.name:<28} {line.detail:<18} {status}"
