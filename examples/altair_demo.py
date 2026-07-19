"""Window-mode demo: Altair opens in a separate Tk pop-up.

Requires:
    pip install -e ".[demo]"

Run:
    python examples/altair_demo.py

Note: the chart loads Vega-Lite from a CDN on first run.
"""

from __future__ import annotations

import altair as alt

from tkipw import App, display


def main() -> None:
    # Host root is withdrawn; only the chart pop-up is visible.
    app = App(title="tkipw · altair", display_mode="window")

    data = alt.Data(
        values=[
            {"city": "Tokyo", "sales": 120},
            {"city": "Osaka", "sales": 88},
            {"city": "Fukuoka", "sales": 95},
        ]
    )
    chart = (
        alt.Chart(data)
        .mark_bar(color="#2563eb")
        .encode(x="city:N", y="sales:Q", tooltip=["city:N", "sales:Q"])
        .properties(title="Altair in tkipw", width=480, height=320)
    )
    display(chart)
    app.run()


if __name__ == "__main__":
    main()
