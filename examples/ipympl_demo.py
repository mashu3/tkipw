"""Window-mode demo: interactive Matplotlib via ipympl in a Tk pop-up.

Requires:
    pip install -e ".[demo]"

Run:
    python examples/ipympl_demo.py

``import ipympl`` (after the App exists, and preferably after matplotlib) opts
into the interactive WebView backend. Plain Matplotlib demos omit that import
and keep PNG / TkAgg.
"""

from __future__ import annotations

import numpy as np

from tkipw import App, display


def main() -> None:
    # Host root is withdrawn; the live ipympl canvas opens in a pop-up.
    app = App(title="tkipw · ipympl", display_mode="window")

    # Load matplotlib first, then ipympl (matches ipympl's own ``use()`` path
    # and the App import hook).
    import importlib

    plt = importlib.import_module("matplotlib.pyplot")
    importlib.import_module("ipympl")

    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=100)
    x = np.linspace(0, 2 * np.pi, 200)
    ax.plot(x, np.sin(x), color="#2563eb", lw=2)
    ax.set_title("ipympl in tkipw")
    ax.set_xlabel("x")
    ax.set_ylabel("sin(x)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    display(fig.canvas)
    app.run()


if __name__ == "__main__":
    main()
