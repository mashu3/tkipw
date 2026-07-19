"""Window-mode demo: Pillow ``Image.show()`` opens in a separate Tk pop-up.

Requires:
    pip install -e ".[demo]"

Run:
    python examples/pillow_demo.py
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from tkipw import App


def main() -> None:
    # Host root is withdrawn; only the image pop-up is visible.
    app = App(title="tkipw · pillow", display_mode="window")

    im = Image.new("RGB", (640, 320), "#eff6ff")
    draw = ImageDraw.Draw(im)
    for x in range(im.width):
        color = (
            37,
            99,
            235,
            int(40 + 180 * x / im.width),
        )
        draw.line((x, 0, x, im.height), fill=color[:3])
    draw.ellipse(
        (210, 50, 430, 270),
        fill="#fbbf24",
        outline="white",
        width=8,
    )

    im.show()
    app.run()


if __name__ == "__main__":
    main()
