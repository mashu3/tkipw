"""Desktop App: Tk + tkwry WebView hosting the Jupyter widgets runtime."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
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

_SHELL = """\
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>tkipw</title>
  <style>__CSS__</style>
</head>
<body>
  <div id="tkipw-root">
    <div id="tkipw-status">Starting widget runtime…</div>
  </div>
  <script>__JS__</script>
</body>
</html>
"""


def _load_shell_html(*, compact: bool = False) -> str:
    runtime = _HTML_DIR / "runtime.js"
    css_path = _HTML_DIR / "runtime.css"
    if not runtime.exists():
        raise FileNotFoundError(
            f"Missing {runtime}. Run: cd js && npm install && npm run build"
        )
    js = runtime.read_text(encoding="utf-8")
    css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    css += """
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
/* Rich output fills the available pane width. */
#tkipw-widgets .jupyter-widgets,
#tkipw-widgets .widget-box,
#tkipw-widgets .widget-vbox,
#tkipw-widgets .widget-html,
#tkipw-widgets .widget-html > div {
  width: 100% !important;
  max-width: 100%;
  box-sizing: border-box;
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
"""
    if compact:
        # Window-mode pop-ups: kill ipywidgets chrome margin.
        # Full-bleed only for media (iframe/img). Text/errors keep normal
        # line-height and padding so tracebacks don't overlap.
        css += """
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

/* Maps / charts / images: edge-to-edge, no text chrome.
   Do not match bare ``img`` — ipyleaflet tiles/markers are also ``img`` and
   must keep Leaflet's pixel sizes (``width/height: 100%`` collapses them). */
body.tkipw-compact #tkipw-widgets:has(iframe),
body.tkipw-compact #tkipw-widgets:has(.widget-image),
body.tkipw-compact #tkipw-widgets:has(.leaflet-container) {
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
body.tkipw-compact .widget-image img {
  max-width: none !important;
  width: 100% !important;
  height: 100% !important;
  object-fit: contain;
}
"""
    # Avoid </script> in source breaking the HTML shell
    js = js.replace("</script>", "<\\/script>")
    body = '<body class="tkipw-compact">' if compact else "<body>"
    return (
        _SHELL.replace("__CSS__", css).replace("__JS__", js).replace("<body>", body, 1)
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
    ) -> None:
        install_comm_backend()

        from .display_mode import validate_display_mode

        self.display_mode = validate_display_mode(display_mode)
        self.compact = compact
        self.theme = "light"
        self._ready = False
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
            self.root = tk.Tk()
            self._container: tk.Misc = self.root
            self.root.title(title)
            self.root.geometry(f"{width}x{height}")
        else:
            self._container = container
            self.root = container.winfo_toplevel()

        self._frame = tk.Frame(self._container)
        self._frame.pack(fill="both", expand=True)

        html = _load_shell_html(compact=compact)
        self.webview = WebView(
            self._frame,
            html=html,
            ipc_handler=self._on_ipc,
            on_page_load=self._on_page_load,
            on_navigation=lambda _url: True,
            devtools=devtools,
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
            # Window mode: the root is only an event-loop host; content opens
            # in Toplevel pop-ups (avoid an empty second window).
            if self.display_mode == "window":
                self.root.withdraw()

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
            self._apply_theme()
            self._schedule_flush()
            return
        if channel == "comm":
            self._handle_comm_from_js(msg)
            return
        if channel == "error":
            detail = msg.get("detail") or msg.get("message") or raw
            print(f"[tkipw] frontend error: {detail}")

    def _handle_comm_from_js(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("msg_type")
        comm_id = msg.get("comm_id")
        if not comm_id:
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

    def set_theme(self, theme: str) -> None:
        """Switch the shell between ``light`` and ``dark`` appearance."""
        if theme not in ("light", "dark"):
            raise ValueError(f"theme must be 'light' or 'dark', got {theme!r}")
        self.theme = theme
        self._apply_theme()

    def _apply_theme(self) -> None:
        if self._destroyed or not self._ready:
            return
        try:
            self.webview.eval_js(
                "document.documentElement.setAttribute("
                f"'data-theme', {json.dumps(self.theme)}"
                ");"
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
