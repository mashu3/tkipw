"""Window-mode demo: a live bqplot Figure opens in a Tk pop-up.

Requires:
    pip install -e ".[demo]"

Run:
    python examples/bqplot_demo.py
"""

from __future__ import annotations

from bqplot import Axis, Figure, LinearScale, Scatter
from ipywidgets import Layout

from tkipw import App, display


def main() -> None:
    # Host root is withdrawn; only the live figure pop-up is visible.
    app = App(title="tkipw · bqplot", display_mode="window")

    x_sc = LinearScale()
    y_sc = LinearScale()
    scatter = Scatter(
        x=[1, 2, 3, 4, 5],
        y=[1, 4, 9, 16, 25],
        scales={"x": x_sc, "y": y_sc},
        colors=["#2563eb"],
    )
    ax_x = Axis(scale=x_sc, label="x")
    ax_y = Axis(scale=y_sc, label="y")
    ax_y.orientation = "vertical"
    fig = Figure(
        marks=[scatter],
        axes=[ax_x, ax_y],
        title="bqplot in tkipw",
        layout=Layout(width="640px", height="400px"),
    )
    display(fig)
    app.run()


if __name__ == "__main__":
    main()
