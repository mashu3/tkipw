"""Small process-local HTTP host for rich HTML documents.

Some Jupyter renderers produce large ``srcdoc`` iframes.  Hosting those
documents on loopback keeps Comm messages small and gives nested pages a real
origin, which is more reliable in desktop WebViews.
"""

from __future__ import annotations

import atexit
import html as html_lib
import re
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

_MODULE_SCRIPT_RE = re.compile(
    r'(<script)\s+type=(["\'])module\2',
    re.IGNORECASE,
)
_SRCDOC_RE = re.compile(
    r'srcdoc=(["\'])(.*?)\1',
    re.IGNORECASE | re.DOTALL,
)
_IFRAME_RE = re.compile(r"<iframe([^>]*)>", re.IGNORECASE)


class LocalHTMLHost:
    """Serve in-memory HTML documents on an ephemeral loopback port."""

    def __init__(self, *, max_documents: int = 32) -> None:
        self._documents: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()
        self._max_documents = max_documents
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._httpd.daemon_threads = True
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="tkipw-html-host",
            daemon=True,
        )
        self._thread.start()

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        documents = self._documents
        lock = self._lock

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if not path.startswith("/document/") or not path.endswith(".html"):
                    self.send_error(404)
                    return
                key = path[len("/document/") : -len(".html")]
                with lock:
                    body = documents.get(key)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def mount(self, document: str) -> str:
        """Store a document and return its loopback URL."""
        key = uuid.uuid4().hex
        with self._lock:
            self._documents[key] = document.encode("utf-8")
            while len(self._documents) > self._max_documents:
                self._documents.popitem(last=False)
        return f"http://127.0.0.1:{self.port}/document/{key}.html"

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


_host: LocalHTMLHost | None = None
_host_lock = threading.Lock()


def get_html_host() -> LocalHTMLHost:
    """Return the shared, lazily-created HTML host."""
    global _host
    with _host_lock:
        if _host is None:
            _host = LocalHTMLHost()
            atexit.register(_host.shutdown)
        return _host


def demote_module_scripts(document: str) -> str:
    """Turn inline ES-module scripts into classic scripts.

    Use only for self-contained bundles with no ``import``/``export``.  This
    compatibility step is useful for WKWebView renderers such as vtk.js.
    """
    return _MODULE_SCRIPT_RE.sub(r"\1", document)


def _inject_head_style(document: str, css: str) -> str:
    """Insert a ``<style>`` block before ``</head>`` (or at the top)."""
    block = f"<style>{css}</style>"
    if "</head>" in document:
        return document.replace("</head>", block + "</head>", 1)
    return block + document


def _inline_fill_document(document: str) -> str:
    """Stretch hosted page content to the iframe (inline pane width wins)."""
    return _inject_head_style(
        document,
        "html,body{width:100%;height:100%;margin:0;padding:0;overflow:hidden;}"
        "body>*{width:100%!important;height:100%!important;"
        "max-width:100%!important;box-sizing:border-box;}",
    )


def _parse_px(value: str) -> float | None:
    """Return a CSS pixel length, or ``None`` when *value* is not ``…px``."""
    text = value.strip().lower()
    if not text.endswith("px"):
        return None
    try:
        return float(text[:-2].strip())
    except ValueError:
        return None


def host_html_document(
    document: str,
    *,
    width: str = "100%",
    height: str = "500px",
    title: str = "Rich output",
) -> str:
    """Host a complete HTML document and return an iframe fragment.

    When an App is active in **inline** mode and both *width* and *height* are
    pixel sizes, the iframe stretches to the pane width while keeping the
    author's aspect ratio (``width:100%; aspect-ratio:W/H``). Callers that
    already pass ``width="100%"`` keep their declared height. Window / compact
    pop-ups keep the caller's size unchanged.
    """
    try:
        from .comm_backend import get_bridge
        from .display_mode import get_display_mode

        inline = get_bridge() is not None and get_display_mode() == "inline"
    except Exception:
        inline = False

    style = f"width:{width};height:{height};border:0;display:block"
    if inline:
        document = _inline_fill_document(document)
        w_px = _parse_px(width)
        h_px = _parse_px(height)
        if w_px is not None and h_px is not None and w_px > 0 and h_px > 0:
            # Pane width wins; scale height with the declared aspect ratio.
            ratio = f"{w_px:g} / {h_px:g}"
            style = (
                f"width:100%;aspect-ratio:{ratio};height:auto;border:0;display:block"
            )
        else:
            style = f"width:100%;height:{height};border:0;display:block"

    url = get_html_host().mount(document)
    safe_title = html_lib.escape(title, quote=True)
    safe_style = html_lib.escape(style, quote=True)
    return (
        f'<iframe src="{url}" class="tkipw-hosted-html" '
        f'title="{safe_title}" '
        f'style="{safe_style}" '
        'allow="fullscreen" referrerpolicy="no-referrer"></iframe>'
    )


def host_srcdoc_iframe(
    iframe: str,
    *,
    document_transform: Callable[[str], str] | None = None,
) -> str | None:
    """Replace an iframe's ``srcdoc`` with a loopback ``src``.

    Returns ``None`` when *iframe* has no ``srcdoc``.
    """
    match = _SRCDOC_RE.search(iframe)
    if match is None:
        return None
    document = html_lib.unescape(match.group(2))
    if document_transform is not None:
        document = document_transform(document)
    url = get_html_host().mount(document)

    attrs_match = _IFRAME_RE.search(iframe)
    attrs = attrs_match.group(1) if attrs_match else ""
    width = _css_dimension(attrs, "width", "100%")
    height = _css_dimension(attrs, "height", "600px")
    return (
        f'<iframe src="{url}" class="tkipw-hosted-html" '
        f'style="width:{width};height:{height};border:0" '
        'allow="fullscreen" referrerpolicy="no-referrer"></iframe>'
    )


def _css_dimension(attrs: str, name: str, default: str) -> str:
    match = re.search(rf"{name}:\s*([^;\"]+)", attrs, re.IGNORECASE)
    return match.group(1).strip() if match else default
