"""Window-mode demo: Bokeh ``show()`` opens in a separate Tk pop-up.

Requires:
    pip install -e ".[demo]"

Run:
    python examples/bokeh_demo.py
"""

from __future__ import annotations

# Import tkipw before creating plots so ``show`` routes through tkipw.
from bokeh.plotting import figure, show

from tkipw import App


def main() -> None:
    # Host root is withdrawn; only the plot pop-up is visible.
    app = App(title="tkipw · bokeh", display_mode="window")

    plot = figure(
        title="Bokeh in tkipw",
        width=640,
        height=400,
        tools="pan,wheel_zoom,box_zoom,reset,save",
    )
    plot.line([1, 2, 3, 4, 5], [1, 4, 9, 16, 25], line_width=3)
    plot.scatter([1, 2, 3, 4, 5], [1, 4, 9, 16, 25], size=10)

    show(plot)
    app.run()


if __name__ == "__main__":
    main()
