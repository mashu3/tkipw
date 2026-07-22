"""Desktop App: Tk + tkwry WebView hosting the Jupyter widgets runtime."""

from __future__ import annotations

import base64
import json
import tkinter as tk
from collections.abc import Callable, Mapping
from pathlib import Path
from tkinter import filedialog
from typing import Any

from tkwry import PageLoadEvent, WebView

from .comm_backend import (
    get_comm,
    install_comm_backend,
    pop_bridge,
    push_bridge,
    reset_comms,
    unregister_comm,
)
from .manager import prepare_widgets

_HTML_DIR = Path(__file__).resolve().parent / "html"

# Live App instances, so process-wide monkey-patches (comm backend, IPython
# display bridge, logging, excepthook) are torn down when the last one closes.
_active_apps: list[App] = []

# Optional ``colors`` keys for ``App.set_theme`` → CSS custom properties.
_THEME_COLOR_VARS: dict[str, str] = {
    "bg": "--tkipw-bg",
    "fg": "--tkipw-fg",
    "muted": "--tkipw-muted",
    "border": "--tkipw-border",
    "panel": "--tkipw-panel",
    "hosted_bg": "--tkipw-hosted-bg",
    "widget_label": "--tkipw-widget-label",
    "link": "--tkipw-link",
    "table_stripe": "--tkipw-table-stripe",
}


def _hex_to_rgba(color: str) -> tuple[int, int, int, int]:
    """Parse ``#rgb`` / ``#rrggbb`` into an opaque RGBA tuple."""
    h = color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"expected #rrggbb, got {color!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255

_SHELL = """\
<!DOCTYPE html>
<html lang="en" data-theme="__THEME__">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>tkipw</title>
  <link rel="stylesheet" href="__RUNTIME_CSS_URL__" />
  <style>__CSS__</style>
</head>
<body>
  <div id="tkipw-root">
    <div id="tkipw-status">Starting widget runtime…</div>
  </div>
  <script src="__RUNTIME_JS_URL__"></script>
</body>
</html>
"""

# App chrome CSS (theme + layout). Widget-manager CSS ships as runtime.css.
_SHELL_CSS = """

html, body {
  margin: 0; padding: 0;
  width: 100%; height: 100%;
  overflow: auto;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial,
    sans-serif;
  background: var(--tkipw-bg);
  color: var(--tkipw-fg);
}
:root, html[data-theme="light"] {
  --tkipw-bg: #ffffff;
  --tkipw-fg: #111111;
  --tkipw-muted: #666666;
  --tkipw-border: #e5e7eb;
  --tkipw-panel: #f9fafb;
  --tkipw-error-fg: #b91c1c;
  --tkipw-error-bg: #fef2f2;
  --tkipw-stderr-fg: #9a3412;
  --tkipw-stderr-bg: #fff7ed;
  --tkipw-hosted-bg: #ffffff;
  --tkipw-widget-label: #333333;
  --tkipw-link: #0969da;
  --tkipw-table-stripe: #f5f5f5;
  --tkipw-table-hover: rgba(66, 165, 245, 0.2);
}
html[data-theme="dark"] {
  --tkipw-bg: #1e1e1e;
  --tkipw-fg: #d4d4d4;
  --tkipw-muted: #9ca3af;
  --tkipw-border: #3c3c3c;
  --tkipw-panel: #252526;
  --tkipw-error-fg: #fca5a5;
  --tkipw-error-bg: #3f1d1d;
  --tkipw-stderr-fg: #fdba74;
  --tkipw-stderr-bg: #3b2a14;
  --tkipw-hosted-bg: #1e1e1e;
  --tkipw-widget-label: #cccccc;
  --tkipw-link: #58a6ff;
  --tkipw-table-stripe: #2a2a2a;
  --tkipw-table-hover: rgba(66, 165, 245, 0.18);
}
#tkipw-root {
  box-sizing: border-box;
  width: 100%;
  min-height: 100%;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: auto;
}
#tkipw-status { font-size: 12px; color: var(--tkipw-muted); flex: 0 0 auto; }
#tkipw-widgets {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  max-width: 100%;
  flex: 1 1 auto;
  overflow: auto;
  color: var(--tkipw-fg);
}
/* Rich output fills the available pane width.
   Exclude ``.jupyter-button`` — bqplot's hover toolbar reuses that class and
   must stay compact (not stretched to 100% width).
   Exclude ipympl canvas nodes — they carry inline pixel sizes; ``width:100%``
   against a ``fit-content`` figure collapses the plot to a thin strip. */
#tkipw-widgets .jupyter-widgets:not(.jupyter-button):not(.jupyter-matplotlib):not(
  .jupyter-matplotlib-canvas-div
):not(.jupyter-matplotlib-canvas-container):not(.jupyter-matplotlib-toolbar),
#tkipw-widgets .widget-box:not(.jupyter-matplotlib):not(
  .jupyter-matplotlib-figure
):not(.jupyter-matplotlib-canvas-container):not(
  .jupyter-matplotlib-canvas-div
):not(.jupyter-matplotlib-toolbar),
#tkipw-widgets .widget-vbox:not(.jupyter-matplotlib):not(.jupyter-matplotlib-toolbar),
#tkipw-widgets .widget-html,
#tkipw-widgets .widget-html > div {
  width: 100% !important;
  max-width: 100%;
  box-sizing: border-box;
}
/* bqplot integrated toolbar (Font Awesome glyphs are omitted from the bundle). */
#tkipw-widgets .bqplot .toolbar_div {
  z-index: 10;
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 4px;
  padding: 4px;
  background: color-mix(in srgb, var(--tkipw-bg) 92%, transparent);
  border: 1px solid var(--tkipw-border);
  border-radius: 6px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
}
#tkipw-widgets .bqplot .toolbar_div .jupyter-button {
  flex: 0 0 auto;
  width: 32px !important;
  min-width: 32px;
  max-width: 32px;
  height: 28px;
  padding: 0;
  margin: 0;
  line-height: 28px;
  text-align: center;
  color: var(--tkipw-fg);
  background: var(--tkipw-panel);
  border: 1px solid var(--tkipw-border);
  border-radius: 4px;
  cursor: pointer;
}
#tkipw-widgets .bqplot .toolbar_div .fa {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif !important;
  font-style: normal;
  font-weight: 700;
  font-size: 14px;
  line-height: 1;
  color: var(--tkipw-fg);
}
#tkipw-widgets .bqplot .toolbar_div .fa:before {
  font-family: inherit !important;
}
#tkipw-widgets .bqplot .toolbar_div .fa-arrows:before {
  content: "↔";
}
#tkipw-widgets .bqplot .toolbar_div .fa-refresh:before {
  content: "↻";
}
#tkipw-widgets .bqplot .toolbar_div .fa-save:before {
  content: "⇩";
}
/* ipympl toolbar (Font Awesome glyphs omitted from the bundle). */
#tkipw-widgets .jupyter-matplotlib-button .fa {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif !important;
  font-style: normal;
  font-weight: 700;
  font-size: 13px;
  line-height: 1;
  color: var(--tkipw-fg);
}
#tkipw-widgets .jupyter-matplotlib-button .fa:before {
  font-family: inherit !important;
}
#tkipw-widgets .jupyter-matplotlib-button .fa-home:before {
  content: "⌂";
}
#tkipw-widgets .jupyter-matplotlib-button .fa-arrow-left:before {
  content: "←";
}
#tkipw-widgets .jupyter-matplotlib-button .fa-arrow-right:before {
  content: "→";
}
#tkipw-widgets .jupyter-matplotlib-button .fa-square-o:before {
  content: "▢";
}
#tkipw-widgets .jupyter-matplotlib-button .fa-arrows:before {
  content: "↔";
}
#tkipw-widgets .jupyter-matplotlib-button .fa-floppy-o:before {
  content: "⇩";
}
#tkipw-widgets .jupyter-matplotlib-button .fa-file-picture-o:before {
  content: "🖼";
}
/* ipympl: leave ``.jupyter-matplotlib-canvas-div`` alone — it sets inline
   ``width``/``height`` in px. Any ``width: … !important`` here overrides that
   and the absolutely-positioned canvas no longer expands its parent.
   ``align-self:flex-start`` stops the flex Output VBox from stretching the
   shell to the pane width while the canvas stays at figure pixels (looks
   like a clipped / padded strip). ``max-width:100%`` on the figure would
   shrink the box below the canvas and clip via overflow:hidden. */
#tkipw-widgets .jupyter-matplotlib {
  width: fit-content !important;
  max-width: none !important;
  flex: 0 0 auto !important;
  align-self: flex-start !important;
}
#tkipw-widgets .jupyter-matplotlib-figure {
  width: fit-content !important;
  max-width: none !important;
  overflow: hidden;
}
#tkipw-widgets .widget-box:has(.jupyter-matplotlib),
#tkipw-widgets .widget-vbox:has(.jupyter-matplotlib),
#tkipw-widgets .lm-Panel:has(.jupyter-matplotlib) {
  overflow: visible !important;
  align-items: flex-start !important;
}
#tkipw-widgets .jupyter-matplotlib-toolbar {
  width: auto !important;
  max-width: none !important;
}
#tkipw-widgets .jupyter-matplotlib-button {
  width: calc(var(--jp-widgets-inline-width-tiny, 64px) / 2 - 2px) !important;
}
/* Drop ipympl notebook chrome (Figure N / status). Playground already labels
   sections; pop-up geometry is figure pixels without these bands. */
#tkipw-widgets .jupyter-matplotlib-header,
#tkipw-widgets .jupyter-matplotlib-footer {
  display: none !important;
  min-height: 0 !important;
  height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
}
/* ipympl defaults to margin:2px on canvas-div / labels — that inflates the
   shell past figure pixels and clips inside overflow:hidden sections. */
#tkipw-widgets .jupyter-matplotlib-canvas-div,
#tkipw-widgets .jupyter-matplotlib-canvas-container {
  margin: 0 !important;
  /* Upstream uses flex:1 1 auto — the div then shrinks below its inline
     pixel width while the absolutely-positioned canvas stays at figsize,
     so overflow:hidden on the figure clips the plot. */
  flex: 0 0 auto !important;
}
/* Keep stacked sections from being covered by overflowing embeds. */
#tkipw-widgets .widget-vbox {
  flex: 0 0 auto;
  min-height: 0;
  overflow: hidden;
}
#tkipw-widgets .widget-html {
  position: relative;
  overflow: hidden;
  flex: 0 0 auto;
}
/* Keep image output inside the viewport.
   Never target bare ``img`` — ipyleaflet tiles/markers set pixel sizes via
   inline style, and ``height: auto !important`` / ``max-width: 100%``
   collapses them to 0×0 inside Leaflet's transform panes. */
#tkipw-widgets .widget-html img,
#tkipw-widgets .tkipw-markdown img,
.jupyter-widgets.widget-image img,
.widget-image img {
  max-width: 100% !important;
  height: auto !important;
  object-fit: contain;
}
#tkipw-widgets .leaflet-container img {
  max-width: none !important;
  height: unset !important;
  object-fit: fill;
}
/* Embedded rich HTML needs an explicit viewport.
   Folium uses position:absolute inside a padding-bottom box — do not
   force min-height there or the iframe overflows and covers siblings
   after Leaflet resizes on interaction. */
#tkipw-widgets .widget-html iframe {
  display: block;
  max-width: 100%;
  border: 0;
  background: transparent;
}
#tkipw-widgets .widget-html iframe.tkipw-hosted-html {
  /* Inline pane: fill column width; height comes from the element style
     (fixed px, or aspect-ratio + height:auto). Compact shells override both. */
  width: 100% !important;
  max-width: 100%;
  background: var(--tkipw-hosted-bg);
}
#tkipw-widgets .widget-html iframe[style*="absolute"] {
  min-height: 0 !important;
}
#tkipw-widgets .widget-html iframe:not([style*="absolute"]):not(.tkipw-hosted-html) {
  width: 100% !important;
  min-height: 480px;
  background: #111;
}
.jupyter-widgets.widget-hbox,
.jupyter-widgets.widget-box {
  max-width: 100%;
  flex-wrap: wrap;
}
/* Plotly defaults to ~700px; keep charts inside the host pane. */
#tkipw-widgets .js-plotly-plot,
#tkipw-widgets .plot-container,
#tkipw-widgets .svg-container {
  max-width: 100% !important;
  width: 100% !important;
  box-sizing: border-box;
}
#tkipw-widgets .js-plotly-plot {
  overflow: hidden;
}
/* Stream / error blocks — theme via CSS variables. */
#tkipw-widgets .tkipw-stream {
  margin: 0;
  padding: 8px 10px;
  border-radius: 4px;
  overflow: auto;
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.45;
}
#tkipw-widgets .tkipw-stdout {
  color: var(--tkipw-fg);
  background: transparent;
}
#tkipw-widgets .tkipw-error {
  color: var(--tkipw-error-fg);
  background: var(--tkipw-error-bg);
}
#tkipw-widgets .tkipw-stderr {
  color: var(--tkipw-stderr-fg);
  background: var(--tkipw-stderr-bg);
}
/* Markdown rendered from IPython.display.Markdown / text/markdown. */
#tkipw-widgets .tkipw-markdown {
  color: var(--tkipw-fg);
  line-height: 1.6;
  overflow-wrap: anywhere;
}
#tkipw-widgets .tkipw-markdown > :first-child {
  margin-top: 0;
}
#tkipw-widgets .tkipw-markdown > :last-child {
  margin-bottom: 0;
}
#tkipw-widgets .tkipw-markdown pre,
#tkipw-widgets .tkipw-markdown code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: var(--tkipw-panel);
  border-radius: 4px;
}
#tkipw-widgets .tkipw-markdown code {
  padding: 0.12em 0.3em;
}
#tkipw-widgets .tkipw-markdown pre {
  padding: 10px 12px;
  overflow: auto;
}
#tkipw-widgets .tkipw-markdown pre code {
  padding: 0;
  background: transparent;
}
#tkipw-widgets .tkipw-markdown blockquote {
  margin-left: 0;
  padding-left: 12px;
  color: var(--tkipw-muted);
  border-left: 3px solid var(--tkipw-border);
}
#tkipw-widgets .tkipw-markdown table {
  border-collapse: collapse;
}
#tkipw-widgets .tkipw-markdown th,
#tkipw-widgets .tkipw-markdown td {
  padding: 5px 9px;
  border: 1px solid var(--tkipw-border);
}
/* Pandas / Styler HTML mirrors Jupyter notebook ``.rendered_html table``.
   Override the legacy ``border="1"`` look from ``DataFrame._repr_html_``. */
#tkipw-widgets table.dataframe {
  margin: 0;
  border: none !important;
  border-collapse: collapse;
  border-spacing: 0;
  color: var(--tkipw-fg);
  font-size: 12px;
  line-height: normal;
  background: transparent;
}
#tkipw-widgets table.dataframe thead {
  border-bottom: 1px solid var(--tkipw-border);
  vertical-align: bottom;
}
#tkipw-widgets table.dataframe th,
#tkipw-widgets table.dataframe td {
  text-align: right;
  vertical-align: middle;
  padding: 0.5em;
  line-height: normal;
  white-space: normal;
  max-width: none;
  border: none !important;
  color: inherit;
  background: transparent;
}
#tkipw-widgets table.dataframe th {
  font-weight: bold;
}
#tkipw-widgets table.dataframe tbody tr:nth-child(odd) {
  background: var(--tkipw-table-stripe);
}
#tkipw-widgets table.dataframe tbody tr:hover {
  background: var(--tkipw-table-hover);
}
#tkipw-widgets .tkipw-markdown a {
  color: var(--tkipw-link);
}
/* Playground / stacked notebook sections. */
#tkipw-widgets .tkipw-section {
  border: 1px solid var(--tkipw-border) !important;
  background: var(--tkipw-bg);
}
#tkipw-widgets .tkipw-section-header {
  padding: 6px 10px;
  color: var(--tkipw-muted);
  background: var(--tkipw-panel);
  border-bottom: 1px solid var(--tkipw-border);
  font: 12px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
/* ipywidgets chrome: labels and plain text follow the shell theme. */
#tkipw-widgets .widget-label,
#tkipw-widgets .widget-label-basic,
#tkipw-widgets .widget-readout,
#tkipw-widgets .widget-html-content,
#tkipw-widgets .jupyter-widgets {
  color: var(--tkipw-widget-label);
}
#tkipw-widgets .widget-html-content pre,
#tkipw-widgets pre {
  color: inherit;
}

body.tkipw-compact {
  overflow: hidden;
}
body.tkipw-compact #tkipw-root {
  padding: 0;
  gap: 0;
  height: 100%;
  min-height: 100%;
  overflow: hidden;
}
body.tkipw-compact #tkipw-widgets {
  position: relative;
  gap: 0;
  height: 100%;
  overflow: auto;
  padding: 12px;
  box-sizing: border-box;
}
body.tkipw-compact .jupyter-widgets,
body.tkipw-compact .p-Widget,
body.tkipw-compact .lm-Widget {
  margin: 0 !important;
  border: 0 !important;
}
body.tkipw-compact #tkipw-widgets .widget-html,
body.tkipw-compact #tkipw-widgets .widget-html > div,
body.tkipw-compact #tkipw-widgets .widget-html-content {
  max-width: 100%;
  line-height: 1.45 !important;
  white-space: normal;
  overflow: visible;
}
body.tkipw-compact #tkipw-widgets .widget-html pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.45;
}

/* Maps / charts / images / tables: edge-to-edge, no text chrome.
   Do not match bare ``img`` — ipyleaflet tiles/markers are also ``img`` and
   must keep Leaflet's pixel sizes (``width/height: 100%`` collapses them).
   Pillow uses ``img.tkipw-raster`` instead.
   ``canvas`` alone is ipycanvas; ipympl also has ``canvas`` but must not share
   that path (its figure is pixel-sized, not a full-bleed fill).
   ``.bqplot`` / ``table.dataframe`` only clear padding
   (pixel- or content-sized); do not stretch them to 100% like maps. */
body.tkipw-compact #tkipw-widgets:has(iframe),
body.tkipw-compact #tkipw-widgets:has(.widget-image),
body.tkipw-compact #tkipw-widgets:has(.leaflet-container),
body.tkipw-compact #tkipw-widgets:has(img.tkipw-raster),
body.tkipw-compact #tkipw-widgets:has(canvas):not(:has(.jupyter-matplotlib)),
body.tkipw-compact #tkipw-widgets:has(.bqplot),
body.tkipw-compact #tkipw-widgets:has(table.dataframe),
body.tkipw-compact #tkipw-widgets:has(.jupyter-matplotlib) {
  padding: 0;
  overflow: hidden;
}
body.tkipw-compact #tkipw-widgets:has(iframe) .jupyter-widgets,
body.tkipw-compact #tkipw-widgets:has(iframe) .widget-html,
body.tkipw-compact #tkipw-widgets:has(iframe) .widget-html > div,
body.tkipw-compact #tkipw-widgets:has(iframe) .widget-html-content,
body.tkipw-compact #tkipw-widgets:has(.widget-image) .jupyter-widgets,
body.tkipw-compact #tkipw-widgets:has(.widget-image) .widget-html,
body.tkipw-compact #tkipw-widgets:has(.widget-image) .widget-html > div,
body.tkipw-compact #tkipw-widgets:has(.widget-image) .widget-html-content,
body.tkipw-compact #tkipw-widgets:has(img.tkipw-raster) .jupyter-widgets,
body.tkipw-compact #tkipw-widgets:has(img.tkipw-raster) .widget-html,
body.tkipw-compact #tkipw-widgets:has(img.tkipw-raster) .widget-html > div,
body.tkipw-compact #tkipw-widgets:has(img.tkipw-raster) .widget-html-content,
body.tkipw-compact #tkipw-widgets:has(.leaflet-container) .leaflet-widgets {
  position: absolute !important;
  inset: 0 !important;
  width: 100% !important;
  height: 100% !important;
  max-width: none !important;
  margin: 0 !important;
  padding: 0 !important;
  line-height: 0 !important;
  overflow: hidden !important;
  box-sizing: border-box !important;
}
body.tkipw-compact #tkipw-widgets .widget-html iframe,
body.tkipw-compact #tkipw-widgets .widget-html iframe.tkipw-hosted-html {
  position: absolute !important;
  inset: 0 !important;
  width: 100% !important;
  height: 100% !important;
  max-width: none !important;
  min-height: 0 !important;
  margin: 0 !important;
  border: 0 !important;
  display: block !important;
  background: transparent !important;
}
body.tkipw-compact #tkipw-widgets:has(.leaflet-container) .leaflet-container {
  width: 100% !important;
  height: 100% !important;
}
body.tkipw-compact .jupyter-widgets.widget-image img,
body.tkipw-compact .widget-image img,
body.tkipw-compact img.tkipw-raster {
  max-width: none !important;
  width: 100% !important;
  height: 100% !important;
  object-fit: fill;
  display: block !important;
}

"""


def _load_shell_html(
    *,
    compact: bool = False,
    theme: str = "light",
    runtime_js_url: str = "",
    runtime_css_url: str = "",
) -> str:
    """Build the widget shell HTML.

    ``runtime_js_url`` / ``runtime_css_url`` point at loopback-hosted assets so
    the document stays small (WebViews struggle with multi-MB inline scripts).
    """
    runtime = _HTML_DIR / "runtime.js"
    if not runtime.exists():
        raise FileNotFoundError(
            f"Missing {runtime}. Run: cd js && npm install && npm run build"
        )
    body = '<body class="tkipw-compact">' if compact else "<body>"
    if theme not in ("light", "dark"):
        theme = "light"
    return (
        _SHELL.replace("__THEME__", theme)
        .replace("__CSS__", _SHELL_CSS)
        .replace("__RUNTIME_JS_URL__", runtime_js_url)
        .replace("__RUNTIME_CSS_URL__", runtime_css_url)
        .replace("<body>", body, 1)
    )


def _shell_document_url(*, compact: bool = False, theme: str = "light") -> str:
    """Serve the widget shell over loopback and return its URL.

    WebView2's ``NavigateToString`` rejects payloads larger than ~2 MB. Even
    over ``url=``, inlining the full runtime as a ``<script>`` body can fail to
    evaluate once the bundle grows (bqplot / leaflet / …). Host ``runtime.js``
    / ``runtime.css`` as separate loopback assets and keep the HTML small.
    """
    from .html_host import get_html_host

    host = get_html_host()
    runtime_js = (_HTML_DIR / "runtime.js").read_bytes()
    css_path = _HTML_DIR / "runtime.css"
    runtime_css = css_path.read_bytes() if css_path.exists() else b"/* empty */\n"
    js_url = host.mount_bytes(
        runtime_js,
        content_type="application/javascript; charset=utf-8",
        suffix=".js",
    )
    css_url = host.mount_bytes(
        runtime_css,
        content_type="text/css; charset=utf-8",
        suffix=".css",
    )
    return host.mount(
        _load_shell_html(
            compact=compact,
            theme=theme,
            runtime_js_url=js_url,
            runtime_css_url=css_url,
        )
    )


class App:
    """Host ipywidgets / anywidget UIs inside a tkwry WebView.

    ``display_mode="inline"`` sends ``display()`` / library ``show()`` output
    into this App. ``display_mode="window"`` opens a new Tk pop-up for each
    output (Matplotlib uses native TkAgg windows).
    """

    def __init__(
        self,
        *,
        title: str = "tkipw",
        width: int = 900,
        height: int = 700,
        root: tk.Misc | None = None,
        parent: tk.Misc | None = None,
        devtools: bool = False,
        display_mode: str = "inline",
        compact: bool = False,
        theme: str = "light",
        colors: Mapping[str, str] | None = None,
    ) -> None:
        install_comm_backend()

        from .display_mode import validate_display_mode

        self.display_mode = validate_display_mode(display_mode)
        self.compact = compact
        self.title = title
        if theme not in ("light", "dark"):
            raise ValueError(f"theme must be 'light' or 'dark', got {theme!r}")
        self.theme = theme
        self._theme_colors: dict[str, str] | None = (
            {str(k): str(v) for k, v in colors.items()} if colors else None
        )
        self._ready = False
        self._ready_callbacks: list[Callable[[], None]] = []
        self._destroyed = False
        self._outbound: list[dict[str, Any]] = []
        self._known_model_ids: set[str] = set()
        self._flush_scheduled = False
        self._flush_after_id: str | None = None
        self._cell_output: Any = None
        self._cell_output_mounted = False
        push_bridge(self)
        _active_apps.append(self)

        # ``parent`` = embed in an existing Frame (e.g. PanedWindow pane).
        # ``root`` kept for backwards compatibility (Tk or container).
        container = parent if parent is not None else root
        self._owns_root = container is None
        if container is None:
            import tkface

            # Embed-safe DPI: awareness only — do not call tkface.win.dpi(root).
            tkface.win.enable_dpi_awareness()
            self.root = tk.Tk()
            self._container: tk.Misc = self.root
            self.root.title(title)
            self.root.geometry(
                f"{tkface.win.design_to_physical(width)}x"
                f"{tkface.win.design_to_physical(height)}"
            )
            # Withdraw before packing the WebView so Windows does not flash an
            # empty host window (content lives in Toplevel pop-ups).
            if self.display_mode == "window":
                self.root.withdraw()
        else:
            self._container = container
            self.root = container.winfo_toplevel()

        self._frame = tk.Frame(self._container)
        self._frame.pack(fill="both", expand=True)
        shell_bg = self._shell_bg_hex()
        try:
            self._frame.configure(bg=shell_bg, highlightthickness=0, bd=0)
        except tk.TclError:
            pass

        # Prefer url= over html=: see ``_shell_document_url``.
        # Bake theme into the shell so ready/flush does not need an early
        # eval_js just to flip data-theme (that raced widget delivery).
        # Native WebView bg matches the shell so a hidden→shown pane does not
        # flash system white (same idea as tklab explorer/editor WebViews).
        try:
            bg_rgba = _hex_to_rgba(shell_bg)
        except ValueError:
            if self.theme == "dark":
                bg_rgba = (30, 30, 30, 255)
            else:
                bg_rgba = (255, 255, 255, 255)
        self.webview = WebView(
            self._frame,
            url=_shell_document_url(compact=compact, theme=self.theme),
            ipc_handler=self._on_ipc,
            on_page_load=self._on_page_load,
            on_navigation=lambda _url: True,
            devtools=devtools,
            background_color=bg_rgba,
        )

        # IPython.display + built-in Jupyter adapters (matplotlib / pyvista / …).
        from .jupyter import install_jupyter_support

        install_jupyter_support()
        from .display_mode import sync_matplotlib

        sync_matplotlib(self.display_mode)

        # Notebook-like error / logging visibility in the output area
        from .output import install_display_logging, install_excepthook

        install_display_logging()
        install_excepthook()

        if self._owns_root:
            # Tear down native WebView before Tk walks the widget tree.
            self.root.protocol("WM_DELETE_WINDOW", self.destroy)

    def _on_page_load(self, event: PageLoadEvent, url: str | None) -> None:
        if event == PageLoadEvent.Finished and not self._ready:
            # Fallback if the runtime failed to post ready: probe and report
            self.webview.eval_js(
                "if(!window.__tkipwDeliver){"
                "window.ipc && window.ipc.postMessage(JSON.stringify({"
                "channel:'error',message:'runtime failed to boot'}));"
                "}"
            )

    # ------------------------------------------------------------------ IPC
    def send_to_js(self, msg: dict[str, Any]) -> None:
        """Queue a message; flush as one batch on the next Tk idle tick.

        Batching matters: creating a widget tree emits many ``comm_open``s plus
        a ``display``. One ``eval_js`` keeps ordering reliable in the WebView.
        """
        if msg.get("msg_type") == "comm_open":
            comm_id = msg.get("comm_id")
            if isinstance(comm_id, str):
                self._known_model_ids.add(comm_id)
        self._outbound.append(msg)
        if not self._ready:
            return
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        if self._flush_scheduled:
            return
        self._flush_scheduled = True
        try:
            self._flush_after_id = self.root.after_idle(self._flush_outbound)
        except Exception:
            self._flush_scheduled = False
            self._flush_after_id = None
            self._flush_outbound()

    def _flush_outbound(self) -> None:
        self._flush_scheduled = False
        self._flush_after_id = None
        if not self._outbound or not self._ready:
            return
        batch = self._outbound
        self._outbound = []
        self._eval_deliver_many(batch)

    def _eval_deliver(self, msg: dict[str, Any]) -> None:
        self._eval_deliver_many([msg])

    def _eval_deliver_many(self, messages: list[dict[str, Any]]) -> None:
        """Deliver one or more protocol messages in a single eval_js call."""
        js = (
            "(function(msgs){"
            "msgs.forEach(function(m){ window.__tkipwDeliver(m); });"
            "})(" + json.dumps(messages, ensure_ascii=False, default=str) + ");"
        )
        try:
            self.webview.eval_js(js)
        except Exception:
            self._outbound.extend(messages)
            self._schedule_flush()

    def _on_ipc(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        channel = msg.get("channel")
        if channel == "ready":
            self._ready = True
            # A synchronous eval_js before the first flush is required: on
            # WKWebView/WebView2 the initial queued display batch is otherwise
            # accepted by eval_js but never applied to the DOM.
            # Theme is already baked into the shell HTML; this is a no-op set.
            self._apply_theme()
            self._schedule_flush()
            self._fire_ready_callbacks()
            return
        if channel == "comm":
            self._handle_comm_from_js(msg)
            return
        if channel == "download":
            self._handle_download_from_js(msg)
            return
        if channel == "error":
            detail = msg.get("detail") or msg.get("message") or raw
            print(f"[tkipw] frontend error: {detail}")

    def _handle_download_from_js(self, msg: dict[str, Any]) -> None:
        """Persist a WebView ``<a download>`` payload via a native save dialog.

        Desktop WebViews do not implement browser downloads; bqplot's Save
        toolbar (and similar) create a data-URL anchor and click it. The JS
        bridge posts the bytes here instead.
        """
        filename = msg.get("filename") or "download"
        if not isinstance(filename, str):
            filename = "download"
        filename = Path(filename).name or "download"
        raw_b64 = msg.get("data_base64") or ""
        if not isinstance(raw_b64, str) or not raw_b64:
            return
        try:
            data = base64.b64decode(raw_b64, validate=False)
        except Exception:
            return
        if not data:
            return

        suffix = Path(filename).suffix
        filetypes: list[tuple[str, str]] = [("All files", "*.*")]
        if suffix:
            filetypes.insert(0, (f"{suffix.lstrip('.').upper()} files", f"*{suffix}"))

        def _save() -> None:
            if self._destroyed:
                return
            path = filedialog.asksaveasfilename(
                parent=self.root,
                title="Save",
                initialfile=filename,
                defaultextension=suffix or "",
                filetypes=filetypes,
            )
            if not path:
                return
            try:
                Path(path).write_bytes(data)
            except OSError as exc:
                print(f"[tkipw] failed to save download: {exc}")

        try:
            self.root.after(0, _save)
        except Exception:
            _save()

    def when_ready(self, callback: Callable[[], None]) -> None:
        """Run *callback* once the widget runtime has booted (and after flush)."""
        if self._destroyed:
            return
        if self._ready:
            self._schedule_ready_callback(callback)
            return
        self._ready_callbacks.append(callback)

    def _fire_ready_callbacks(self) -> None:
        callbacks = self._ready_callbacks
        self._ready_callbacks = []
        for callback in callbacks:
            self._schedule_ready_callback(callback)

    def _schedule_ready_callback(self, callback: Callable[[], None]) -> None:
        # ``_schedule_flush`` already queued an idle flush; a second idle runs
        # after it so pop-up reveal happens with widgets already delivered.
        try:
            self.root.after_idle(callback)
        except Exception:
            try:
                callback()
            except Exception:
                pass

    def _handle_comm_from_js(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("msg_type")
        comm_id = msg.get("comm_id")
        if not comm_id:
            return
        if msg_type == "comm_open":
            from .comm_backend import accept_comm_open_from_js

            accept_comm_open_from_js(msg)
            if isinstance(comm_id, str):
                self._known_model_ids.add(comm_id)
            return
        c = get_comm(comm_id)
        if msg_type == "comm_msg":
            if c is None:
                return
            c.deliver_from_js(msg.get("data") or {}, msg.get("buffers"))
        elif msg_type == "comm_close":
            if c is not None:
                c.handle_close(
                    {
                        "content": {
                            "comm_id": comm_id,
                            "data": msg.get("data") or {},
                        }
                    }
                )
            unregister_comm(comm_id)

    def activate(self) -> None:
        """Make this App the active bridge so new widget comms route here.

        Useful when several Apps are alive at once (the most recently used one
        should receive newly created widget comms).
        """
        push_bridge(self)
        from .display_mode import sync_matplotlib

        sync_matplotlib(self.display_mode)

    def set_display_mode(self, mode: str) -> None:
        """Switch this App between inline output and pop-up windows."""
        from .display_mode import validate_display_mode

        self.display_mode = validate_display_mode(mode)
        self.activate()

    def set_theme(
        self,
        theme: str,
        *,
        colors: Mapping[str, str] | None = None,
    ) -> None:
        """Switch the shell between ``light`` and ``dark`` appearance.

        ``colors`` optionally overrides CSS variables (``bg``, ``fg``, ``muted``,
        ``border``, ``panel``, ``hosted_bg``, ``widget_label``, ``link``,
        ``table_stripe``). When omitted, stock light/dark variables are used.
        """
        if theme not in ("light", "dark"):
            raise ValueError(f"theme must be 'light' or 'dark', got {theme!r}")
        self.theme = theme
        if colors is not None:
            self._theme_colors = {str(k): str(v) for k, v in colors.items()} or None
        else:
            self._theme_colors = None
        self._apply_native_shell_bg()
        self._apply_theme()

    def _shell_bg_hex(self) -> str:
        colors = self._theme_colors
        if colors and colors.get("bg"):
            return colors["bg"]
        return "#1e1e1e" if self.theme == "dark" else "#ffffff"

    def _apply_native_shell_bg(self) -> None:
        shell_bg = self._shell_bg_hex()
        try:
            self._frame.configure(bg=shell_bg)
        except tk.TclError:
            pass
        try:
            r, g, b, a = _hex_to_rgba(shell_bg)
            self.webview.set_background_color(r, g, b, a)
        except Exception:
            pass

    def _apply_theme(self) -> None:
        if self._destroyed or not self._ready:
            return
        colors = self._theme_colors or {}
        props: dict[str, str] = {}
        for key, var in _THEME_COLOR_VARS.items():
            if key in colors and colors[key]:
                props[var] = colors[key]
        clear_vars = [v for v in _THEME_COLOR_VARS.values() if v not in props]
        try:
            self.webview.eval_js(
                "(function(){"
                "var root=document.documentElement;"
                f"root.setAttribute('data-theme',{json.dumps(self.theme)});"
                f"var set={json.dumps(props)};"
                "Object.keys(set).forEach(function(k){"
                "root.style.setProperty(k,set[k]);"
                "});"
                f"var clear={json.dumps(clear_vars)};"
                "clear.forEach(function(k){root.style.removeProperty(k);});"
                "})();"
            )
        except Exception:
            pass

    # ---------------------------------------------------------------- display
    def display(self, *widgets: Any) -> None:
        """Mount one or more widgets in the WebView root (notebook cell body)."""
        if not widgets:
            return
        # Route this widget tree's comm_open traffic to this App, even when
        # another App was activated more recently.
        self.activate()
        model_ids = prepare_widgets(widgets, bridge=self)
        self.send_to_js({"channel": "display", "model_ids": model_ids})

    def _ensure_cell_output(self) -> Any:
        """Lazy-create the default notebook-style output area under the cell."""
        if self._cell_output is None:
            from .output import Output

            self._cell_output = Output()
        if not self._cell_output_mounted:
            self.display(self._cell_output)
            self._cell_output_mounted = True
        return self._cell_output

    def _append_output(self, items: list[Any]) -> None:
        out = self._ensure_cell_output()
        out._append(items)

    def _clear_output(self, wait: bool = False) -> None:
        out = self._ensure_cell_output()
        out.clear_output(wait=wait)

    def call_soon(self, fn: Any, *args: Any) -> None:
        """Schedule ``fn(*args)`` on the Tk UI thread."""
        self.root.after(0, lambda: fn(*args))

    def run(self) -> None:
        """Enter the Tk event loop (blocks)."""
        self.root.mainloop()

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True

        pop_bridge(self)
        try:
            _active_apps.remove(self)
        except ValueError:
            pass

        self._ready = False
        self._ready_callbacks.clear()
        self._outbound.clear()
        self._flush_scheduled = False
        if self._flush_after_id is not None:
            try:
                self.root.after_cancel(self._flush_after_id)
            except Exception:
                pass
            self._flush_after_id = None

        self._cell_output = None
        self._cell_output_mounted = False

        try:
            self.webview.destroy()
        except Exception:
            pass
        if self._owns_root:
            try:
                self.root.destroy()
            except tk.TclError:
                pass

        # Last App out restores the process-wide patches it relied on.
        if not _active_apps:
            _teardown_global_patches()


def _teardown_global_patches() -> None:
    """Undo process-wide monkey-patches once no App is alive."""
    from .jupyter import uninstall_jupyter_support
    from .output import uninstall_display_logging, uninstall_excepthook

    uninstall_jupyter_support()
    uninstall_display_logging()
    uninstall_excepthook()
    reset_comms()


# Public alias from the architecture doc
Runtime = App
