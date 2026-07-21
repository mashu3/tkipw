# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Bundled **bqplot** / **bqscales** front end (live SVG figures in the WebView)
  with playground sample and `examples/bqplot_demo.py`
- Bundled **ipycanvas** front end (live `Canvas` in the WebView) with playground
  sample and `examples/ipycanvas_demo.py`
- PyPI-oriented install docs and packaging classifiers (Python 3.10–3.14)

### Fixed

- Defer iopub ``idle`` until after WidgetModel increments its pending counter so
  later trait syncs (e.g. bqplot toolbar PanZoom) are not buffered forever
- Register frontend-initiated secondary comms with CommManager so teardown does
  not raise ``KeyError`` in ``Widget.__del__``
- Bridge WebView ``<a download>`` clicks to a native Tk save dialog (bqplot
  toolbar Save and similar)
- Drop compact-shell padding for ipycanvas / bqplot so window-mode pop-ups are
  edge-to-edge like maps and images
- Serve `runtime.js` / `runtime.css` as separate loopback assets (HTML stays
  small) so large bundles still boot in desktop WebViews
- Accept frontend-initiated ``comm_open`` (e.g. bqplot toolbar ``PanZoom``) so
  ``IPY_MODEL_…`` trait refs resolve on the Python side
- Load the widget shell over a loopback URL so WebView2’s ~2MB `navigate_to_string`
  limit is not hit
- Windows WebView / VTK startup races and empty window flash
- Detect unsupported window alpha on Linux/Xvfb
- Use tkface for Windows DPI; harden Playground output boot
- Prevent Matplotlib TkAgg teardown hang on headless Linux CI
- Require `tkface>=0.2.1`
- Harden Windows/Linux e2e (split suites, per-process Windows tests, ipyleaflet
  window-mode isolation)
- Align bundled JS license notices; trim lazy `__all__`; reset Comm state in tests

### Changed

- CI: `actions/setup-node` v6 and Node 24

## [0.0.1] - 2026-07-20

Initial Alpha release on PyPI.

### Added

- Desktop ipywidgets / anywidget runtime on [tkwry](https://github.com/mashu3/tkwry)
  (no Jupyter Notebook / browser tab)
- `App`, `display()`, `clear_output()`, `Output`, and notebook-like routing for
  Matplotlib / logging / tracebacks
- Bundled front end: `@jupyter-widgets/html-manager`, anywidget, **jupyter-leaflet**
  / ipyleaflet
- Optional display helpers (Matplotlib, Folium, Plotly, Pillow, PyVista, pandas, …)
- Playground and demo examples
- CI and tag-triggered GitHub Release / PyPI publish workflow
