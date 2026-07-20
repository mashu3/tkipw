# tkipw

[![License: MIT](https://img.shields.io/pypi/l/tkipw)](https://opensource.org/licenses/MIT)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/tkipw)](https://pypi.org/project/tkipw)
[![GitHub Release](https://img.shields.io/github/v/release/mashu3/tkipw?color=orange)](https://github.com/mashu3/tkipw/releases)
[![PyPI Version](https://img.shields.io/pypi/v/tkipw?color=yellow)](https://pypi.org/project/tkipw/)
[![Downloads](https://static.pepy.tech/badge/tkipw)](https://pepy.tech/project/tkipw)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-red)](https://github.com/mashu3/tkipw)
[![CI](https://github.com/mashu3/tkipw/actions/workflows/ci.yml/badge.svg)](https://github.com/mashu3/tkipw/actions/workflows/ci.yml)

**Run ipywidgets / anywidget on the desktop — no Jupyter Notebook, no browser tab.**

tkipw is a small runtime that hosts [ipywidgets](https://github.com/jupyter-widgets/ipywidgets) and [anywidget](https://github.com/manzt/anywidget) inside a real system WebView embedded in a Tkinter window, powered by [**tkwry**](https://github.com/mashu3/tkwry).

```
Python → ipywidgets API → Comm (tkipw) → tkwry IPC → JS Widget Manager → DOM
```

> **Alpha** — APIs and behavior may change. Not recommended for production yet.

---

## 📖 Overview

Jupyter widgets normally need a notebook kernel and a browser. tkipw drops both:
your widgets run in the same process as your Python code and render in a native
WebView that lives *inside* a Tk `Frame` (via tkwry's child-window embedding).

* **No notebook** — plain `python your_script.py`
* **Real widgets** — the official `@jupyter-widgets/html-manager` runs the same controls you use in Jupyter
* **anywidget** — bundled front end (e.g. Plotly `FigureWidget`)
* **ipyleaflet** — bundled live Leaflet widget module (Python ↔ map trait updates)
* **Notebook-like display** — `display()`, `clear_output()`, `Output`, `plt.show()`, tracebacks, and `logging` all show up in an output area
* **One event loop** — everything runs on Tk's `mainloop`

---

## 🔧 Requirements

* Python 3.10+
* [tkwry](https://github.com/mashu3/tkwry) (system WebView: WebView2 on Windows, WKWebView on macOS, WebKitGTK on Linux — see tkwry's platform notes)
* `ipywidgets>=8,<9`

The bundled widget runtime is inlined into the shell HTML. The Playground's
Monaco editor and standalone Altair / Bokeh documents load their JavaScript
libraries from a CDN.

### Bundled front-end dependencies

The widget front end is prebuilt from `js/` with esbuild into
`src/tkipw/html/runtime.{js,css}` and shipped inside the wheel (built in CI, not
committed to the repo). It embeds:

* **Jupyter Widgets** (`@jupyter-widgets/*`) and **Lumino** — BSD-3-Clause
* **anywidget**, **jupyter-leaflet**, **jQuery**, **Backbone.js** — MIT
* **Leaflet** and its map plugins — BSD / MIT / ISC / Beerware
* **Font Awesome Free** icon styles (pulled in by Jupyter Widgets; font binaries
  are stripped at build time) — MIT / CC BY 4.0 / SIL OFL 1.1

All are permissively licensed and redistributable; attributions are collected in
[`NOTICE`](NOTICE). Python runtime dependencies (`tkwry`, `ipywidgets`, `comm`,
`traitlets`, `markdown`) are installed by pip as normal and are not vendored.

---

## 📦 Installation

```bash
pip install -e .
pip install -e ".[demo]"   # plotting, data, image, and 3D demos
```

Rebuild the front end only if you change `js/`:

```bash
cd js && npm install && npm run build
```

---

## 🚀 Usage

```python
from tkipw import App, display
import matplotlib.pyplot as plt

app = App()
plt.plot([1, 2, 3], [1, 4, 9])
plt.show()          # routed into the output area (inline mode — default)
app.run()
```

Pop-up windows (``%matplotlib tk`` style for figures, and for any `display()`):

```python
from tkipw import App, display

app = App(title="host", display_mode="window")
display(some_chart)   # opens a Tk pop-up (host root stays hidden)
app.run()
```

Interactive widgets work as usual:

```python
from tkipw import App
import ipywidgets as widgets

app = App()
slider = widgets.IntSlider(description="n", value=10)
app.display(slider)
app.run()
```

`import ipywidgets` / `import anywidget` work unchanged.

* `app.display(...)` — mount widgets in **this** App's WebView
* `display` / `clear_output` / `Output` — notebook-style output under the cell
* `App(display_mode="inline"|"window")` — output pane vs one Tk pop-up per `display()`
  (window mode hides the host root so only the pop-ups are visible)
* `plt.show()` — follows the active App (PNG inline, or native TkAgg windows)

> **Import order:** `from tkipw import App` before you create widgets, so they
> bind to tkipw's Comm backend instead of a `DummyComm`.

### 🔄 Multiple Apps & cleanup

Several `App`s can be alive at once. The most recently used one (the one you
last called `display()` / `activate()` on) receives newly created widget comms.
`destroy()` cleans up that App, and when the **last** App closes, tkipw restores
the process-wide patches it installed (Comm backend registry, IPython display
bridge, logging handler, `sys.excepthook`).

```python
a = App(title="A")
b = App(title="B")

a.display(widgets.Button(description="in A"))   # activates A → renders in A
b.display(widgets.Button(description="in B"))   # activates B → renders in B

a.destroy()
b.destroy()   # last one out tears down global patches
```

The monkey-patches are also individually reversible:
`uninstall_comm_backend()`, `uninstall_jupyter_support()`.

---

## 📁 Examples

```bash
pip install -e ".[demo]"
python examples/playground.py    # inline: Monaco editor + stacked output
python examples/plotly_demo.py   # window: Plotly FigureWidget pop-up
python examples/ipyleaflet_demo.py # window: live ipyleaflet map pop-up
python examples/bokeh_demo.py    # window: Bokeh ``show(plot)`` pop-up
python examples/altair_demo.py   # window: Altair ``display(chart)`` pop-up
python examples/pillow_demo.py   # window: Pillow ``Image.show()`` pop-up
```

| Script | Mode | Description |
| ------ | ---- | ----------- |
| [`examples/playground.py`](examples/playground.py) | inline | Monaco multi-tab editor + stacked live output |
| [`examples/plotly_demo.py`](examples/plotly_demo.py) | window | Plotly `FigureWidget` in a Tk pop-up |
| [`examples/ipyleaflet_demo.py`](examples/ipyleaflet_demo.py) | window | Live ipyleaflet widget map in a Tk pop-up |
| [`examples/bokeh_demo.py`](examples/bokeh_demo.py) | window | Bokeh `show(plot)` in a Tk pop-up |
| [`examples/altair_demo.py`](examples/altair_demo.py) | window | Altair `display(chart)` in a Tk pop-up |
| [`examples/pillow_demo.py`](examples/pillow_demo.py) | window | Pillow `Image.show()` in a Tk pop-up |

---

## 🖥️ Playground

An **inline-mode** IDE-like playground with a Monaco multi-tab editor on the left
and stacked notebook-style output on the right:

```bash
python examples/playground.py
```

Samples (`README.md` / matplotlib / pyvista / pandas / Folium / ipyleaflet / …) open as
tabs. Running a `.md` or `.markdown` tab renders the file directly in the
themed output pane; Python code can render the same content with
`IPython.display.Markdown`. Run the active tab with the **Run** button or
⌘/Ctrl+Enter. While Python is running, the green play button becomes a red stop
button; stopping cooperative Python execution reports the interruption in the
output pane. The menu bar has
New/Open/Save, Undo/Redo, Find/Replace, Minimap, Word Wrap, editor theme, and a
**View → Display Mode → Inline / Window** selector. Inline results are stacked
in the toggleable output pane; Window mode opens each `display()` in a separate
Tk pop-up. Monaco loads from a CDN on first run.

---

## 🧩 Jupyter extensions

`IPython.display.display()`, `tkipw.display()` and `App.display()` all go through
one transform gateway, so library-specific display fixes live in extensions:

```python
from tkipw import register_extension

class MyExtension:
    name = "my-library"

    def setup(self):
        ...                 # initialise as a notebook front end

    def transform(self, obj):
        return obj          # adapt for the WebView if needed

register_extension(MyExtension())
```

Built-ins:

* **Matplotlib** — follows the active App's ``display_mode``: ``inline`` → PNG in the output
  area; ``window`` → native TkAgg figure windows (``%matplotlib tk`` style).
  Shortcuts: ``matplotlib_inline()`` / ``matplotlib_window()``.
* **Folium** — pixel ``Map(width=…, height=…)`` becomes a fixed-size hosted
  map (preferred in window mode). Percentage sizes keep the notebook HTML.
* **ipyleaflet** — bundled `jupyter-leaflet` module renders live widget maps;
  map/layer trait changes continue to flow over the tkipw Comm bridge.
* **Pillow** — `Image.show()` → PNG via ``display()`` (inline pane or pop-up)
* **Altair** — standalone Vega-Lite HTML hosted in a responsive iframe
* **Bokeh** — `show()` / displayed models → standalone HTML hosted in an iframe
* **PyVista** — `handle_plotter → show_trame → IPython.display`. On macOS the
  `trame` / `server` backends are remapped to `client`, because native VTK
  OpenGL + WKWebView crash (SIGTRAP). Large offline-`html` `srcdoc` iframes are
  served over a loopback `LocalHTMLHost` for WebView compatibility.

---

## 🏗️ Architecture

* **Python** — `comm.create_comm` → `TkwryComm`; official ipywidgets messages sent as JSON (+base64 buffers)
* **JS** — `@jupyter-widgets/html-manager` + `window.ipc`, with anywidget and
  jupyter-leaflet bundled in
* **Bridge** — a stack of active `App`s; the top receives new comm traffic

---

## 🧪 Tests

```bash
pytest -m "not e2e"        # fast, display-free unit tests
TKIPW_E2E=1 pytest -m e2e  # real WebView: boot, comm, and extension DOM regression
```

CI runs the unit tests on Windows / macOS / Linux, plus the WebView E2E suite
on Linux (Xvfb) and macOS (runtime/comm and extension display paths, split to
avoid WebKitGTK hangs). See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## ⚠️ Known limitations

* **Alpha** — APIs may change
* **Widget coverage** — standard ipywidgets 8 controls + anywidget + ipyleaflet;
  no kernel, `update_display`, or general dynamic third-party widget modules
  (bqplot, ipycanvas, …)
* **PyVista on macOS** — client-side rendering only (see extensions above)
* **Platform behavior** — inherits tkwry's platform notes (macOS embedding, import order, Linux source build)

---

## 📝 License

MIT. The bundled JavaScript embeds third-party libraries (Jupyter Widgets and
Lumino under BSD-3-Clause; anywidget, jQuery, and Backbone under MIT; Font
Awesome Free icon styles under MIT / CC BY 4.0 / OFL 1.1) — all permissive and
redistributable. See [`NOTICE`](NOTICE) for full attributions.

Built on [tkwry](https://github.com/mashu3/tkwry).

---

## 👨‍💻 Author

[mashu3](https://github.com/mashu3)

[![Contributors](https://contrib.rocks/image?repo=mashu3/tkipw)](https://github.com/mashu3/tkipw/graphs/contributors)
