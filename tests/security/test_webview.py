"""Phase 13: the static To-do web view (GET /app) is public, holds no secret, and adds no data access."""
from __future__ import annotations

import re
import sqlite3

from services.lab import webview
from services.lab.auth import PERMISSIONS, PUBLIC_ROUTES, WEBVIEW_ROUTES
from services.lab.config import Settings
from services.lab.mcp import CATALOG
from tests.conftest import FAKE_RUNNER_TOKEN, FAKE_TOKENS, headers
from tests.security.test_deny_by_default import business_routes

STATIC_FILES = ("app.html", "app.js", "app.css")
# Credential-shaped patterns (the bundle/redaction scanners' families, made strict enough not to match the
# page's own 'Bearer ' + variable concatenation).
CREDENTIAL_PATTERNS = [
    re.compile(r"ts_[a-z]+_[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-.=]{16,}"),
    re.compile(r"x-api-key\s*[\"':=]", re.I),
    re.compile(r"\b[0-9a-f]{40,}\b"),
    re.compile(r"[A-Za-z0-9_\-+/=]{32,}"),
    re.compile(r"(password|secret|api[_-]?key)\s*[:=]\s*[\"'][^\"']+[\"']", re.I),
]


def _text(name: str) -> str:
    return (webview.STATIC_DIR / name).read_text(encoding="utf-8")


def test_app_page_is_public_with_strict_csp(seeded):
    for path in ("/app", "/app/"):
        r = seeded.client.get(path)  # no Authorization header
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/html")
        csp = r.headers["content-security-policy"]
        assert csp == webview.CSP
        assert "default-src 'self'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert '<meta http-equiv="Content-Security-Policy" content="default-src \'self\';' in r.text
        assert "TaskSprint To-do" in r.text and "workshop-v1.1" in r.text
    for path, kind in (("/app/app.js", "text/javascript"), ("/app/app.css", "text/css")):
        r = seeded.client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith(kind)
        assert r.headers["content-security-policy"] == webview.CSP


def test_served_bytes_contain_no_token_like_strings(seeded):
    secrets = list(FAKE_TOKENS.values()) + [FAKE_RUNNER_TOKEN]
    for path in ("/app", "/app/", "/app/app.js", "/app/app.css"):
        body = seeded.client.get(path).text
        assert not [s for s in secrets if s in body], path
        hits = [p.pattern for p in CREDENTIAL_PATTERNS if p.search(body)]
        assert hits == [], (path, hits)


def test_static_files_contain_no_credential_pattern_or_external_resource():
    for name in STATIC_FILES:
        text = _text(name)
        hits = [p.pattern for p in CREDENTIAL_PATTERNS if p.search(text)]
        assert hits == [], (name, hits)
        assert not re.search(r"https?://", text), f"{name} references an external URL"
        assert "@import" not in text and "@font-face" not in text and "fonts.g" not in text


def test_page_has_no_inline_code_and_masks_the_token():
    html = _text("app.html")
    assert not re.search(r"\son[a-z]+\s*=", html, re.I), "inline event handler"
    assert "<style" not in html.lower()
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.I | re.S)
    assert scripts and all('src="/app/' in attrs and body.strip() == "" for attrs, body in scripts)
    assert "javascript:" not in html.lower()
    token_input = re.search(r"<input[^>]*id=\"token\"[^>]*>", html).group(0)
    assert 'type="password"' in token_input and 'autocomplete="off"' in token_input
    assert "value=" not in token_input


def test_token_is_kept_only_in_session_storage():
    js = _text("app.js")
    assert "sessionStorage" in js
    for forbidden in ("localStorage", "document.cookie", "indexedDB", "location.hash", "location.search",
                      "history.pushState", "innerHTML", "outerHTML", "eval(", "new Function", "console."):
        assert forbidden not in js, forbidden
    # The token travels only in the Authorization header, and every request is same-origin and cookie-free.
    assert "'Authorization': 'Bearer ' + token" in js
    assert "credentials: 'omit'" in js


def test_page_uses_only_existing_application_role_routes():
    js = _text("app.js")
    paths = set(re.findall(r"'(/v1/[a-z0-9/\-]+)'", js))
    assert paths == {"/v1/app/commands", "/v1/releases"}
    assert "application" in PERMISSIONS[("POST", "/v1/app/commands")]
    assert "application" in PERMISSIONS[("GET", "/v1/releases")]
    # The page's commands are the App Console grammar; the workspace header is demo-001.
    for cmd in ("command('list')", "command('status')", "'add ' + title", "'complete ' + t.id"):
        assert cmd in js
    assert "'X-TaskSprint-Workspace': WORKSPACE" in js and "var WORKSPACE = 'demo-001';" in js


def test_webview_routes_add_no_permission_or_mcp_tool():
    assert set(WEBVIEW_ROUTES) <= set(PUBLIC_ROUTES)
    assert not [k for k in PERMISSIONS if k[1].startswith("/app")]
    assert not [t.name for t in CATALOG if t.route and t.route[1].startswith("/app")]
    # The MCP host allowlist default is unchanged by Phase 13.
    assert Settings(db_path=":memory:").mcp_allowed_hosts == ("127.0.0.1:*", "localhost:*", "[::1]:*")


def test_business_routes_still_require_a_token(seeded):
    routes = business_routes(seeded.app)
    assert ("POST", "/v1/app/commands") in routes and ("GET", "/v1/releases") in routes
    assert not [r for r in routes if r[1].startswith("/app")]
    for method, path in (("POST", "/v1/app/commands"), ("GET", "/v1/releases"), ("GET", "/v1/app-health"),
                         ("GET", "/v1/state")):
        r = seeded.client.request(method, path, json={"command": "list"} if method == "POST" else None,
                                  headers={"X-TaskSprint-Workspace": "demo-001"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED", path
    assert seeded.client.get("/app/app.py").status_code == 404
    assert seeded.client.get("/app/../services/lab/auth.py").status_code == 404


def test_page_poll_calls_work_with_the_application_token_and_write_no_events(seeded):
    conn = sqlite3.connect(seeded.db_path)
    before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    h = headers("application")
    lst = seeded.client.post("/v1/app/commands", json={"command": "list"}, headers=h)
    st = seeded.client.post("/v1/app/commands", json={"command": "status"}, headers=h)
    rel = seeded.client.get("/v1/releases", headers=h)
    assert lst.status_code == st.status_code == rel.status_code == 200
    assert [t["id"] for t in lst.json()["data"]["tasks"]] == ["T001", "T002"]
    assert st.json()["data"]["status"] == "healthy" and "FEATURE_UNAVAILABLE" in st.json()["data"]["features"]["complete"]
    assert rel.json()["active"]["candidate_id"] == st.json()["data"]["active_candidate_id"]
    after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    assert after == before, "polling list/status/releases must not write audit events"
    # The v0 refusal the page shows on Complete.
    r = seeded.client.post("/v1/app/commands", json={"command": "complete T001"}, headers=h)
    assert r.status_code == 200 and r.json()["code"] == "FEATURE_UNAVAILABLE" and r.json()["ok"] is False
