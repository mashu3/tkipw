"""Shared fixtures for real-WebView e2e tests."""

from __future__ import annotations

import os

import pytest

from e2e.helpers import wait_until


@pytest.fixture
def app():
    if os.environ.get("TKIPW_E2E") != "1":
        pytest.skip("set TKIPW_E2E=1 to run the real-WebView end-to-end tests")
    pytest.importorskip("tkwry")
    from tkipw import App

    try:
        instance = App(title="tkipw-e2e", width=720, height=520)
    except Exception as exc:  # pragma: no cover - no usable display / WebView
        pytest.skip(f"WebView unavailable: {exc}")

    try:
        assert wait_until(instance.root, lambda: instance._ready), (
            "runtime never became ready"
        )
        yield instance
    finally:
        instance.destroy()
