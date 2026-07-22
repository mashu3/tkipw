#!/usr/bin/env bash
# macOS CI test runner (GitHub Actions bash shell).
#
# WKWebView is unstable after repeated App create/destroy in one process:
# Abort trap during GC while LocalHTMLHost threads are still serving shell
# assets. Run each e2e case in its own pytest process so native state cannot
# accumulate (same posture as Windows / WebView2).
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
