"""WidgetFrame is the Tk Frame host; App is the windowed wrapper."""

from __future__ import annotations

import inspect
import tkinter as tk

from tkipw.app import App, WidgetFrame


def test_widget_frame_is_tk_frame():
    assert issubclass(WidgetFrame, tk.Frame)
    assert issubclass(App, WidgetFrame)


def test_widget_frame_takes_master_first():
    params = list(inspect.signature(WidgetFrame.__init__).parameters)
    assert params[1] == "master"


def test_app_keeps_keyword_only_parent():
    params = inspect.signature(App.__init__).parameters
    assert params["parent"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["root"].kind is inspect.Parameter.KEYWORD_ONLY
