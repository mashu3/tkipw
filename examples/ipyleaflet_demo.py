"""Window-mode demo: a live ipyleaflet map opens in a Tk pop-up.

Requires:
    pip install -e ".[demo]"

Run:
    python examples/ipyleaflet_demo.py
"""

from __future__ import annotations

from ipyleaflet import Map, Marker
from ipywidgets import Layout

from tkipw import App, display


def main() -> None:
    # Host root is withdrawn; only the live widget map pop-up is visible.
    app = App(title="tkipw · ipyleaflet", display_mode="window")
    tokyo = (35.6812, 139.7671)
    widget_map = Map(
        center=tokyo,
        zoom=12,
        layout=Layout(width="800px", height="480px"),
    )
    widget_map.add(Marker(location=tokyo, title="Tokyo Station"))
    display(widget_map)
    app.run()


if __name__ == "__main__":
    main()
