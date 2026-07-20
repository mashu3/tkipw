#!/usr/bin/env bash
# Windows CI test runner (GitHub Actions bash shell).
# Split e2e suites into separate pytest processes: after many WebView2
# instances in one process, Windows (especially arm64) can fatal-exit while
# creating the next App (0x80000003 during GC / http.server / Tk pump), or
# leave Tcl unable to open init.tcl for a subsequent tk.Tk().
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export TK_SILENCE_DEPRECATION="${TK_SILENCE_DEPRECATION:-1}"
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"

pytest tests/unit/ -v --tb=short

# Window-mode uses nested Tk roots; run it first in a fresh process while
# Tcl/WebView2 are still clean (later suites can leave init.tcl unreadable).
TKIPW_E2E=1 pytest \
  tests/e2e/test_extensions.py::test_ipyleaflet_map_renders_in_window_mode \
  -v --tb=short

TKIPW_E2E=1 pytest tests/e2e/test_webview.py -v --tb=short
TKIPW_E2E=1 pytest tests/e2e/test_extensions.py -v --tb=short \
  -k "not test_ipyleaflet_map_renders_in_window_mode"
