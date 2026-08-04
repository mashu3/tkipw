#!/usr/bin/env bash
# macOS CI test runner (GitHub Actions bash shell).
#
# WKWebView Aborts after repeated App create/destroy in one process. Speed up
# by sharing one App per test module (TKIPW_E2E_SHARED_APP=1) and only
# isolating window-mode cases that construct their own App/WebView.
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

echo "==> tests/e2e/test_webview.py (shared App)"
TKIPW_E2E=1 TKIPW_E2E_SHARED_APP=1 pytest tests/e2e/test_webview.py -v --tb=short

echo "==> tests/e2e/test_extensions.py (shared App, exclude window-mode)"
TKIPW_E2E=1 TKIPW_E2E_SHARED_APP=1 pytest tests/e2e/test_extensions.py \
  -k "not in_window_mode" -v --tb=short

echo "==> window-mode e2e (isolated processes)"
run_e2e_isolated tests/e2e/test_extensions.py -k "in_window_mode"
