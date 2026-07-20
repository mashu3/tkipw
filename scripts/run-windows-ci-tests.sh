#!/usr/bin/env bash
# Windows CI test runner (GitHub Actions bash shell).
#
# WebView2 on Windows (especially arm64) is unstable after repeated App
# create/destroy in one process: fatal 0x80000003 during GC + LocalHTMLHost
# writes, or Tcl failing to open init.tcl. Run each e2e case in its own
# pytest process so native state cannot accumulate.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export TK_SILENCE_DEPRECATION="${TK_SILENCE_DEPRECATION:-1}"
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"

pytest tests/unit/ -v --tb=short

run_e2e_isolated() {
  local nodeid
  while IFS= read -r nodeid; do
    [[ "$nodeid" == *::* ]] || continue
    echo "==> $nodeid"
    TKIPW_E2E=1 pytest "$nodeid" -v --tb=short
  done < <(TKIPW_E2E=1 pytest "$@" --collect-only -q | grep '::' || true)
}

run_e2e_isolated tests/e2e/test_webview.py tests/e2e/test_extensions.py
