#!/usr/bin/env bash
# Shared Linux test runner for GitHub Actions.
# Expects: DISPLAY set, Xvfb already running, package installed, cwd usable
# from repo root (tests/ at ./tests).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Leftover WebKitNetworkProcess zombies can lock later suites on GHA.
cleanup_webkit() {
  pkill -9 -f '[Ww]eb[Kk]it' 2>/dev/null || true
}

# Fast, display-free unit tests first.
pytest tests/unit/ -v --tb=short
cleanup_webkit

# Real-WebView end-to-end tests (opt in via TKIPW_E2E=1). WebKitGTK can hang in
# a single pytest process after many WebViews, so split suites.
TKIPW_E2E=1 pytest tests/e2e/test_webview.py -v --tb=short
cleanup_webkit
TKIPW_E2E=1 pytest tests/e2e/test_extensions.py -v --tb=short
cleanup_webkit
