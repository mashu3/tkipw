"""Package version is sourced from ``tkipw.__version__`` only."""

from __future__ import annotations

import re
from pathlib import Path

from tkipw import __version__

_ROOT = Path(__file__).resolve().parents[2]


def test_version_format():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_pyproject_reads_version_from_init():
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'path = "src/tkipw/__init__.py"' in text
    assert not re.search(r'(?m)^version\s*=\s*"', text)
