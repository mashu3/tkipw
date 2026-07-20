"""DOM / event-loop helpers for real-WebView e2e tests."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable


def pump(root, *, steps: int = 1, delay_ms: int = 25) -> None:
    for _ in range(steps):
        root.update_idletasks()
        root.update()
        if sys.platform == "linux":
            try:
                from tkwry._core import ensure_gtk_init, pump_events

                ensure_gtk_init()
                pump_events()
            except Exception:
                pass
        root.after(delay_ms)
        root.update()


def wait_until(root, predicate: Callable[[], bool], *, steps: int = 400) -> bool:
    for _ in range(steps):
        if predicate():
            return True
        pump(root, steps=1)
    return predicate()


def eval_js(app, script: str, *, steps: int = 40) -> str:
    """Evaluate *script* and return the raw callback payload string.

    Keep *steps* small: callers often poll inside :func:`wait_until`, and a
    large nested wait turns a miss into a multi-minute stall (especially under
    WebKitGTK when callbacks are delayed).
    """
    results: list[str] = []
    app.webview.eval_js_with_callback(script, results.append)
    wait_until(app.root, lambda: bool(results), steps=steps)
    return results[-1] if results else ""


def eval_json(app, script: str, *, steps: int = 40):
    """Evaluate *script* and JSON-decode the callback payload."""
    raw = eval_js(app, script, steps=steps)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def dom_html(app) -> str:
    value = eval_json(
        app,
        "(document.getElementById('tkipw-widgets') || document.body).innerHTML",
    )
    return value if isinstance(value, str) else ""


def dom_text(app) -> str:
    value = eval_json(
        app,
        "(document.getElementById('tkipw-widgets') || document.body).innerText",
    )
    return value if isinstance(value, str) else ""


def query_count(app, selector: str) -> int:
    # Short wait: used as a wait_until predicate.
    value = eval_json(
        app,
        f"document.querySelectorAll({json.dumps(selector)}).length",
        steps=8,
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def wait_for_selector(app, selector: str, *, steps: int = 400) -> bool:
    return wait_until(app.root, lambda: query_count(app, selector) > 0, steps=steps)


def wait_for_html(app, needle: str, *, steps: int = 400) -> bool:
    return wait_until(app.root, lambda: needle in dom_html(app), steps=steps)
