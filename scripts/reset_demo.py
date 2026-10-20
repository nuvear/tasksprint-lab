#!/usr/bin/env python3
"""Preview or apply the A12 reset of ONE designated demo workspace (Architecture A12, A13).

A thin wrapper over the lab's instructor actions `reset_preview` / `reset_confirm` (the same actions the
TS-90 commands `reset preview` and `reset confirm WORKSPACE` send). The lab exports the workspace's evidence,
clears drill/outage/stop flags, cancels open plans, unused approvals and live runs, deletes stories and saved
preferences, reseeds T001/T002, restores v0 as the active artifact if needed and advances the generation.
Append-only evidence (candidates, test runs, plans, approvals, releases, events) and every other workspace
are kept. Nothing in Langflow is touched.

  uv run python scripts/reset_demo.py --workspace demo-001 --dry-run
  uv run python scripts/reset_demo.py --workspace demo-001 --confirm demo-001
  uv run python scripts/reset_demo.py --workspace demo-001 --dry-run \
      --lab-url https://<lab-domain> --tokens-file .local/railway/role_tokens.env

Without --lab-url the in-process lab (.local/lab.env) is used, like seed_demo.py. The instructor token is read
from the tokens file and never printed. --confirm must repeat --workspace exactly. Exit 0 on success.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
WORKSPACE_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def summary(action: str, body: dict) -> str:
    if action == "reset_preview":
        p = body.get("pending") or {}
        return (f"PREVIEW {body.get('workspace_id')} generation {body.get('generation')} stopped={body.get('stopped')} "
                f"counts={json.dumps(body.get('counts'), sort_keys=True)} live_runs={len(p.get('active_runs', []))} "
                f"open_plans={p.get('open_plans', [])} active_approvals={p.get('active_approvals', [])} "
                f"drills={len(p.get('enabled_drills', []))}\nWOULD " + "; ".join(body.get("would_do", [])))
    ex = body.get("export") or {}
    return (f"RESET {body.get('workspace_id')} -> generation {body.get('generation')}; export {ex.get('export_id')} "
            f"sha256 {ex.get('export_sha256')}; cancelled {json.dumps(body.get('cancelled'), sort_keys=True)}; "
            f"restored v0 release {body.get('restored_v0_release_id')}; tasks {body.get('tasks_seeded')}; "
            f"event {body.get('event_id')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", required=True, help="designated workspace id, e.g. demo-001")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="preview counts and pending work (no change)")
    mode.add_argument("--confirm", metavar="WORKSPACE", help="apply the reset; must repeat --workspace")
    ap.add_argument("--env-file", default=str(REPO_ROOT / ".local" / "lab.env"))
    ap.add_argument("--tokens-file", default=str(REPO_ROOT / ".local" / "role_tokens.env"))
    ap.add_argument("--lab-url", default=None, help="deployed lab base URL (https://host); omit for in-process")
    ap.add_argument("--json", action="store_true", help="also print the full (token-free) lab response")
    a = ap.parse_args(argv)
    if not a.workspace or set(a.workspace) - WORKSPACE_CHARS or len(a.workspace) < 3:
        print("ERROR: --workspace is not a valid workspace id", file=sys.stderr)
        return 2
    if a.confirm is not None and a.confirm != a.workspace:
        print(f"ERROR: --confirm must repeat the workspace exactly ({a.workspace}); nothing was sent", file=sys.stderr)
        return 2
    action = "reset_preview" if a.dry_run else "reset_confirm"
    payload = {"action": action, "workspace_id": a.workspace, **({"confirm": a.confirm} if a.confirm else {})}

    from services.lab.config import parse_env_file
    try:
        token = parse_env_file(Path(a.tokens_file)).get("TS_INSTRUCTOR_TOKEN", "")
    except OSError as exc:
        print(f"ERROR: tokens file unavailable ({type(exc).__name__}).", file=sys.stderr)
        return 2
    if not token:
        print("ERROR: TS_INSTRUCTOR_TOKEN missing from the tokens file.", file=sys.stderr)
        return 2
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "reset_demo"}

    if a.lab_url is None:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from fastapi.testclient import TestClient
        from services.lab.config import ConfigError, load_settings
        from services.lab.main import create_app
        try:
            settings = load_settings({**os.environ, "TASKSPRINT_ENV_FILE": a.env_file})
        except ConfigError as exc:
            print(f"ERROR: configuration unavailable ({type(exc).__name__}). Run scripts/local_init.py first.",
                  file=sys.stderr)
            return 2
        resp = TestClient(create_app(settings)).post("/v1/instructor/actions", json=payload, headers=headers)
        code, body = resp.status_code, resp.json()
    else:
        import httpx
        u = urlparse(a.lab_url)
        host = u.hostname or ""
        try:
            loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if u.scheme not in ("http", "https") or not host or u.path not in ("", "/") or u.query or \
                (u.scheme != "https" and not loopback):
            print("ERROR: --lab-url must be https://host with no path (http only for loopback)", file=sys.stderr)
            return 2
        try:
            resp = httpx.post(a.lab_url.rstrip("/") + "/v1/instructor/actions", json=payload, headers=headers,
                              timeout=60, trust_env=False)
        except httpx.HTTPError as exc:
            print(f"ERROR: lab unreachable ({type(exc).__name__}).", file=sys.stderr)
            return 1
        code = resp.status_code
        try:
            body = resp.json()
        except ValueError:
            print(f"HTTP {code} (non-JSON response)")
            return 1
    print(f"HTTP {code}")
    if code >= 400:
        e = body.get("error") or {}
        print(f"NOT DONE: {e.get('code')} {e.get('message')} [{e.get('request_id')}]")
        return 1
    print(summary(action, body))
    if a.json:
        print(json.dumps(body, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
