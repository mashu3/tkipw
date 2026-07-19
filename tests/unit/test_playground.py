"""Playground editor + StackedOutput helpers (no WebView required)."""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace
from unittest.mock import MagicMock

import ipywidgets as widgets

from examples.playground import (
    EditorShortcutBindings,
    Playground,
    StackedOutput,
    _editor_html,
)


def test_editor_exposes_menu_actions():
    html = _editor_html([])
    for api in (
        "editorUndo",
        "editorRedo",
        "editorCut",
        "editorCopy",
        "editorPasteText",
        "editorFind",
        "editorReplace",
        "editorSetMinimap",
        "editorSetWordWrap",
        "editorSetTheme",
        "editorMarkSaved",
    ):
        assert f"window.{api}" in html
    assert 'endsWith(".md")' in html
    assert 'return "markdown"' in html
    assert 'type: "stop"' in html
    assert "runBusy ? stopIcon : runIcon" in html


def test_editor_shortcut_bindings_cover_paste():
    assert "<Control-v>" in EditorShortcutBindings.PASTE
    assert "<Command-v>" in EditorShortcutBindings.PASTE
    assert "<<Paste>>" in EditorShortcutBindings.PASTE

    calls: list[str] = []

    def action() -> None:
        calls.append("paste")

    handler = EditorShortcutBindings.wrap(action)
    assert handler(object()) == "break"  # type: ignore[arg-type]
    assert calls == ["paste"]


def test_stacked_output_appends_sections_vertically():
    output = StackedOutput()
    output._append([widgets.HTML(value="<table><tr><td>x</td></tr></table>")])
    output._append([widgets.HTML(value='<img src="data:image/png;base64,x"/>')])

    assert len(output.children) == 2
    first, second = output.children
    assert "tkipw-section" in first._dom_classes
    assert "tkipw-section-header" in first.children[0].value
    assert "1 · Table" in first.children[0].value
    assert "2 · Figure" in second.children[0].value
    assert "<table" in first.children[1].value
    assert "<img" in second.children[1].value


def test_stacked_output_labels_markdown():
    output = StackedOutput()
    output._append(
        [widgets.HTML(value='<article class="tkipw-markdown"><h1>Hi</h1></article>')]
    )

    assert "1 · Markdown" in output.children[0].children[0].value


def test_stacked_output_wait_clear_replaces_sections():
    output = StackedOutput()
    output._append([widgets.Label("old")])
    output.clear_output(wait=True)
    output._append([widgets.Label("new")])

    assert len(output.children) == 1
    section = output.children[0]
    assert "1 · Label" in section.children[0].value
    assert section.children[1].value == "new"


def test_display_mode_menu_updates_app_and_output_pane():
    playground = Playground.__new__(Playground)
    playground._display_mode_var = MagicMock()
    playground._display_mode_var.get.return_value = "window"
    playground.app = MagicMock()
    playground._set_output_visible = MagicMock()
    playground._set_status = MagicMock()

    playground._apply_display_mode()

    playground.app.set_display_mode.assert_called_once_with("window")
    playground._set_output_visible.assert_called_once_with(False)
    playground._set_status.assert_called_once_with("display · window")


def test_stop_interrupts_python_loop_and_displays_message():
    playground = Playground.__new__(Playground)
    playground.app = SimpleNamespace(display_mode="inline")
    playground._results = StackedOutput()
    playground._stop_requested = False
    playground._user_tk_roots = []
    playground._finish = MagicMock()
    playground.root = MagicMock()
    playground.root.update.side_effect = lambda: setattr(
        playground, "_stop_requested", True
    )

    playground._exec_code("while True:\n    pass", "loop.py")

    assert len(playground._results.children) == 1
    section = playground._results.children[0]
    assert "Execution stopped by user." in section.children[1].value
    playground._finish.assert_called_once_with("stopped · loop.py")


def test_stop_interrupts_tkinter_mainloop(tk_root):
    root = tk_root
    root.withdraw()
    playground = Playground.__new__(Playground)
    playground.app = SimpleNamespace(display_mode="inline")
    playground._results = StackedOutput()
    playground._busy = True
    playground._stop_requested = False
    playground._user_tk_roots = []
    playground._finish = MagicMock()
    playground._set_status = MagicMock()
    playground.root = root

    root.after(100, playground._on_stop)
    playground._exec_code(
        "\n".join(
            [
                "import tkinter as tk",
                "win = tk.Tk()",
                "win.title('demo')",
                "tk.Label(win, text='hello').pack()",
                "win.mainloop()",
            ]
        ),
        "tk_app.py",
    )

    playground._finish.assert_called_once_with("stopped · tk_app.py")
    assert any(
        "Execution stopped by user." in section.children[1].value
        for section in playground._results.children
    )


def test_closing_tkinter_window_ends_run_without_stop(tk_root):
    root = tk_root
    root.withdraw()
    playground = Playground.__new__(Playground)
    playground.app = SimpleNamespace(display_mode="inline")
    playground._results = StackedOutput()
    playground._busy = True
    playground._stop_requested = False
    playground._user_tk_roots = []
    playground._finish = MagicMock()
    playground._set_status = MagicMock()
    playground.root = root

    def close_user_window() -> None:
        for window in list(playground._user_tk_roots):
            try:
                if window.winfo_exists():
                    window.destroy()
            except tk.TclError:
                pass

    root.after(100, close_user_window)
    playground._exec_code(
        "\n".join(
            [
                "import tkinter as tk",
                "win = tk.Tk()",
                "win.title('demo')",
                "tk.Label(win, text='hello').pack()",
                "win.mainloop()",
            ]
        ),
        "tk_app.py",
    )

    playground._finish.assert_called_once_with("done · tk_app.py")
    # Playground root must stay alive (Misc.quit would end its mainloop).
    assert root.winfo_exists()


def test_quit_user_tk_windows_does_not_call_quit(tk_root):
    root = tk_root
    root.withdraw()
    child = tk.Toplevel(root)
    playground = Playground.__new__(Playground)
    playground._user_tk_roots = [child]
    child.quit = MagicMock(side_effect=AssertionError("quit() must not be called"))

    playground._quit_user_tk_windows()

    assert not child.winfo_exists()
    assert root.winfo_exists()
