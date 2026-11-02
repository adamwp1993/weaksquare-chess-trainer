"""The temporary loopback listener for the OAuth redirect (FR-6.2, SR-4, SR-9).

Bound to 127.0.0.1 only, on a random free port. It accepts exactly one `GET /callback` (other paths
get a 404 and don't consume it), answers with a plain page, then shuts down. It also shuts down after
the timeout or when cancelled. The callback's query (it holds the authorization code) is never logged.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

TIMEOUT_S = 300  # FR-6.2: 5 minutes

PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>WeakSquare</title></head>
<body style="font-family:sans-serif;margin:3em"><p>{message}</p></body></html>"""
OK_MESSAGE = "Signed in. You can close this tab and return to WeakSquare."
FAIL_MESSAGE = "Sign-in didn't complete. You can close this tab and return to WeakSquare to try again."


class LoopbackTimeout(Exception):
    pass


class LoopbackCancelled(Exception):
    pass


Query = dict[str, list[str]]


class LoopbackListener:
    def __init__(self, accept: Callable[[Query], bool] = lambda q: True, timeout_s: float = TIMEOUT_S) -> None:
        """`accept(query)` decides which page the browser sees (it doesn't change what `wait` returns)."""
        self._accept = accept
        self._timeout_s = timeout_s
        self._done = threading.Event()
        self._query: Query | None = None
        self._cancelled = False
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        """Start listening; returns the redirect URI."""
        listener = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                url = urlsplit(self.path)
                if url.path != "/callback" or listener._done.is_set():
                    self.send_error(404)
                    return
                query = parse_qs(url.query, keep_blank_values=True)
                ok = listener._accept(query)
                body = PAGE.format(message=OK_MESSAGE if ok else FAIL_MESSAGE).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                listener._query = query
                listener._done.set()

            def log_message(self, format: str, *args: object) -> None:
                pass  # SR-9: the request line holds the code; never log it

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="oauth-loopback", daemon=True)  # fmt: skip
        self._thread.start()
        return f"http://127.0.0.1:{self._server.server_address[1]}/callback"

    def wait(self) -> Query:
        """Block until the callback, the timeout or a cancel. Always shuts the listener down."""
        try:
            if not self._done.wait(self._timeout_s):
                raise LoopbackTimeout()
            if self._cancelled or self._query is None:
                raise LoopbackCancelled()
            return self._query
        finally:
            self.close()

    def cancel(self) -> None:
        self._cancelled = True
        self._done.set()

    def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
