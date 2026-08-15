"""Native save-dialog bridge for WebView ``<a download>`` clicks."""

from __future__ import annotations

import base64

from tkipw.app import App, _suggested_download_filename


class _FakeRoot:
    """Minimal stand-in so this unit test never opens a real Tk display.

    Windows ARM64 CI occasionally ships a broken Tk (missing ttk scripts);
    ``filedialog`` is monkeypatched anyway, so a real root is unnecessary.
    """

    def after(self, _ms: int, callback) -> None:
        callback()

    def update(self) -> None:
        pass


def test_handle_download_from_js_writes_file(tmp_path, monkeypatch):
    root = _FakeRoot()
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
    assert out.read_bytes() == b"PNGDATA"


def test_handle_download_from_js_cancel_is_noop(tmp_path, monkeypatch):
    root = _FakeRoot()
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
    assert list(tmp_path.iterdir()) == before


def test_suggested_download_filename_strips_path():
    assert _suggested_download_filename("../evil/image.png") == "image.png"
    assert _suggested_download_filename("", ".", "..") == "download"
    assert _suggested_download_filename(None, 1, "report.pdf") == "report.pdf"


def test_on_native_download_returns_absolute_path(tmp_path, monkeypatch):
    root = _FakeRoot()
    host = type("DownloadHost", (), {"_destroyed": False, "root": root})()
    out = tmp_path / "report.pdf"
    captured: dict[str, object] = {}

    def fake_dialog(**kwargs):
        captured.update(kwargs)
        return str(out)

    monkeypatch.setattr("tkipw.app.filedialog.asksaveasfilename", fake_dialog)
    result = App._on_native_download(
        host,
        "https://example.com/files/report.pdf",
        str(tmp_path / "suggested.pdf"),
    )
    assert result == str(out)
    assert captured["initialfile"] == "suggested.pdf"


def test_on_native_download_falls_back_to_url_name(tmp_path, monkeypatch):
    root = _FakeRoot()
    host = type("DownloadHost", (), {"_destroyed": False, "root": root})()
    out = tmp_path / "chart.png"
    captured: dict[str, object] = {}

    def fake_dialog(**kwargs):
        captured.update(kwargs)
        return str(out)

    monkeypatch.setattr("tkipw.app.filedialog.asksaveasfilename", fake_dialog)
    result = App._on_native_download(
        host,
        "https://cdn.example.com/chart.png",
        "",
    )
    assert result == str(out)
    assert captured["initialfile"] == "chart.png"


def test_on_native_download_cancel_returns_false(monkeypatch):
    root = _FakeRoot()
    host = type("DownloadHost", (), {"_destroyed": False, "root": root})()
    monkeypatch.setattr(
        "tkipw.app.filedialog.asksaveasfilename",
        lambda **_kwargs: "",
    )
    assert (
        App._on_native_download(host, "https://example.com/a.bin", "/tmp/a.bin")
        is False
    )
