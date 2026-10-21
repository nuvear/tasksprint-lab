"""Phase 13: the production web view of the To-do app (``GET /app``), for the projector.

The page (``static/app.html`` + ``app.js`` + ``app.css``) is public to fetch because it holds no data and no
secret. Every data call it makes is an existing application-role route (``POST /v1/app/commands`` with
list/status/add/complete, ``GET /v1/releases``) and needs the application token, which the viewer pastes once
into a masked field; the page keeps it only in that tab's ``sessionStorage``. No new data route is added.

The files are read once at start-up into memory and served from a fixed table (no path parameter, so no
traversal). Responses carry a strict Content-Security-Policy (scripts and styles from this origin only, no
inline code, no framing) and ``Cache-Control: no-store``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import Response

from .auth import WEBVIEW_ROUTES

STATIC_DIR = Path(__file__).resolve().parent / "static"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
       "base-uri 'none'; form-action 'none'; object-src 'none'; frame-ancestors 'none'")
ASSETS: dict[str, tuple[str, str]] = {
    "/app": ("app.html", "text/html; charset=utf-8"),
    "/app/": ("app.html", "text/html; charset=utf-8"),
    "/app/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app/app.css": ("app.css", "text/css; charset=utf-8"),
}
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}
assert {("GET", p) for p in ASSETS} == set(WEBVIEW_ROUTES), "webview routes must equal auth.WEBVIEW_ROUTES"


def _endpoint(body: bytes, media_type: str) -> Callable[[], Response]:
    def serve() -> Response:
        return Response(content=body, media_type=media_type, headers=dict(SECURITY_HEADERS))
    return serve


def register(app: FastAPI) -> None:
    files = {name: (STATIC_DIR / name).read_bytes() for name, _ in ASSETS.values()}
    for path, (name, media_type) in ASSETS.items():
        app.add_api_route(path, _endpoint(files[name], media_type), methods=["GET"], include_in_schema=False)
