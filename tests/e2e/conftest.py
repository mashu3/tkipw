"""Shared fixtures for real-WebView e2e tests."""

from __future__ import annotations

import os

import pytest

from e2e.helpers import pump, wait_until

# macOS CI sets ``TKIPW_E2E_SHARED_APP=1`` so one App (one WKWebView cold start)
# serves a whole test module. Default stays function-scoped for Windows/Linux
# isolation runners that create/destroy per case.
_APP_SCOPE = "module" if os.environ.get("TKIPW_E2E_SHARED_APP") == "1" else "function"


def _reset_app_state(instance: object) -> None:
    """Clear output / theme / matplotlib so the next test sees a clean shell."""
    try:
        from tkipw.output import clear_output

        clear_output(wait=False)
    except Exception:
        pass
    set_theme = getattr(instance, "set_theme", None)
    if callable(set_theme):
        try:
            set_theme("light")
        except Exception:
            pass
    try:
        from tkipw.extensions.matplotlib import enable_matplotlib

        enable_matplotlib(mode="inline")
    except Exception:
        pass
    root = getattr(instance, "root", None)
    if root is not None:
        pump(root, steps=2)


@pytest.fixture(scope=_APP_SCOPE)
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


@pytest.fixture(autouse=True)
def _reset_shared_app_between_tests(request: pytest.FixtureRequest):
    """When the App is module-scoped, scrub state before/after each test."""
    if os.environ.get("TKIPW_E2E_SHARED_APP") != "1":
        yield
        return
    if "app" not in request.fixturenames:
        yield
        return
    instance = request.getfixturevalue("app")
    _reset_app_state(instance)
    yield
    _reset_app_state(instance)
