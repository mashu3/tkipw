"""tkipw playground — inline-mode demo.

Left: Monaco (multi-tab), right: stacked notebook-style output.
``App(display_mode="inline")`` is the default; this app is the reference for
that mode. See ``examples/*_demo.py`` for window-mode pop-ups.

Samples are open as editor tabs; switching tabs replaces the old combobox.
Run executes the active tab on the Tk main thread (needed for VTK/Cocoa and
pyvista ``export_html`` / trame).

Requires network on first launch (Monaco Editor CDN; pyvista HTML uses vtk.js).
"""

from __future__ import annotations

import json
import sys
import time
import tkinter as tk
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tkinter import filedialog, messagebox

import ipywidgets as widgets
import tkface
from IPython.display import Markdown
from tkwry import WebView

import tkipw.output as out
from tkipw import App

MONACO_VERSION = "0.52.2"


class _ExecutionStopped(BaseException):
    """Internal cooperative interruption raised by the execution tracer."""


class EditorShortcutBindings:
    """Bind editor shortcuts before tkwry's macOS web key guard.

    WebViews often cannot read the system clipboard on Ctrl/Cmd+V, so paste
    (and related edit actions) are handled in Tk and forwarded to Monaco —
    same approach as tkwry ``markdown_demo``.
    """

    TAG = "PlaygroundEditorShortcuts"
    UNDO = (
        "<Command-z>",
        "<Command-Z>",
        "<Control-z>",
        "<Control-Z>",
        "<<Undo>>",
    )
    REDO = (
        "<Command-Shift-z>",
        "<Command-Shift-Z>",
        "<Control-y>",
        "<Control-Y>",
        "<<Redo>>",
    )
    CUT = (
        "<Command-x>",
        "<Command-X>",
        "<Control-x>",
        "<Control-X>",
        "<<Cut>>",
    )
    COPY = (
        "<Command-c>",
        "<Command-C>",
        "<Control-c>",
        "<Control-C>",
        "<<Copy>>",
    )
    PASTE = (
        "<Command-v>",
        "<Command-V>",
        "<Control-v>",
        "<Control-V>",
        "<<Paste>>",
    )
    FIND = (
        "<Command-f>",
        "<Command-F>",
        "<Control-f>",
        "<Control-F>",
    )
    REPLACE = (
        "<Command-Option-f>",
        "<Command-Option-F>",
        "<Command-Alt-f>",
        "<Command-Alt-F>",
        "<Control-h>",
        "<Control-H>",
    )
    NEW_TAB = (
        "<Command-t>",
        "<Command-T>",
        "<Control-t>",
        "<Control-T>",
    )
    OPEN = (
        "<Command-o>",
        "<Command-O>",
        "<Control-o>",
        "<Control-O>",
    )
    SAVE = (
        "<Command-s>",
        "<Command-S>",
        "<Control-s>",
        "<Control-S>",
    )
    SAVE_AS = (
        "<Command-Shift-s>",
        "<Command-Shift-S>",
        "<Control-Shift-s>",
        "<Control-Shift-S>",
    )
    CLOSE_TAB = (
        "<Command-w>",
        "<Command-W>",
        "<Control-w>",
        "<Control-W>",
    )

    @classmethod
    def install(
        cls,
        root: tk.Misc,
        bindings: list[tuple[tuple[str, ...], Callable[[tk.Event], str]]],
        *,
        global_bindings: list[tuple[tuple[str, ...], Callable[[tk.Event], str]]]
        | None = None,
    ) -> None:
        for sequences, handler in bindings:
            for sequence in sequences:
                root.bind_class(cls.TAG, sequence, handler)
        cls._prepend_tag_tree(root, cls.TAG)
        if global_bindings:
            for sequences, handler in global_bindings:
                for sequence in sequences:
                    root.bind_all(sequence, handler, add="+")

    @classmethod
    def register_virtual_events(cls, root: tk.Misc) -> None:
        if sys.platform != "darwin":
            return
        for sequence in cls.REPLACE:
            root.event_add("<<Replace>>", sequence)

    @staticmethod
    def wrap(action: Callable[[], None]) -> Callable[[tk.Event], str]:
        def handler(_event: tk.Event) -> str:
            action()
            return "break"

        return handler

    @staticmethod
    def _prepend_tag_tree(widget: tk.Misc, tag: str) -> None:
        tags = widget.bindtags()
        if not tags or tags[0] != tag:
            widget.bindtags((tag, *tuple(t for t in tags if t != tag)))
        for child in widget.winfo_children():
            EditorShortcutBindings._prepend_tag_tree(child, tag)


README_SAMPLE = """\
# Markdown in tkipw

This is a real **README.md** tab. Press the play button or
<kbd>⌘/Ctrl</kbd>+<kbd>Enter</kbd> to render it in the output pane.

* **Bold**, *italic*, links, lists, tables, and fenced code are supported.
* The result follows the output pane's light or dark theme.

| Runtime | View |
| --- | --- |
| Python | Markdown |
| tkwry | System WebView |

```python
from IPython.display import Markdown, display

display(Markdown("# Hello"))
```
"""

SAMPLES: dict[str, str] = {
    "matplotlib": """\
import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 2 * np.pi, 200)
plt.figure(figsize=(7, 3.5), dpi=100)
plt.plot(x, np.sin(x), color="#2563eb", lw=2)
plt.title("sin")
plt.xlabel("x")
plt.ylabel("y")
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()
""",
    "pyvista": """\
import pyvista as pv

sphere = pv.Sphere()

# Uses PyVista's Jupyter path (tkipw forces notebook=True).
# "trame"/"server" are remapped to "client" so a native VTK window
# does not open; needs: pip install "pyvista[jupyter]"
sphere.plot(jupyter_backend="client")

# long example
# plotter = pv.Plotter(notebook=True)
# plotter.add_mesh(sphere)
# plotter.show(jupyter_backend="client")
""",
    "pandas": """\
import pandas as pd

df = pd.DataFrame(
    {
        "city": ["Tokyo", "Osaka", "Fukuoka"],
        "sales": [120.5, 88.0, 95.2],
        "units": [10, 7, 9],
    }
)
display(df)
display(df.describe())
""",
    "folium": """\
import folium

# Pixel size is preferred in window mode (no empty chrome around the map).
tokyo = folium.Map(
    location=[35.6812, 139.7671],
    zoom_start=12,
    width=800,
    height=480,
)
folium.Marker(
    [35.6812, 139.7671],
    tooltip="Tokyo Station",
).add_to(tokyo)
display(tokyo)

tokyo_satellite = folium.Map(
    location=[35.6812, 139.7671],
    zoom_start=12,
    tiles=None,
    width=800,
    height=480,
)
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Tiles © Esri",
    name="Esri World Imagery",
).add_to(tokyo_satellite)
folium.Marker(
    [35.6812, 139.7671],
    tooltip="Tokyo Station",
).add_to(tokyo_satellite)
display(tokyo_satellite)
""",
    "ipyleaflet": """\
from ipyleaflet import Map, Marker
from ipywidgets import Layout

tokyo = (35.6812, 139.7671)
widget_map = Map(
    center=tokyo,
    zoom=12,
    layout=Layout(width="100%", height="480px"),
)
widget_map.add(Marker(location=tokyo, title="Tokyo Station"))
display(widget_map)
""",
    "ipycanvas": """\
from ipycanvas import Canvas, hold_canvas

canvas = Canvas(width=640, height=360)
display(canvas)

with hold_canvas():
    canvas.fill_style = "#eff6ff"
    canvas.fill_rect(0, 0, canvas.width, canvas.height)

    canvas.fill_style = "#2563eb"
    canvas.fill_rect(40, 40, 200, 120)

    canvas.stroke_style = "#f59e0b"
    canvas.line_width = 4
    canvas.stroke_circle(420, 180, 80)

    canvas.fill_style = "#0f172a"
    canvas.font = "24px sans-serif"
    canvas.fill_text("ipycanvas in tkipw", 40, 320)
""",
    "bqplot": """\
from bqplot import Axis, Figure, LinearScale, Scatter
from ipywidgets import Layout

x_sc = LinearScale()
y_sc = LinearScale()
scatter = Scatter(
    x=[1, 2, 3, 4, 5],
    y=[1, 4, 9, 16, 25],
    scales={"x": x_sc, "y": y_sc},
    colors=["#2563eb"],
)
ax_x = Axis(scale=x_sc, label="x")
ax_y = Axis(scale=y_sc, label="y")
ax_y.orientation = "vertical"
fig = Figure(
    marks=[scatter],
    axes=[ax_x, ax_y],
    title="bqplot in tkipw",
    layout=Layout(width="100%", height="400px"),
)
display(fig)
""",
    "pillow": """\
from PIL import Image, ImageDraw

im = Image.new("RGB", (640, 320), "#eff6ff")
draw = ImageDraw.Draw(im)
for x in range(im.width):
    color = (37, 99, 235, int(40 + 180 * x / im.width))
    draw.line((x, 0, x, im.height), fill=color[:3])
draw.ellipse((210, 50, 430, 270), fill="#fbbf24", outline="white", width=8)
im.show()  # Routed into the tkipw output pane (no external Preview window).
""",
    "altair": """\
import altair as alt

data = alt.Data(
    values=[
        {"city": "Tokyo", "sales": 120},
        {"city": "Osaka", "sales": 88},
        {"city": "Fukuoka", "sales": 95},
    ]
)
chart = (
    alt.Chart(data)
    .mark_bar(color="#2563eb")
    .encode(x="city:N", y="sales:Q", tooltip=["city:N", "sales:Q"])
    .properties(title="Altair in tkipw", width=480, height=320)
)
display(chart)
""",
    "bokeh": """\
from bokeh.plotting import figure, show

plot = figure(
    title="Bokeh in tkipw",
    width=640,
    height=400,
    tools="pan,wheel_zoom,box_zoom,reset,save",
)
plot.line([1, 2, 3, 4, 5], [1, 4, 9, 16, 25], line_width=3)
plot.scatter([1, 2, 3, 4, 5], [1, 4, 9, 16, 25], size=10)
show(plot)
""",
    "error": """\
import logging
import sys

logging.warning("this is a warning")
print("stdout line", flush=True)
print("stderr line", file=sys.stderr, flush=True)
raise ValueError("boom — notebook-style traceback below")
""",
}


class StackedOutput(out.Output):
    """Notebook output target that stacks each display call vertically."""

    def __init__(self) -> None:
        super().__init__()
        self._serial = 0

    def clear_output(self, wait: bool = False) -> None:
        if wait:
            self._wait_clear = True
            return
        self._wait_clear = False
        self.children = ()
        self._serial = 0

    def _append(self, items: list[widgets.Widget]) -> None:
        if not items:
            return
        if self._wait_clear:
            self.clear_output(wait=False)

        self._serial += 1
        kind = _output_kind(items)
        header = widgets.HTML(
            value=(f'<div class="tkipw-section-header">{self._serial} · {kind}</div>')
        )
        body: widgets.Widget
        if len(items) == 1:
            body = items[0]
        else:
            body = widgets.VBox(
                items,
                layout=widgets.Layout(width="100%", overflow="hidden"),
            )
        # overflow:hidden keeps folium/leaflet iframes from covering
        # neighboring section chrome after map interaction resizes them.
        section = widgets.VBox(
            [header, body],
            layout=widgets.Layout(
                width="100%",
                margin="0 0 12px 0",
                overflow="hidden",
            ),
        )
        section.add_class("tkipw-section")
        self.children = tuple(self.children) + (section,)


def _output_kind(items: list[widgets.Widget]) -> str:
    """Return a compact section label for converted display widgets."""
    if len(items) != 1:
        return "Output"
    item = items[0]
    if isinstance(item, widgets.HTML):
        value = item.value.lower()
        if "tkipw-error" in value or "traceback" in value:
            return "Error"
        if "tkipw-stderr" in value:
            return "Stderr"
        if "<iframe" in value:
            return "View"
        if "<img" in value:
            return "Figure"
        if "tkipw-markdown" in value:
            return "Markdown"
        if "<table" in value:
            return "Table"
        if "<pre" in value:
            return "Text"
        return "HTML"
    name = type(item).__name__
    return name.removesuffix("Widget")[:16] or "Output"


def _parse_eval_json_object(result: str) -> dict | None:
    """Parse ``eval_js_with_callback`` results that may be JSON-encoded twice."""
    if not result or result == "null":
        return None
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        try:
            again = json.loads(parsed)
        except json.JSONDecodeError:
            return None
        return again if isinstance(again, dict) else None
    return None


def _editor_html(initial_tabs: list[dict[str, str]]) -> str:
    """Monaco workbench with VS Code-style tabs (python language)."""
    initial_tabs_json = json.dumps(initial_tabs)
    return f"""\
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      height: 100%;
      overflow: hidden;
      background: #1e1e1e;
      color: #cccccc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    #workbench {{
      display: flex;
      flex-direction: column;
      height: 100%;
    }}
    #tab-bar {{
      display: flex;
      align-items: stretch;
      height: 35px;
      background: #252526;
      border-bottom: 1px solid #1e1e1e;
      flex-shrink: 0;
      overflow: hidden;
    }}
    #tabs {{
      display: flex;
      flex: 1;
      min-width: 0;
      overflow-x: auto;
      overflow-y: hidden;
      scrollbar-width: none;
      -ms-overflow-style: none;
    }}
    #tabs::-webkit-scrollbar {{
      display: none;
      width: 0;
      height: 0;
    }}
    .tab {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      max-width: 240px;
      padding: 0 8px 0 8px;
      background: #2d2d2d;
      border-right: 1px solid #1e1e1e;
      cursor: pointer;
      user-select: none;
      flex-shrink: 0;
    }}
    .tab:hover {{ background: #1e1e1e; }}
    .tab.active {{
      background: #1e1e1e;
      border-top: 1px solid #007acc;
    }}
    .tab-icon {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 14px;
      height: 14px;
      flex-shrink: 0;
    }}
    .tab.active .tab-icon {{
      display: none;
    }}
    .tab-icon svg {{
      display: block;
      width: 14px;
      height: 14px;
    }}
    .tab-run {{
      display: none;
      align-items: center;
      justify-content: center;
      width: 14px;
      height: 14px;
      border: none;
      border-radius: 3px;
      background: transparent;
      color: #89d185;
      padding: 0;
      cursor: pointer;
      flex-shrink: 0;
      transition: background 0.1s ease, color 0.1s ease;
    }}
    .tab.active .tab-run {{
      display: inline-flex;
    }}
    .tab-run:hover:not(:disabled) {{
      background: rgba(137, 209, 133, 0.16);
      color: #a8e6a4;
    }}
    .tab-run.stop {{
      color: #f14c4c;
    }}
    .tab-run.stop:hover {{
      color: #ff6b6b;
      background: rgba(241, 76, 76, 0.18);
    }}
    .tab-run:disabled {{
      opacity: 0.3;
      cursor: default;
      color: #cccccc;
    }}
    .tab-run:disabled:hover {{
      background: transparent;
      color: #cccccc;
    }}
    .tab-run svg {{
      display: block;
      width: 11px;
      height: 11px;
      fill: currentColor;
    }}
    .tab-label {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      line-height: 35px;
      min-width: 0;
    }}
    .tab-dirty {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #cccccc;
      flex-shrink: 0;
      transition: opacity 0.1s ease;
    }}
    .tab:hover .tab-dirty,
    .tab.active .tab-dirty {{
      opacity: 0;
      width: 0;
      margin: 0;
    }}
    .tab-actions {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      flex-shrink: 0;
      margin-right: -4px;
    }}
    .tab-close {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      border: none;
      border-radius: 4px;
      background: transparent;
      color: #cccccc;
      padding: 0;
      cursor: pointer;
      flex-shrink: 0;
      opacity: 0;
      transition: opacity 0.1s ease, background 0.1s ease;
    }}
    .tab:hover .tab-close,
    .tab.active .tab-close {{ opacity: 1; }}
    .tab-close:hover {{
      background: rgba(255, 255, 255, 0.1);
      color: #ffffff;
    }}
    .tab-close:disabled {{
      opacity: 0.35;
      cursor: default;
    }}
    .tab-close:disabled:hover {{
      background: transparent;
      color: #cccccc;
    }}
    .tab-close svg {{
      display: block;
      width: 16px;
      height: 16px;
      fill: currentColor;
    }}
    #new-tab,
    #toggle-output {{
      width: 32px;
      border: none;
      border-left: 1px solid #1e1e1e;
      background: #252526;
      color: #cccccc;
      cursor: pointer;
      flex-shrink: 0;
    }}
    #new-tab {{
      font-size: 18px;
      line-height: 1;
    }}
    #toggle-output {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0;
    }}
    #toggle-output svg {{
      width: 16px;
      height: 16px;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.2;
    }}
    #new-tab:hover,
    #toggle-output:hover {{ background: #2a2d2e; }}
    #toggle-output.active {{
      color: #ffffff;
      background: #37373d;
    }}
    #editor {{
      flex: 1;
      min-height: 0;
      width: 100%;
    }}
    html[data-theme="light"] body {{
      background: #ffffff;
      color: #333333;
    }}
    html[data-theme="light"] #tab-bar {{
      background: #ececec;
      border-bottom-color: #d4d4d4;
    }}
    html[data-theme="light"] .tab {{
      background: #e8e8e8;
      border-right-color: #d4d4d4;
    }}
    html[data-theme="light"] .tab:hover {{
      background: #f3f3f3;
    }}
    html[data-theme="light"] .tab.active {{
      background: #ffffff;
      border-top-color: #0078d4;
    }}
    html[data-theme="light"] .tab-dirty {{
      background: #424242;
    }}
    html[data-theme="light"] .tab-run {{
      color: #388a34;
    }}
    html[data-theme="light"] .tab-run:hover:not(:disabled) {{
      background: rgba(56, 138, 52, 0.12);
      color: #2f7a2c;
    }}
    html[data-theme="light"] .tab-run:disabled,
    html[data-theme="light"] .tab-run:disabled:hover {{
      color: #424242;
    }}
    html[data-theme="light"] .tab-close {{
      color: #424242;
    }}
    html[data-theme="light"] #new-tab,
    html[data-theme="light"] #toggle-output {{
      background: #ececec;
      border-left-color: #d4d4d4;
      color: #424242;
    }}
    html[data-theme="light"] #toggle-output.active {{
      color: #0078d4;
      background: #dcdcdc;
    }}
  </style>
</head>
<body>
  <div id="workbench">
    <div id="tab-bar">
      <div id="tabs"></div>
      <button id="new-tab" type="button" title="New tab">+</button>
      <button id="toggle-output" type="button"
              title="Toggle Output Pane" aria-label="Toggle Output Pane"
              aria-pressed="false">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <rect x="1.75" y="2.25" width="12.5" height="11.5" rx="1"/>
          <path d="M10.25 2.25v11.5"/>
        </svg>
      </button>
    </div>
    <div id="editor"></div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/monaco-editor@{MONACO_VERSION}/min/vs/loader.js"></script>
  <script>
    const INITIAL_TABS = {initial_tabs_json};

    function post(msg) {{
      if (window.ipc) window.ipc.postMessage(JSON.stringify(msg));
    }}

    require.config({{
      paths: {{
        vs: "https://cdn.jsdelivr.net/npm/monaco-editor@{MONACO_VERSION}/min/vs",
      }},
    }});

    require(["vs/editor/editor.main"], function () {{
      const tabs = [];
      let activeTabId = null;
      let nextTabId = 1;
      let untitledSerial = 0;
      let runBusy = false;

      const editor = monaco.editor.create(document.getElementById("editor"), {{
        language: "python",
        theme: "vs-dark",
        fontSize: 13,
        lineNumbers: "on",
        minimap: {{ enabled: true }},
        wordWrap: "on",
        scrollBeyondLastLine: false,
        automaticLayout: true,
        contextmenu: false,
        fixedOverflowWidgets: true,
        tabSize: 4,
        insertSpaces: true,
      }});

      document.addEventListener("contextmenu", (event) => event.preventDefault());

      function nextUntitledTitle() {{
        untitledSerial += 1;
        return untitledSerial === 1 ? "untitled.py" : `untitled${{untitledSerial}}.py`;
      }}

      function tabById(id) {{
        return tabs.find((tab) => tab.id === id) || null;
      }}

      function activeTab() {{
        return activeTabId ? tabById(activeTabId) : null;
      }}

      function languageForTitle(title) {{
        const lower = String(title || "").toLowerCase();
        if (lower.endsWith(".md") || lower.endsWith(".markdown")) return "markdown";
        if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
        if (lower.endsWith(".json")) return "json";
        return "python";
      }}

      function isDirty(tab) {{
        return tab.model.getValue() !== tab.baseline;
      }}

      function renderTabBar() {{
        const container = document.getElementById("tabs");
        const closePath =
          "M8 8.707l3.646 3.647.708-.707L8.707 8l3.647-3.646-.707-.708" +
          "L8 7.293 4.354 3.646l-.707.708L7.293 8l-3.646 3.646.707.708L8 8.707z";
        const closeIcon =
          '<svg viewBox="0 0 16 16" aria-hidden="true">' +
          '<path d="' + closePath + '"/>' +
          "</svg>";
        const runIcon =
          '<svg viewBox="0 0 16 16" aria-hidden="true">' +
          '<path d="M4 2.5v11l9-5.5L4 2.5z"/>' +
          "</svg>";
        const stopIcon =
          '<svg viewBox="0 0 16 16" aria-hidden="true">' +
          '<rect x="3" y="3" width="10" height="10" rx="1"/>' +
          "</svg>";
        // Classic blue/yellow Python logo (compact).
        const pythonIcon =
          '<svg viewBox="0 0 24 24" aria-hidden="true">' +
          '<path fill="#3776AB" d="M11.8.1C5.9.3 5.5 2.9 5.5 2.9l.01 2.9h6.19v.87' +
          'H3.7S.3 6.3.5 12.1c.2 5.7 3.2 5.6 3.2 5.6h1.9v-2.7s-.1-3.2 3.1-3.2h5.3' +
          's3 .1 3-2.9V3.1S17.3-.1 11.8.1zM9.1 2c.6 0 1.1.5 1.1 1.1S9.7 4.2 9.1 4' +
          '.2 8 3.7 8 3.1 8.5 2 9.1 2z"/>' +
          '<path fill="#FFD43B" d="M12.2 23.9c5.9-.2 6.3-2.8 6.3-2.8l-.01-2.9h-6.' +
          '19v-.87h8.01s3.4.4 3.2-5.4c-.2-5.7-3.2-5.6-3.2-5.6h-1.9v2.7s.1 3.2-3.1' +
          ' 3.2H10s-3-.1-3 2.9v5.8s.3 3.2 5.2 3zM14.9 22c-.6 0-1.1-.5-1.1-1.1s.5-' +
          '1.1 1.1-1.1 1.1.5 1.1 1.1-.5 1.1-1.1 1.1z"/>' +
          "</svg>";
        const markdownIcon =
          '<svg viewBox="0 0 16 16" aria-hidden="true">' +
          '<rect x="1" y="3" width="14" height="10" rx="1" fill="#519aba"/>' +
          '<path fill="#fff" d="M3 5v6h1.5V7.4L6 9.2l1.5-1.8V11H9V5H7.5L6 7' +
          ' 4.5 5H3zm7 3h1.5V5h1v3H14l-2 2.2L10 8z"/>' +
          "</svg>";
        container.replaceChildren();
        for (const tab of tabs) {{
          const el = document.createElement("div");
          el.className = "tab" + (tab.id === activeTabId ? " active" : "");
          el.dataset.id = tab.id;

          const run = document.createElement("button");
          run.className = "tab-run";
          run.classList.toggle("stop", runBusy);
          run.type = "button";
          run.title = runBusy ? "Stop" : "Run (⌘/Ctrl+Enter)";
          run.innerHTML = runBusy ? stopIcon : runIcon;
          run.addEventListener("click", (event) => {{
            event.stopPropagation();
            if (runBusy) {{
              post({{ type: "stop" }});
            }} else {{
              requestRun(tab.id);
            }}
          }});
          el.appendChild(run);

          const icon = document.createElement("span");
          icon.className = "tab-icon";
          const language = tab.model.getLanguageId();
          icon.title = languageLabel(tab.model);
          icon.innerHTML = language === "markdown" ? markdownIcon : pythonIcon;
          el.appendChild(icon);

          const label = document.createElement("span");
          label.className = "tab-label";
          label.textContent = tab.title;
          el.appendChild(label);

          if (isDirty(tab)) {{
            const dot = document.createElement("span");
            dot.className = "tab-dirty";
            dot.title = "Modified";
            el.appendChild(dot);
          }}

          const actions = document.createElement("span");
          actions.className = "tab-actions";

          const close = document.createElement("button");
          close.className = "tab-close";
          close.type = "button";
          close.title = "Close";
          close.innerHTML = closeIcon;
          if (tabs.length <= 1) close.disabled = true;
          close.addEventListener("click", (event) => {{
            event.stopPropagation();
            if (tabs.length > 1) closeTab(tab.id);
          }});
          actions.appendChild(close);
          el.appendChild(actions);

          el.addEventListener("click", () => switchTab(tab.id));
          el.addEventListener("mousedown", (event) => {{
            if (event.button === 1 && tabs.length > 1) {{
              event.preventDefault();
              closeTab(tab.id);
            }}
          }});

          container.appendChild(el);
        }}
        const active = container.querySelector(".tab.active");
        if (active && typeof active.scrollIntoView === "function") {{
          active.scrollIntoView({{
            behavior: "auto",
            inline: "nearest",
            block: "nearest",
          }});
        }}
      }}

      function switchTab(id) {{
        const tab = tabById(id);
        if (!tab || activeTabId === id) return;
        activeTabId = id;
        editor.setModel(tab.model);
        renderTabBar();
        updateEditorStatus();
        post({{ type: "tab", title: tab.title }});
      }}

      function openTab(title, content, path) {{
        const id = String(nextTabId++);
        const uri = monaco.Uri.parse(`inmemory://${{id}}/${{title}}`);
        const model = monaco.editor.createModel(
          content,
          languageForTitle(title),
          uri,
        );
        const tab = {{
          id,
          title,
          model,
          baseline: content,
          path: path || null,
        }};
        tabs.push(tab);
        activeTabId = id;
        editor.setModel(model);
        renderTabBar();
        updateEditorStatus();
        post({{ type: "tab", title: tab.title }});
        return id;
      }}

      function closeTab(id) {{
        if (tabs.length <= 1) return;
        const index = tabs.findIndex((tab) => tab.id === id);
        if (index < 0) return;
        const closing = tabs[index];
        const wasActive = activeTabId === id;
        tabs.splice(index, 1);
        closing.model.dispose();
        if (wasActive) {{
          const next = tabs[Math.min(index, tabs.length - 1)];
          activeTabId = next.id;
          editor.setModel(next.model);
          updateEditorStatus();
          post({{ type: "tab", title: next.title }});
        }}
        renderTabBar();
      }}

      window.editorNewTab = function (title, content, path) {{
        openTab(
          title || nextUntitledTitle(),
          content == null ? "" : content,
          path || null,
        );
      }};

      window.editorCloseActiveTab = function () {{
        if (activeTabId) closeTab(activeTabId);
      }};

      window.editorGetActiveTabInfo = function () {{
        const tab = activeTab();
        if (!tab) return null;
        return {{
          id: tab.id,
          title: tab.title,
          content: tab.model.getValue(),
          path: tab.path,
        }};
      }};

      window.editorMarkSaved = function (path, title) {{
        const tab = activeTab();
        if (!tab) return;
        tab.path = path || null;
        if (title) {{
          tab.title = title;
          monaco.editor.setModelLanguage(tab.model, languageForTitle(title));
        }}
        tab.baseline = tab.model.getValue();
        renderTabBar();
        post({{ type: "tab", title: tab.title }});
      }};

      window.editorUndo = function () {{
        editor.focus();
        editor.trigger("keyboard", "undo", null);
      }};
      window.editorRedo = function () {{
        editor.focus();
        editor.trigger("keyboard", "redo", null);
      }};
      window.editorCut = function () {{
        editor.focus();
        editor.trigger("keyboard", "editor.action.clipboardCutAction", null);
      }};
      window.editorCopy = function () {{
        editor.focus();
        editor.trigger("keyboard", "editor.action.clipboardCopyAction", null);
      }};
      window.editorPasteText = function (text) {{
        if (text == null || text === "") return;
        editor.focus();
        const selection = editor.getSelection();
        if (!selection) return;
        editor.executeEdits("clipboard-paste", [{{
          range: selection,
          text,
          forceMoveMarkers: true,
        }}]);
      }};

      function runEditorAction(candidates) {{
        editor.focus();
        requestAnimationFrame(() => {{
          for (const id of candidates) {{
            const action = editor.getAction(id);
            if (action) {{
              action.run();
              return;
            }}
          }}
        }});
      }}
      window.editorFind = function () {{
        runEditorAction(["actions.find", "editor.action.startFindAction"]);
      }};
      window.editorReplace = function () {{
        runEditorAction([
          "editor.action.startFindReplaceAction",
          "actions.findWithReplace",
        ]);
      }};
      window.editorSetMinimap = function (enabled) {{
        editor.updateOptions({{ minimap: {{ enabled: !!enabled }} }});
      }};
      window.editorSetWordWrap = function (enabled) {{
        editor.updateOptions({{ wordWrap: enabled ? "on" : "off" }});
      }};
      window.editorSetTheme = function (mode) {{
        const dark = mode !== "light";
        document.documentElement.setAttribute(
          "data-theme",
          dark ? "dark" : "light",
        );
        monaco.editor.setTheme(dark ? "vs-dark" : "vs");
      }};

      const outputToggle = document.getElementById("toggle-output");
      let statusFrame = 0;

      function languageLabel(model) {{
        if (!model) return "Plain Text";
        const id = model.getLanguageId();
        if (id === "python") return "Python";
        if (id === "json") return "JSON";
        if (id === "markdown") return "Markdown";
        if (id === "html") return "HTML";
        if (id === "css") return "CSS";
        if (id === "javascript") return "JavaScript";
        if (id === "typescript") return "TypeScript";
        return id ? id.charAt(0).toUpperCase() + id.slice(1) : "Plain Text";
      }}

      function updateEditorStatus() {{
        if (statusFrame) return;
        statusFrame = requestAnimationFrame(() => {{
          statusFrame = 0;
          const model = editor.getModel();
          const pos = editor.getPosition();
          const sel = editor.getSelection();
          let cursor = "Ln 1, Col 1";
          if (pos) {{
            cursor = "Ln " + pos.lineNumber + ", Col " + pos.column;
            if (sel && !sel.isEmpty()) {{
              const lines = Math.abs(sel.endLineNumber - sel.startLineNumber) + 1;
              const chars = model ? model.getValueLengthInRange(sel) : 0;
              cursor +=
                lines > 1
                  ? " (" + lines + " selected)"
                  : " (" + chars + " selected)";
            }}
          }}
          const opts = editor.getOptions();
          const insertSpaces = opts.get(monaco.editor.EditorOption.insertSpaces);
          const tabSize = opts.get(monaco.editor.EditorOption.tabSize);
          post({{
            type: "editor_status",
            cursor,
            indent: insertSpaces ? "Spaces: " + tabSize : "Tab Size: " + tabSize,
            encoding: "UTF-8",
            eol: model && model.getEOL() === "\\r\\n" ? "CRLF" : "LF",
            language: languageLabel(model),
          }});
        }});
      }}
      window.updateEditorStatus = updateEditorStatus;

      window.editorSetBusy = function (busy) {{
        runBusy = !!busy;
        renderTabBar();
      }};

      window.editorSetOutputVisible = function (visible) {{
        const active = !!visible;
        outputToggle.classList.toggle("active", active);
        outputToggle.setAttribute("aria-pressed", String(active));
        outputToggle.title = active ? "Hide Output Pane" : "Show Output Pane";
      }};

      function requestRun(tabId) {{
        if (runBusy) return;
        if (tabId && tabId !== activeTabId) switchTab(tabId);
        post({{ type: "run" }});
      }}

      editor.onDidChangeModelContent(() => {{
        renderTabBar();
        updateEditorStatus();
      }});
      editor.onDidChangeCursorPosition(() => updateEditorStatus());
      editor.onDidChangeCursorSelection(() => updateEditorStatus());
      editor.onDidChangeModel(() => updateEditorStatus());

      editor.addCommand(
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter,
        () => requestRun(),
      );
      editor.addCommand(
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
        () => post({{ type: "save" }}),
      );
      editor.addCommand(
        monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyS,
        () => post({{ type: "save_as" }}),
      );
      editor.addCommand(
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyT,
        () => window.editorNewTab(),
      );
      editor.addCommand(
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyO,
        () => post({{ type: "open" }}),
      );
      editor.addCommand(
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyW,
        () => window.editorCloseActiveTab(),
      );

      document.getElementById("new-tab").addEventListener("click", () => {{
        window.editorNewTab();
      }});
      outputToggle.addEventListener("click", () => {{
        post({{ type: "toggle_output" }});
      }});

      if (INITIAL_TABS.length === 0) {{
        openTab("untitled.py", "");
      }} else {{
        for (const spec of INITIAL_TABS) {{
          openTab(spec.title, spec.content || "", spec.path || null);
        }}
        switchTab(tabs[0].id);
      }}

      updateEditorStatus();
      post({{ type: "ready" }});
    }});
  </script>
</body>
</html>
"""


def _status_html() -> str:
    """Independent thin status-bar WebView (full window width)."""
    return """\
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <style>
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      height: 100%;
      overflow: hidden;
      background: #181818;
      color: #cccccc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 12px;
      user-select: none;
    }
    #bar {
      display: flex;
      align-items: stretch;
      justify-content: space-between;
      height: 100%;
      border-top: 1px solid #2b2b2b;
    }
    #left, #right {
      display: flex;
      align-items: stretch;
      min-width: 0;
    }
    #left { flex: 1; padding-left: 8px; }
    #message {
      display: flex;
      align-items: center;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .item {
      display: inline-flex;
      align-items: center;
      padding: 0 8px;
      border: none;
      background: transparent;
      color: inherit;
      font: inherit;
      white-space: nowrap;
      cursor: pointer;
    }
    .item:hover {
      background: rgba(255, 255, 255, 0.08);
      color: #ffffff;
    }
    html[data-theme="light"] body {
      background: #f3f3f3;
      color: #616161;
    }
    html[data-theme="light"] #bar {
      border-top-color: #e0e0e0;
    }
    html[data-theme="light"] .item:hover {
      background: rgba(0, 0, 0, 0.06);
      color: #333333;
    }
  </style>
</head>
<body>
  <div id="bar">
    <div id="left"><span id="message"></span></div>
    <div id="right">
      <button class="item" type="button" data-item="cursor" title="Go to Line"
              id="cursor">Ln 1, Col 1</button>
      <button class="item" type="button" data-item="indent" title="Select Indentation"
              id="indent">Spaces: 4</button>
      <button class="item" type="button" data-item="encoding" title="Select Encoding"
              id="encoding">UTF-8</button>
      <button class="item" type="button" data-item="eol"
              title="Select End of Line Sequence"
              id="eol">LF</button>
      <button class="item" type="button" data-item="language"
              title="Select Language Mode"
              id="language">Python</button>
    </div>
  </div>
  <script>
    function post(msg) {
      if (window.ipc) window.ipc.postMessage(JSON.stringify(msg));
    }

    window.setStatusMessage = function (text) {
      document.getElementById("message").textContent = text || "";
    };

    window.setStatusItems = function (items) {
      if (!items) return;
      if (items.cursor != null)
        document.getElementById("cursor").textContent = items.cursor;
      if (items.indent != null)
        document.getElementById("indent").textContent = items.indent;
      if (items.encoding != null)
        document.getElementById("encoding").textContent = items.encoding;
      if (items.eol != null)
        document.getElementById("eol").textContent = items.eol;
      if (items.language != null)
        document.getElementById("language").textContent = items.language;
    };

    window.setStatusTheme = function (mode) {
      document.documentElement.setAttribute(
        "data-theme",
        mode === "light" ? "light" : "dark",
      );
    };

    document.getElementById("right").addEventListener("click", (event) => {
      const btn = event.target.closest("[data-item]");
      if (!btn) return;
      post({
        type: "status_click",
        item: btn.getAttribute("data-item"),
        value: btn.textContent || "",
      });
    });

    post({ type: "status_ready" });
  </script>
</body>
</html>
"""


def _set_macos_app_name(name: str) -> None:
    """Rename the macOS application menu (the bold entry Tk labels ``Python``).

    On macOS the first menu-bar item is auto-generated from the process's
    ``CFBundleName``. For an unbundled Python that is ``Python``. Overriding it
    before Tk builds the menu makes it show *name* instead. No-op elsewhere.
    """
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is not None:
            info["CFBundleName"] = name
    except Exception:
        pass


class Playground:
    def __init__(self) -> None:
        _set_macos_app_name("tkipw")
        # Before the first Tk window: awareness keeps Matplotlib TkAgg sized
        # correctly. WebView bounds use tkwry Physical pixels on Windows.
        # Embed-safe: do not call tkface.win.dpi(root).
        tkface.win.enable_dpi_awareness()
        self.root = tk.Tk()
        # Hide the window until the output App has been booted and the pane
        # re-hidden. That way we can map the pane for WebView create without a
        # visible open/close flash, and the first Run is not stalled on boot.
        self._startup_cloaked = False
        try:
            self.root.attributes("-alpha", 0.0)
            self._startup_cloaked = True
        except tk.TclError:
            pass
        self.root.title("tkipw · playground")
        self.root.geometry(
            f"{tkface.win.design_to_physical(1100)}x"
            f"{tkface.win.design_to_physical(700)}"
        )
        self.root.minsize(
            tkface.win.design_to_physical(800),
            tkface.win.design_to_physical(500),
        )
        self._minimap_var = tk.BooleanVar(self.root, value=True)
        self._word_wrap_var = tk.BooleanVar(self.root, value=True)
        self._dark_editor_var = tk.BooleanVar(self.root, value=True)
        self._dark_output_var = tk.BooleanVar(self.root, value=True)
        # Start with the editor at full width. Inline Run reveals the pane.
        self._output_visible_var = tk.BooleanVar(self.root, value=False)
        self._display_mode_var = tk.StringVar(self.root, value="inline")
        self._save_dialog_active = False
        self._editor_ready = False
        self._status_ready = False
        self._app_webview_ready = False
        self._busy = False
        self._stop_requested = False
        self._user_tk_roots: list[tk.Misc] = []
        self._status_epoch = 0
        self._run_status_epoch = 0
        self._editor_frame: tk.Frame | None = None
        self._paned: tk.PanedWindow | None = None
        self._output_frame: tk.Frame | None = None
        self._status_frame: tk.Frame | None = None
        self._build_menubar()

        # Independent status WebView — full window width under the paned area.
        self._status_frame = tk.Frame(
            self.root, height=tkface.win.design_to_physical(22), bg="#181818"
        )
        self._status_frame.pack(side="bottom", fill="x")
        self._status_frame.pack_propagate(False)

        paned = tk.PanedWindow(
            self.root,
            orient="horizontal",
            sashwidth=tkface.win.design_to_physical(6),
            sashrelief="flat",
            bd=0,
            bg="#404040",
        )
        paned.pack(side="top", fill="both", expand=True)

        left = tk.Frame(paned, bg="#1e1e1e")
        right = tk.Frame(paned)
        self._editor_frame = left
        self._paned = paned
        self._output_frame = right
        pane_min = tkface.win.design_to_physical(280)
        paned.add(left, minsize=pane_min, stretch="always")
        paned.add(right, minsize=pane_min, stretch="always")
        # Start with the editor at full width (output pane hidden).
        paned.paneconfigure(right, hide=True)

        left.pack_propagate(False)
        right.pack_propagate(False)

        self._editor_initial_tabs = [
            {"title": "README.md", "content": README_SAMPLE.lstrip("\n")},
            *[
                {"title": f"{name}.py", "content": code.lstrip("\n")}
                for name, code in SAMPLES.items()
            ],
        ]
        # One WebView2 at a time on Windows: status → editor → output App.
        self._editor: WebView | None = None
        self._status = WebView(
            self._status_frame,
            html=_status_html(),
            ipc_handler=self._on_status_ipc,
        )

        self._results = StackedOutput()
        self.app: App | None = None
        self._app_create_scheduled = False
        self._editor_create_scheduled = False
        self._layout_sync_enabled = False

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._install_shortcuts()
        self.root.after(0, self._install_webview_resize_hooks)

    def _install_shortcuts(self) -> None:
        wrap = EditorShortcutBindings.wrap
        replace_handler = wrap(self._replace)
        save_handler = wrap(self._save)
        save_as_handler = wrap(self._save_as)
        open_handler = wrap(self._open_file)
        EditorShortcutBindings.register_virtual_events(self.root)
        self.root.bind("<<Replace>>", replace_handler, add="+")
        EditorShortcutBindings.install(
            self.root,
            [
                (EditorShortcutBindings.UNDO, wrap(self._undo)),
                (EditorShortcutBindings.REDO, wrap(self._redo)),
                (EditorShortcutBindings.CUT, wrap(self._cut)),
                (EditorShortcutBindings.COPY, wrap(self._copy)),
                (EditorShortcutBindings.PASTE, wrap(self._paste)),
                (EditorShortcutBindings.FIND, wrap(self._find)),
                (EditorShortcutBindings.REPLACE, replace_handler),
                (EditorShortcutBindings.NEW_TAB, wrap(self._new_tab)),
                (EditorShortcutBindings.OPEN, open_handler),
                (EditorShortcutBindings.SAVE, save_handler),
                (EditorShortcutBindings.SAVE_AS, save_as_handler),
                (EditorShortcutBindings.CLOSE_TAB, wrap(self._close_tab)),
            ],
            global_bindings=[
                (EditorShortcutBindings.REPLACE, replace_handler),
                (EditorShortcutBindings.OPEN, open_handler),
                (EditorShortcutBindings.SAVE, save_handler),
                (EditorShortcutBindings.SAVE_AS, save_as_handler),
            ],
        )

    def _build_menubar(self) -> None:
        mod = "Command" if sys.platform == "darwin" else "Ctrl"
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(
            label="New Tab",
            accelerator=f"{mod}-T",
            command=self._new_tab,
        )
        file_menu.add_command(
            label="Open…",
            accelerator=f"{mod}-O",
            command=self._open_file,
        )
        file_menu.add_command(
            label="Close Tab",
            accelerator=f"{mod}-W",
            command=self._close_tab,
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Save",
            accelerator=f"{mod}-S",
            command=self._save,
        )
        file_menu.add_command(
            label="Save As…",
            accelerator=f"{mod}-Shift-S",
            command=self._save_as,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_close)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(
            label="Undo",
            accelerator=f"{mod}-Z",
            command=self._undo,
        )
        edit_menu.add_command(
            label="Redo",
            accelerator=("Command-Shift-Z" if sys.platform == "darwin" else "Ctrl-Y"),
            command=self._redo,
        )
        edit_menu.add_separator()
        edit_menu.add_command(
            label="Cut",
            accelerator=f"{mod}-X",
            command=self._cut,
        )
        edit_menu.add_command(
            label="Copy",
            accelerator=f"{mod}-C",
            command=self._copy,
        )
        edit_menu.add_command(
            label="Paste",
            accelerator=f"{mod}-V",
            command=self._paste,
        )
        edit_menu.add_separator()
        edit_menu.add_command(
            label="Find",
            accelerator=f"{mod}-F",
            command=self._find,
        )
        edit_menu.add_command(
            label="Replace",
            accelerator=("Command-Option-F" if sys.platform == "darwin" else "Ctrl-H"),
            command=self._replace,
        )

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_checkbutton(
            label="Output Pane",
            variable=self._output_visible_var,
            command=self._toggle_output_pane,
        )
        view_menu.add_separator()
        display_menu = tk.Menu(view_menu, tearoff=False)
        display_menu.add_radiobutton(
            label="Inline",
            value="inline",
            variable=self._display_mode_var,
            command=self._apply_display_mode,
        )
        display_menu.add_radiobutton(
            label="Window",
            value="window",
            variable=self._display_mode_var,
            command=self._apply_display_mode,
        )
        view_menu.add_cascade(label="Display Mode", menu=display_menu)
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="Minimap",
            variable=self._minimap_var,
            command=self._apply_editor_options,
        )
        view_menu.add_checkbutton(
            label="Word Wrap",
            variable=self._word_wrap_var,
            command=self._apply_editor_options,
        )
        view_menu.add_checkbutton(
            label="Dark Editor",
            variable=self._dark_editor_var,
            command=self._apply_editor_options,
        )
        view_menu.add_checkbutton(
            label="Dark Output Pane",
            variable=self._dark_output_var,
            command=self._apply_output_theme,
        )

        run_menu = tk.Menu(menubar, tearoff=False)
        run_menu.add_command(
            label="Run Active Tab",
            accelerator=f"{mod}-Return",
            command=self._on_run,
        )

        menubar.add_cascade(label="File", menu=file_menu)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        menubar.add_cascade(label="View", menu=view_menu)
        menubar.add_cascade(label="Run", menu=run_menu)
        self.root.configure(menu=menubar)

    def _new_tab(self) -> None:
        self._eval_editor("window.editorNewTab && window.editorNewTab();")

    def _close_tab(self) -> None:
        self._eval_editor(
            "window.editorCloseActiveTab && window.editorCloseActiveTab();"
        )

    def _undo(self) -> None:
        self._eval_editor("window.editorUndo && window.editorUndo();")

    def _redo(self) -> None:
        self._eval_editor("window.editorRedo && window.editorRedo();")

    def _cut(self) -> None:
        self._eval_editor("window.editorCut && window.editorCut();")

    def _copy(self) -> None:
        self._eval_editor("window.editorCopy && window.editorCopy();")

    def _paste(self) -> None:
        if not self._editor_ready or self._editor is None:
            return
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return
        self._editor.focus()
        self._editor.eval_js(f"window.editorPasteText({json.dumps(text)});")

    def _find(self) -> None:
        self._eval_editor("window.editorFind && window.editorFind();")

    def _replace(self) -> None:
        self._eval_editor("window.editorReplace && window.editorReplace();")

    def _toggle_output_pane(self) -> None:
        self._set_output_visible(self._output_visible_var.get())

    def _apply_display_mode(self) -> None:
        mode = self._display_mode_var.get()
        if self.app is None:
            # Window mode needs the App/bridge even with the pane hidden.
            if mode == "window":
                self._maybe_create_output_app(force=True)
            return
        self.app.set_display_mode(mode)
        # Inline needs the result pane; window mode gives the editor full width.
        self._set_output_visible(mode == "inline")
        self._set_status(f"display · {mode}")

    def _set_output_visible(
        self, visible: bool, *, flush: bool = True, sync_bounds: bool = True
    ) -> None:
        self._output_visible_var.set(visible)
        self._eval_editor(
            "window.editorSetOutputVisible && "
            f"window.editorSetOutputVisible({json.dumps(visible)});"
        )
        paned = self._paned
        output_frame = self._output_frame
        if paned is None or output_frame is None:
            return

        # Prefer pane hide over forget: native WKWebView overlays do not
        # follow forget/unmap cleanly (same approach as tkwry markdown_demo).
        paned.paneconfigure(output_frame, hide=not visible)
        # Never update_idletasks here: it re-enters WebView2 create on Windows.
        del flush
        if visible:
            # First show is when we boot the output App (avoids startup flash).
            self._maybe_create_output_app()
        if not sync_bounds or not self._layout_sync_enabled:
            return
        if visible:
            self._output_sash_ratio = 0.5
            self._place_output_sash()
            self._schedule_webview_bounds_sync(passes=2)

            def place_sash() -> None:
                self._place_output_sash()
                self._schedule_webview_bounds_sync(passes=2)

            self.root.after(50, place_sash)
        else:
            self._schedule_webview_bounds_sync(passes=1)

    def _reveal_after_startup(self) -> None:
        """Show the main window once startup WebView boot is finished."""
        if not self._startup_cloaked:
            return
        self._startup_cloaked = False
        try:
            self.root.attributes("-alpha", 1.0)
        except tk.TclError:
            pass

    def _on_app_webview_ready(self) -> None:
        self._app_webview_ready = True
        self._layout_sync_enabled = True
        if self._output_visible_var.get():
            self._place_output_sash()
        self._schedule_webview_bounds_sync(passes=2)
        self._reveal_after_startup()

    def _maybe_create_output_app(self, *, force: bool = False) -> None:
        """Create the output App once editor/status are up.

        Prefer an early *force* boot (pane mapped under the startup cloak) so
        the first Run does not wait on WebView creation. A later show of the
        pane is then only a layout change.
        """
        if self.app is not None or self._app_create_scheduled:
            return
        if not (self._status_ready and self._editor_ready):
            return
        if not force and not self._output_visible_var.get():
            return
        self._app_create_scheduled = True
        # Short gap after editor create; keep this small — it is on the
        # critical path for first-result latency when not pre-booted.
        self.root.after(50, lambda: self._create_output_app(force=force))

    def _create_editor_webview(self) -> None:
        if self._editor is not None:
            return
        left = self._editor_frame
        if left is None:
            return
        self._editor = WebView(
            left,
            html=_editor_html(self._editor_initial_tabs),
            ipc_handler=self._on_editor_ipc,
        )

    def _create_output_app(self, *, force: bool = False) -> None:
        if self.app is not None:
            return
        right = self._output_frame
        paned = self._paned
        if right is None or paned is None:
            return
        # WebView needs a mapped non-zero parent. Map for boot; re-hide after
        # ready when the user still wants the pane closed.
        restore_hidden = not self._output_visible_var.get()
        if restore_hidden or force or self._output_visible_var.get():
            paned.paneconfigure(right, hide=False)

        def body() -> None:
            if self.app is not None:
                return
            theme = "dark" if self._dark_output_var.get() else "light"
            mode = self._display_mode_var.get()
            if mode not in ("inline", "window"):
                mode = "inline"
            self.app = App(
                parent=right,
                title="tkipw · playground",
                display_mode=mode,
                theme=theme,
            )
            self.app.display(self._results)

            def on_ready() -> None:
                if restore_hidden and not self._output_visible_var.get():
                    paned.paneconfigure(right, hide=True)
                self._on_app_webview_ready()

            self.app.when_ready(on_ready)

        # Let Tk settle geometry without update_idletasks (WebView2 re-entrancy).
        self.root.after(50, body)

    def _schedule_webview_bounds_sync(self, *, passes: int = 1) -> None:
        if not self._layout_sync_enabled:
            return

        def _run(remaining: int) -> None:
            self._sync_webview_bounds()
            if remaining > 1:
                self.root.after(50, lambda: _run(remaining - 1))

        self.root.after(50, lambda: _run(passes))

    def _install_webview_resize_hooks(self) -> None:
        self._bounds_sync_after_id: str | None = None
        self._output_sash_ratio = 0.5

        def _on_configure(event: tk.Event | None = None) -> None:
            if not self._layout_sync_enabled:
                return
            # Ignore bubbled Configure from nested children — only act on the
            # widgets we bound (root / paned / panes / status).
            if event is not None and event.widget not in {
                self.root,
                self._paned,
                self._editor_frame,
                self._output_frame,
                self._status_frame,
            }:
                return
            if self._bounds_sync_after_id is not None:
                try:
                    self.root.after_cancel(self._bounds_sync_after_id)
                except tk.TclError:
                    pass
            self._bounds_sync_after_id = self.root.after(50, self._on_layout_settle)

        for widget in (
            self.root,
            self._paned,
            self._editor_frame,
            self._output_frame,
            self._status_frame,
        ):
            if widget is not None:
                widget.bind("<Configure>", _on_configure, add="+")

    def _on_layout_settle(self) -> None:
        self._bounds_sync_after_id = None
        if not self._layout_sync_enabled:
            return
        if self._output_visible_var.get():
            self._place_output_sash()
        self._sync_webview_bounds()

    def _place_output_sash(self) -> None:
        """Keep the editor/output split as a ratio of the current paned width.

        ``sash_place`` is absolute pixels; without re-placing on resize the sash
        stays at the width from the last show (often the maximized width).
        """
        paned = self._paned
        if paned is None or not self._output_visible_var.get():
            return
        width = paned.winfo_width()
        if width <= 1 or len(paned.panes()) < 2:
            return
        ratio = getattr(self, "_output_sash_ratio", 0.5)
        ratio = min(max(float(ratio), 0.2), 0.8)
        paned.sash_place(0, int(width * ratio), 0)

    def _sync_webview_bounds(self) -> None:
        webs = [
            getattr(self, "_editor", None),
            getattr(self, "_status", None),
        ]
        app = getattr(self, "app", None)
        app_web = getattr(app, "webview", None) if app is not None else None
        if app_web is not None and self._app_webview_ready:
            webs.append(app_web)
        for web in webs:
            if web is None:
                continue
            sync = getattr(web, "sync_bounds", None)
            if callable(sync):
                try:
                    sync()
                except Exception:
                    pass

    def _apply_editor_options(self) -> None:
        minimap = json.dumps(self._minimap_var.get())
        word_wrap = json.dumps(self._word_wrap_var.get())
        mode = "dark" if self._dark_editor_var.get() else "light"
        if self._editor_frame is not None:
            self._editor_frame.configure(bg="#1e1e1e" if mode == "dark" else "#ffffff")
        if self._status_frame is not None:
            self._status_frame.configure(bg="#181818" if mode == "dark" else "#f3f3f3")
        self._eval_status(
            f"window.setStatusTheme && window.setStatusTheme({json.dumps(mode)});"
        )
        self._eval_editor(
            f"window.editorSetMinimap && window.editorSetMinimap({minimap});"
            f"window.editorSetWordWrap && window.editorSetWordWrap({word_wrap});"
            f"window.editorSetTheme && window.editorSetTheme({json.dumps(mode)});"
        )

    def _apply_output_theme(self) -> None:
        mode = "dark" if self._dark_output_var.get() else "light"
        if self.app is None:
            return
        try:
            self.app.set_theme(mode)
        except Exception:
            pass

    def _open_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Open File",
            filetypes=[
                ("Supported", "*.py *.md *.markdown"),
                ("Python", "*.py"),
                ("Markdown", "*.md *.markdown"),
                ("All Files", "*"),
            ],
        )
        if not path:
            return
        file_path = Path(path)
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Open", str(exc), parent=self.root)
            return
        self._eval_editor(
            "window.editorNewTab("
            f"{json.dumps(file_path.name)},"
            f"{json.dumps(content)},"
            f"{json.dumps(str(file_path))}"
            ");"
        )

    def _save(self) -> None:
        self._save_active_tab(save_as=False)

    def _save_as(self) -> None:
        self._save_active_tab(save_as=True)

    def _save_active_tab(self, *, save_as: bool) -> None:
        if self._save_dialog_active or not self._editor_ready or self._editor is None:
            return
        self._save_dialog_active = True

        def on_info(result: str) -> None:
            try:
                info = _parse_eval_json_object(result)
                if not info:
                    return
                title = str(info.get("title") or "untitled.py")
                existing = info.get("path")
                path = str(existing) if existing else ""
                if save_as or not path:
                    markdown_file = title.lower().endswith((".md", ".markdown"))
                    chosen = filedialog.asksaveasfilename(
                        parent=self.root,
                        title="Save As" if save_as else "Save",
                        initialfile=title,
                        defaultextension=".md" if markdown_file else ".py",
                        filetypes=[
                            ("Markdown", "*.md *.markdown"),
                            ("Python", "*.py"),
                            ("All Files", "*"),
                        ],
                    )
                    if not chosen:
                        return
                    path = chosen
                file_path = Path(path)
                try:
                    file_path.write_text(
                        str(info.get("content") or ""),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    messagebox.showerror("Save", str(exc), parent=self.root)
                    return
                self._eval_editor(
                    "window.editorMarkSaved("
                    f"{json.dumps(str(file_path))},"
                    f"{json.dumps(file_path.name)}"
                    ");"
                )
                self._set_status(f"saved · {file_path.name}")
            finally:
                self._save_dialog_active = False

        def on_error(_exc: BaseException) -> None:
            self._save_dialog_active = False

        self._editor.eval_js_with_callback(
            "window.editorGetActiveTabInfo && window.editorGetActiveTabInfo()",
            on_info,
            on_error=on_error,
        )

    def _on_close(self) -> None:
        self._close_matplotlib_figures()
        if self._editor is not None:
            try:
                self._editor.destroy()
            except Exception:
                pass
        try:
            self._status.destroy()
        except Exception:
            pass
        if self.app is not None:
            try:
                self.app.destroy()
            except Exception:
                pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    @staticmethod
    def _close_matplotlib_figures() -> None:
        """Close native TkAgg windows before tearing down the Playground root."""
        try:
            from matplotlib import pyplot as plt

            plt.close("all")
        except Exception:
            pass

    def _on_status_ipc(self, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        kind = data.get("type")
        if kind == "status_ready":
            self._status_ready = True
            mode = "dark" if self._dark_editor_var.get() else "light"
            self._eval_status(
                f"window.setStatusTheme && window.setStatusTheme({json.dumps(mode)});"
            )
            if not self._editor_create_scheduled:
                self._editor_create_scheduled = True
                self.root.after(150, self._create_editor_webview)
        elif kind == "status_click":
            # Reserved for future status-item menus (language / EOL / …).
            return

    def _on_editor_ipc(self, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        kind = data.get("type")
        if kind == "ready":
            self._editor_ready = True
            self._apply_editor_options()
            self._set_output_visible(
                self._output_visible_var.get(), flush=False, sync_bounds=False
            )
            # When the window is alpha-cloaked, pre-boot the output App now
            # (pane map is invisible). Otherwise wait until the pane is shown
            # so we do not flash it — Run still starts without waiting on ready.
            self._maybe_create_output_app(force=self._startup_cloaked)
            if self._startup_cloaked:
                # Safety: never stay invisible forever if App boot hangs.
                self.root.after(8000, self._reveal_after_startup)
        elif kind == "tab":
            # Invalidate sticky run/save messages when the active tab changes.
            self._status_epoch += 1
            self._set_status("")
        elif kind == "editor_status":
            payload = {
                "cursor": str(data.get("cursor") or "Ln 1, Col 1"),
                "indent": str(data.get("indent") or "Spaces: 4"),
                "encoding": str(data.get("encoding") or "UTF-8"),
                "eol": str(data.get("eol") or "LF"),
                "language": str(data.get("language") or "Python"),
            }
            self._eval_status(
                "window.setStatusItems && window.setStatusItems("
                f"{json.dumps(payload)}"
                ");"
            )
        elif kind == "run":
            self._on_run()
        elif kind == "stop":
            self._on_stop()
        elif kind == "open":
            self._open_file()
        elif kind == "save":
            self._save()
        elif kind == "save_as":
            self._save_as()
        elif kind == "toggle_output":
            self._set_output_visible(not self._output_visible_var.get())

    def _eval_editor(self, script: str) -> None:
        if not self._editor_ready or self._editor is None:
            return
        self._editor.focus()

        def run() -> None:
            if self._editor is None:
                return
            try:
                self._editor.eval_js(script)
            except Exception:
                pass

        self.root.after_idle(run)

    def _eval_status(self, script: str) -> None:
        if not self._status_ready:
            return
        try:
            self._status.eval_js(script)
        except Exception:
            pass

    def _set_status(self, text: str) -> None:
        self._eval_status(
            "window.setStatusMessage && "
            f"window.setStatusMessage({json.dumps(text or '')});"
        )

    def _set_busy(self, busy: bool) -> None:
        self._eval_editor(f"window.editorSetBusy({json.dumps(busy)});")

    def _set_run_state(self, *, busy: bool, status: str | None = None) -> None:
        """Update busy glyph and optional left-side status message."""
        self._set_busy(busy)
        if status is not None:
            self._set_status(status)

    def _on_run(self) -> None:
        if self._busy or not self._editor_ready or self._editor is None:
            return
        mode = self._display_mode_var.get()
        inline = mode != "window"
        if inline:
            if not self._output_visible_var.get():
                self._set_output_visible(True)
            else:
                self._maybe_create_output_app()
        else:
            self._maybe_create_output_app(force=True)
        self._busy = True
        self._stop_requested = False
        self._run_status_epoch = self._status_epoch
        self._set_run_state(busy=True, status="running…")

        def start_fetch() -> None:
            if self._stop_requested:
                self._finish("stopped")
                return

            def on_info(result: str) -> None:
                info = _parse_eval_json_object(result)
                if not info:
                    self._finish("no active tab")
                    return
                code = str(info.get("content", ""))
                title = str(info.get("title", "<playground>"))
                # Main thread: VTK/Cocoa + pyvista export_html/trame require it.
                if title.lower().endswith((".md", ".markdown")):
                    self.root.after(0, lambda: self._render_markdown(code, title))
                else:
                    self.root.after(0, lambda: self._exec_code(code, title))

            def on_error(_exc: BaseException) -> None:
                self._finish("editor eval failed")

            assert self._editor is not None
            self._editor.eval_js_with_callback(
                "window.editorGetActiveTabInfo && window.editorGetActiveTabInfo()",
                on_info,
                on_error=on_error,
            )

        def wait_app_instance() -> None:
            """Wait only until App() exists; display traffic queues until ready."""
            if self._stop_requested:
                self._finish("stopped")
                return
            if self.app is None:
                self.root.after(20, wait_app_instance)
                return
            start_fetch()

        # Do not block on WebView ready — outbound messages queue and flush on
        # ready. Blocking here made the first Run feel much slower than before.
        if self.app is None:
            self._set_status("starting output…")
            wait_app_instance()
            return
        start_fetch()

    def _on_stop(self) -> None:
        if not self._busy:
            return
        self._stop_requested = True
        self._set_status("stopping…")
        self._quit_user_tk_windows()

    def _quit_user_tk_windows(self) -> None:
        """Unblock ``wait_window`` from user scripts without exiting Playground.

        Important: do **not** call ``Misc.quit()``. That ends the interpreter's
        main ``mainloop`` and closes the whole Playground app.
        """
        for window in list(getattr(self, "_user_tk_roots", [])):
            try:
                if window.winfo_exists():
                    window.destroy()
            except Exception:
                pass

    @contextmanager
    def _tkinter_run_sandbox(self) -> Iterator[None]:
        """Make user ``tk.Tk().mainloop()`` stoppable inside the Playground.

        A second real ``Tk()`` would nest a separate event loop and swallow the
        Stop button (WebView IPC lives on the Playground root). Redirect ``Tk``
        to a ``Toplevel`` under this app and run an interruptible ``mainloop``.
        """
        import tkinter as tkinter_mod

        self._user_tk_roots = []
        real_tk = tkinter_mod.Tk
        real_mainloop = tkinter_mod.Misc.mainloop
        previous_default = getattr(tkinter_mod, "_default_root", None)
        playground = self

        class RedirectedTk(tkinter_mod.Toplevel):
            def __init__(
                self,
                screenName=None,
                baseName=None,
                className="Tk",
                useTk=True,
                sync=False,
                use=None,
            ):
                del screenName, baseName, useTk, sync, use
                super().__init__(playground.root)
                title = "tk" if className in (None, "Tk") else str(className)
                try:
                    self.title(title)
                except tk.TclError:
                    pass
                playground._user_tk_roots.append(self)
                if getattr(tkinter_mod, "_support_default_root", True):
                    tkinter_mod._default_root = self

            def mainloop(self, n: int = 0):
                del n
                playground._run_interruptible_mainloop(self)

        def patched_mainloop(window, n: int = 0):
            del n
            playground._run_interruptible_mainloop(window)

        tkinter_mod.Tk = RedirectedTk  # type: ignore[misc, assignment]
        tkinter_mod.Misc.mainloop = patched_mainloop  # type: ignore[method-assign]
        try:
            yield
        finally:
            tkinter_mod.Tk = real_tk  # type: ignore[misc]
            tkinter_mod.Misc.mainloop = real_mainloop  # type: ignore[method-assign]
            if getattr(tkinter_mod, "_support_default_root", True):
                tkinter_mod._default_root = previous_default
            self._quit_user_tk_windows()
            self._user_tk_roots = []

    def _run_interruptible_mainloop(self, window: tk.Misc) -> None:
        """Block like ``mainloop`` until the window closes or Stop is pressed.

        User ``Tk`` windows are actually ``Toplevel``s under the Playground root.
        A real ``mainloop()`` would keep running after the child is closed with
        the window X, because the Playground root is still alive. ``wait_window``
        returns when the child is destroyed, while still dispatching Playground
        / WebView events (including Stop).
        """

        def close_window() -> None:
            try:
                if window.winfo_exists():
                    window.destroy()
            except tk.TclError:
                pass

        def poll() -> None:
            if self._stop_requested:
                close_window()
                return
            try:
                if window.winfo_exists():
                    window.after(50, poll)
            except tk.TclError:
                return

        try:
            window.protocol("WM_DELETE_WINDOW", close_window)
        except tk.TclError:
            pass

        poll()
        try:
            if window.winfo_exists():
                # Process events on the Playground root until *window* goes away.
                self.root.wait_window(window)
        except tk.TclError:
            pass

        if self._stop_requested:
            raise _ExecutionStopped

    def _finish(self, status: str | None = None) -> None:
        self._busy = False
        self._stop_requested = False
        message = status
        epoch = self._run_status_epoch

        def apply() -> None:
            # Skip if a newer Run already started (idle / delayed callbacks).
            if self._busy:
                return
            # Always clear the busy glyph; only keep the message if the user
            # has not switched tabs since this run started.
            if epoch == self._status_epoch:
                self._set_run_state(busy=False, status=message)
            else:
                self._set_busy(False)

        # Defer past widget delivery / eval_js flood from display().
        self.root.after_idle(apply)
        # Backup: WebView can still be flushing widget scripts on idle.
        self.root.after(80, apply)

    def _exec_code(self, code: str, filename: str) -> None:
        if self.app is None:
            self._finish("output app not ready")
            return
        status = "done"
        inline = self.app.display_mode == "inline"
        stream_output = None if inline else out.Output()
        target = self._results if inline else out.stream_context(stream_output)
        with target:
            try:
                if inline:
                    out.clear_output(wait=False)
                ns = {
                    "__name__": "__main__",
                    "display": out.display,
                    "clear_output": out.clear_output,
                }
                with out.capture_stdio(), self._tkinter_run_sandbox():
                    previous_trace = sys.gettrace()
                    next_pump = time.monotonic()

                    def execution_trace(frame, event, arg):
                        del event, arg
                        nonlocal next_pump

                        def stop_here() -> bool:
                            # Only interrupt user code. Raising from Playground /
                            # tkwry / Tk callbacks surfaces as
                            # "Exception in Tkinter callback".
                            return frame.f_code.co_filename == filename

                        if self._stop_requested and stop_here():
                            raise _ExecutionStopped
                        now = time.monotonic()
                        if now >= next_pump:
                            next_pump = now + 0.03
                            try:
                                # Keep Tk/WebView IPC responsive while user
                                # Python runs synchronously on the main thread.
                                self.root.update_idletasks()
                                self.root.update()
                            except tk.TclError:
                                self._stop_requested = True
                            if self._stop_requested and stop_here():
                                raise _ExecutionStopped
                        return execution_trace

                    try:
                        sys.settrace(execution_trace)
                        exec(compile(code, filename, "exec"), ns, ns)
                    finally:
                        sys.settrace(previous_trace)
            except _ExecutionStopped:
                status = "stopped"
                out.display_error("Execution stopped by user.", kind="stderr")
            except Exception:
                status = "error"
                out.display_error(traceback.format_exc())
        if stream_output is not None and stream_output.children:
            # stdout/stderr/errors/logging share one window per Run. Ordinary
            # display() calls above still opened their own windows.
            out.display(stream_output)
        self._finish(f"{status} · {filename}")

    def _render_markdown(self, source: str, filename: str) -> None:
        if self.app is None:
            self._finish("output app not ready")
            return
        try:
            if self.app.display_mode == "inline":
                with self._results:
                    out.clear_output(wait=False)
                    out.display(Markdown(source))
            else:
                out.display(Markdown(source))
        except Exception:
            out.display_error(traceback.format_exc())
            self._finish(f"error · {filename}")
            return
        self._finish(f"done · {filename}")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    Playground().run()
