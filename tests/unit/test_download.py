"""Native save-dialog bridge for WebView ``<a download>`` clicks."""

from __future__ import annotations

import base64
import tkinter as tk

from tkipw.app import App


def test_handle_download_from_js_writes_file(tmp_path, monkeypatch):
    root = tk.Tk()
    root.withdraw()
    host = type("DownloadHost", (), {"_destroyed": False, "root": root})()
    out = tmp_path / "image.png"
    monkeypatch.setattr(
        "tkipw.app.filedialog.asksaveasfilename",
        lambda **_kwargs: str(out),
    )

    App._handle_download_from_js(
        host,
        {
            "filename": "../evil/image.png",
            "data_base64": base64.b64encode(b"PNGDATA").decode("ascii"),
        },
    )
    root.update()
    assert out.read_bytes() == b"PNGDATA"
    root.destroy()


def test_handle_download_from_js_cancel_is_noop(tmp_path, monkeypatch):
    root = tk.Tk()
    root.withdraw()
    host = type("DownloadHost", (), {"_destroyed": False, "root": root})()
    monkeypatch.setattr(
        "tkipw.app.filedialog.asksaveasfilename",
        lambda **_kwargs: "",
    )
    before = list(tmp_path.iterdir())
    App._handle_download_from_js(
        host,
        {
            "filename": "image.png",
            "data_base64": base64.b64encode(b"PNGDATA").decode("ascii"),
        },
    )
    root.update()
    assert list(tmp_path.iterdir()) == before
    root.destroy()
