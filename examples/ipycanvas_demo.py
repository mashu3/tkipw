"""Window-mode demo: a live ipycanvas Canvas opens in a Tk pop-up.

Requires:
    pip install -e ".[demo]"

Run:
    python examples/ipycanvas_demo.py
"""

from __future__ import annotations

from ipycanvas import Canvas, hold_canvas

from tkipw import App, display


def main() -> None:
    # Host root is withdrawn; only the live canvas pop-up is visible.
    app = App(title="tkipw · ipycanvas", display_mode="window")
    canvas = Canvas(width=640, height=360)
    display(canvas)

    with hold_canvas():
        canvas.fill_style = "#eff6ff"
        canvas.fill_rect(0, 0, canvas.width, canvas.height)

        canvas.fill_style = "#2563eb"
        canvas.fill_rect(40, 40, 200, 120)

        canvas.stroke_style = "#f59e0b"
        canvas.line_width = 4
        canvas.stroke_circle(420, 180, 80)

        canvas.fill_style = "#0f172a"
        canvas.font = "24px sans-serif"
        canvas.fill_text("ipycanvas in tkipw", 40, 320)

    app.run()


if __name__ == "__main__":
    main()
