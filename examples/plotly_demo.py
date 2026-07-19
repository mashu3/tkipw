"""Window-mode demo: Plotly opens in a separate Tk pop-up.

Requires:
    pip install -e ".[demo]"

Run:
    python examples/plotly_demo.py
"""

from __future__ import annotations

# Import tkipw before creating widgets so they use TkwryComm, not DummyComm.
import plotly.graph_objects as go

from tkipw import App, display


def main() -> None:
    # Host root is withdrawn; only the figure pop-up is visible.
    app = App(title="tkipw · plotly", display_mode="window")

    fig = go.FigureWidget(
        data=[
            go.Scatter(
                x=[1, 2, 3, 4, 5],
                y=[1, 4, 9, 16, 25],
                mode="lines+markers",
                name="y = x²",
            )
        ],
        layout=go.Layout(
            title="Plotly FigureWidget in tkipw",
            autosize=True,
            margin=dict(l=40, r=20, t=50, b=40),
        ),
    )
    display(fig)
    app.run()


if __name__ == "__main__":
    main()
