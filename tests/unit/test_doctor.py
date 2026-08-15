"""``python -m tkipw doctor`` — display-free diagnostics."""

from __future__ import annotations

from pathlib import Path

from tkipw import __version__
from tkipw.__main__ import main
from tkipw.doctor import collect_report, run_doctor


def test_collect_report_includes_tkipw_version():
    report = collect_report()
    names = {line.name: line for line in report.packages}
    assert names["tkipw"].detail == __version__
    assert names["tkipw"].ok
    assert names["ipywidgets"].ok
    assert names["tkwry"].ok


def test_collect_report_runtime_assets_present():
    report = collect_report()
    shell = {line.name: line for line in report.shell}
    assert shell["runtime.js"].ok
    assert shell["runtime.css"].ok
    assert report.ok
    widgets = {line.name: line for line in report.widgets}
    assert widgets["anywidget"].ok
    assert widgets["jupyter-leaflet"].ok


def test_missing_runtime_fails_report(tmp_path: Path):
    report = collect_report(html_dir=tmp_path)
    assert not report.ok
    shell = {line.name: line for line in report.shell}
    assert not shell["runtime.js"].ok
    assert "missing" in shell["runtime.js"].detail


def test_format_contains_sections():
    text = collect_report().format()
    assert text.startswith("Packages\n")
    assert "\nWebView\n" in text
    assert "\nShell\n" in text
    assert "\nWidget runtime\n" in text
    assert "jupyter-matplotlib" in text


def test_run_doctor_exit_zero(capsys):
    assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "tkipw" in out
    assert "OK" in out


def test_main_doctor_ok():
    assert main(["doctor"]) == 0


def test_main_help_without_command():
    assert main([]) == 2
