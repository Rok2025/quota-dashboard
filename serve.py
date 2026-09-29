#!/usr/bin/env python3
"""Serve the quota dashboard on 127.0.0.1.

    GET /            -> web/index.html
    GET /api/quota   -> aggregated usage JSON (collected on request, cached briefly)
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import collect

HOST = "127.0.0.1"
PORT = int(os.environ.get("QUOTA_PORT", "8765"))
WEB_DIR = Path(__file__).resolve().parent / "web"
CACHE_SECONDS = 5

_cache_lock = threading.Lock()
_cache = {"at": 0.0, "body": b""}


def quota_body() -> bytes:
    with _cache_lock:
        now = time.time()
        if now - _cache["at"] > CACHE_SECONDS:
            _cache["body"] = json.dumps(collect.collect(now), ensure_ascii=False).encode("utf-8")
            _cache["at"] = now
        return _cache["body"]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        path = self.path.split("?", 1)[0]
        if path == "/api/quota":
            try:
                self._send(200, quota_body(), "application/json; charset=utf-8")
            except Exception as exc:  # keep the page alive when collection fails
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self._send(500, body, "application/json; charset=utf-8")
        elif path in ("/", "/index.html"):
            self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        pass  # quiet: the page polls every 30 seconds


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"quota-dashboard: http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
