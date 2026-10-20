#!/usr/bin/env python3
"""Read-only Langflow health/schema probe. No login or provisioning operations.

Uses only the Python standard library. Credentials are never printed or saved.
Run with --auth only after creating a separate bootstrap API key privately.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 16 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward authentication to an unexpected destination.
        return None


def get_json(base: str, path: str, api_key: str | None) -> tuple[dict, object | None]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    request = Request(base + path, headers=headers, method="GET")
    opener = build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            body = response.read(MAX_BYTES + 1)
            status = response.status
            content_type = response.headers.get("Content-Type", "")
        if len(body) > MAX_BYTES:
            return {"path": path, "status": status, "result": "response_too_large"}, None
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = None
        return {"path": path, "status": status, "content_type": content_type,
                "result": "json" if parsed is not None else "non_json"}, parsed
    except HTTPError as exc:
        label = "authentication_required" if exc.code in (401, 403) else "http_error"
        return {"path": path, "status": exc.code, "result": label}, None
    except (URLError, TimeoutError, OSError):
        # Do not echo exception content that could contain request details.
        return {"path": path, "status": None, "result": "connection_failed"}, None


def save_private_json(path: Path, value: object) -> None:
    # Replace only the probe's own output files, never existing credentials.
    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    if os.name != "nt":
        path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://langflow-railway-production-f493.up.railway.app")
    parser.add_argument("--auth", action="store_true",
                        help="Privately read a new bootstrap API key; never an admin password")
    parser.add_argument("--output", type=Path, default=Path(".local/preflight"))
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    parts = urlsplit(base)
    if parts.username or parts.password or parts.query or parts.fragment or parts.path:
        parser.error("Use a base origin only, with no credentials, path, query or fragment.")
    if parts.scheme != "https" and not (
        parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        parser.error("HTTPS is required, except for an explicitly local development host.")
    if not parts.hostname:
        parser.error("A host is required.")
    key = None
    if args.auth:
        key = os.environ.get("LANGFLOW_BOOTSTRAP_KEY") or getpass.getpass(
            "New Langflow bootstrap API key (private input; NOT your admin password): "
        ).strip()
        if not key:
            parser.error("No API key supplied; rerun without --auth for an unauthenticated probe.")
    args.output.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        args.output.chmod(0o700)
    results = []
    health, _ = get_json(base, "/health_check", key)
    results.append(health)
    schema_result, schema = get_json(base, "/openapi.json", key)
    results.append(schema_result)
    schema_info = None
    if isinstance(schema, dict) and isinstance(schema.get("paths"), dict):
        save_private_json(args.output / "langflow-openapi.json", schema)
        paths = schema["paths"]
        schema_info = {
            "api_title": schema.get("info", {}).get("title"),
            "api_schema_version": schema.get("info", {}).get("version"),
            "note": "API schema version is not proof of the installed image/component version.",
            "matching_paths": {name: [p for p in paths if token in p.lower()]
                               for name, token in [("a2a", "a2a"), ("mcp", "mcp"),
                                                   ("flows", "flows"), ("variables", "variables"),
                                                   ("run", "/run"), ("version", "version")]},
        }
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base, "read_only": True, "credentials_saved": False,
        "requests": results, "schema": schema_info,
        "not_verified": ["UI component fields", "actual model/tool behavior", "A2A publication/auth",
                         "MCP connection", "HITL behavior", "import/export round trip",
                         "Railway configuration", "application backend readiness"],
    }
    save_private_json(args.output / "report.json", report)
    print(f"Read-only report: {args.output / 'report.json'}")
    for result in results:
        print(f"{result['path']}: {result['status']} / {result['result']}")
    if schema_info:
        print("Schema saved. Verify the installed version and component fields in the UI.")
    else:
        print("Schema unavailable. Record the blocker; do not disable authentication.")
    print("No flows, keys, variables, services or data were changed.")
    return 0 if health.get("status") == 200 else 2


if __name__ == "__main__":
    sys.exit(main())
