#!/usr/bin/env python3
"""Check a running TaskSprint stack (Architecture A13; Build Guide 03.4 and 05.5).

  uv run python scripts/check_stack.py --target local
  uv run python scripts/check_stack.py --target railway --base-url https://<lab-domain> \\
      --env-file .local/railway/role_tokens.env [--snapshot save|verify]

--target local (Phase 03; read-only except one recorded app.complete event):
  1. lab /healthz is up and minimal
  2. the runner is NOT reachable from this host at --runner-probe (it must be private)
  3. an unauthenticated business request is refused (401)
  4. with the application token from --tokens-file: `status` reports business health
  5. with the application token: `complete T999` is answered by the bounded runner
     (on v0 this returns FEATURE_UNAVAILABLE and changes nothing; it records one
     app.complete event)

--target railway (Phase 05.5) adds, over HTTPS:
  * /healthz without a token = 200 and minimal; business routes without a token or with
    an invalid token = 401; /mcp without a token = 401
  * MCP initialize with the coordinator token is accepted (not 421: the lab's
    TASKSPRINT_MCP_ALLOWED_HOSTS lists this host); the session is closed again
  * coordinator reads canonical state; application status and the lab -> runner path
    over Railway private networking (`complete T999`, as above)
  * --snapshot save: records non-secret identifiers (newest event IDs, task list, active
    release hash) in a private file (0600) BEFORE you redeploy the lab;
    --snapshot verify: after the redeploy, proves those records survived on the /data
    volume. Verify runs before any check that writes.
  The runner has no public address to probe: confirm in the Railway UI that
  tasksprint-runner has no public domain (printed as NOTE, not counted).

Token values are read from the private file and never printed. Exit status:
0 all checks PASS (SKIPs allowed only with --allow-skip), 1 a check failed,
2 configuration error.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "tasksprint-check-stack", "version": "1"}}}
MCP_ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INVALID_TOKEN = "ts_invalid_" + "0" * 40  # well-formed, never issued


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def tcp_reachable(hostport: str, timeout: float) -> bool:
    host, _, port = hostport.rpartition(":")
    try:
        with socket.create_connection((host or "127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def write_private_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(data, indent=2, sort_keys=True).encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class Results:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def record(self, status: str, name: str, detail: str) -> None:
        self.items.append((status, name, detail))
        print(f"{status:4} {name}: {detail}")

    def summary(self, allow_skip: bool) -> int:
        failed = [n for s, n, _ in self.items if s == "FAIL"]
        skipped = [n for s, n, _ in self.items if s == "SKIP"]
        passed = sum(1 for s, _, _ in self.items if s == "PASS")
        print(f"SUMMARY: {passed} pass, {len(failed)} fail, {len(skipped)} skip")
        if failed:
            return 1
        return 0 if (not skipped or allow_skip) else 1


def check_liveness(client: httpx.Client, res: Results) -> bool:
    try:
        r = client.get("/healthz")
        ok = r.status_code == 200 and r.json() == {"status": "ok", "service": "tasksprint-lab"}
        res.record("PASS" if ok else "FAIL", "lab liveness without a token", f"GET /healthz -> {r.status_code}")
        return True
    except (httpx.HTTPError, ValueError) as exc:
        res.record("FAIL", "lab liveness without a token", f"unreachable ({type(exc).__name__})")
        return False


def check_app_paths(client: httpx.Client, res: Results, app_token: str, workspace: str) -> None:
    if not app_token:
        res.record("SKIP", "application status", "no TS_APP_TOKEN in the tokens file")
        res.record("SKIP", "lab -> runner path", "no TS_APP_TOKEN in the tokens file")
        return
    hdrs = {"Authorization": f"Bearer {app_token}", "X-TaskSprint-Workspace": workspace}
    r = client.post("/v1/app/commands", json={"command": "status"}, headers=hdrs)
    if r.status_code == 404:
        res.record("SKIP", "application status", f"workspace {workspace} not seeded")
        res.record("SKIP", "lab -> runner path", f"workspace {workspace} not seeded")
        return
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    health = (body.get("data") or {}).get("status")
    res.record("PASS" if r.status_code == 200 and health == "healthy" else "FAIL", "application status",
               f"-> {r.status_code}, business health {health}")
    r = client.post("/v1/app/commands", json={"command": "complete T999"}, headers=hdrs)
    data = (r.json().get("data") or {}) if r.status_code == 200 else {}
    ev = data.get("evaluation") or {}
    ok = r.status_code == 200 and str(ev.get("evaluated_by", "")).startswith("tasksprint-runner/") \
        and data.get("tasks_changed") == 0
    res.record("PASS" if ok else "FAIL", "lab -> runner path",
               f"-> {r.status_code}, code {r.json().get('code') if r.status_code == 200 else None}, "
               f"runner {ev.get('evaluated_by')}, ops {ev.get('ops')}")


def take_snapshot(client: httpx.Client, coord: dict[str, str], app: dict[str, str]) -> dict[str, Any] | str:
    """Non-secret identifiers that only survive if the database file survived."""
    r = client.get("/v1/events", params={"limit": 50}, headers=coord)
    if r.status_code != 200:
        return f"GET /v1/events -> {r.status_code}"
    event_ids = [e["event_id"] for e in r.json().get("events", [])]
    if not event_ids:
        return "no events recorded yet in this workspace"
    r = client.get("/v1/state", headers=coord)
    if r.status_code != 200:
        return f"GET /v1/state -> {r.status_code}"
    release = r.json().get("release") or {}
    r = client.post("/v1/app/commands", json={"command": "list"}, headers=app)
    if r.status_code != 200:
        return f"app list -> {r.status_code}"
    tasks = (r.json().get("data") or {}).get("tasks", [])
    return {"event_ids": event_ids, "active_sha256": release.get("active_sha256"),
            "tasks": [{"id": t.get("id"), "title": t.get("title"), "completed": t.get("completed")} for t in tasks]}


def railway_checks(args: argparse.Namespace, client: httpx.Client, res: Results) -> None:
    ws = args.workspace
    r = client.get("/v1/state", headers={"X-TaskSprint-Workspace": ws})
    res.record("PASS" if r.status_code == 401 else "FAIL", "business route without a token refused",
               f"GET /v1/state -> {r.status_code}")
    r = client.post("/v1/app/commands", json={"command": "status"}, headers={"X-TaskSprint-Workspace": ws})
    res.record("PASS" if r.status_code == 401 else "FAIL", "write route without a token refused",
               f"POST /v1/app/commands -> {r.status_code}")
    r = client.get("/v1/state", headers={"X-TaskSprint-Workspace": ws, "Authorization": f"Bearer {INVALID_TOKEN}"})
    res.record("PASS" if r.status_code == 401 else "FAIL", "invalid token refused", f"GET /v1/state -> {r.status_code}")
    r = client.post("/mcp", json=MCP_INIT, headers={**MCP_ACCEPT, "X-TaskSprint-Workspace": ws})
    res.record("PASS" if r.status_code == 401 else "FAIL", "/mcp without a token refused", f"-> {r.status_code}")

    tokens_path = Path(args.env_file)
    tokens = read_env(tokens_path) if tokens_path.is_file() else {}
    coord_token, app_token = tokens.get("TS_COORD_TOKEN", ""), tokens.get("TS_APP_TOKEN", "")
    if not tokens:
        res.record("SKIP", "authenticated checks", f"tokens file {tokens_path.name} not found")
        return
    coord = {"Authorization": f"Bearer {coord_token}", "X-TaskSprint-Workspace": ws}
    app = {"Authorization": f"Bearer {app_token}", "X-TaskSprint-Workspace": ws}

    snap_path = Path(args.snapshot_file) if args.snapshot_file else tokens_path.parent / "railway_snapshot.json"
    if args.snapshot == "verify":
        if not snap_path.is_file():
            res.record("FAIL", "volume persistence after redeploy", f"no saved snapshot at {snap_path.name}")
        else:
            saved = json.loads(snap_path.read_text(encoding="utf-8"))
            now = take_snapshot(client, coord, app)
            if isinstance(now, str):
                res.record("FAIL", "volume persistence after redeploy", now)
            else:
                newest = saved["event_ids"][0]
                ok = newest in now["event_ids"] and now["tasks"] == saved["tasks"] \
                    and now["active_sha256"] == saved["active_sha256"]
                res.record("PASS" if ok else "FAIL", "volume persistence after redeploy",
                           f"saved newest event {'present' if newest in now['event_ids'] else 'MISSING'}; "
                           f"{len(now['tasks'])} tasks {'unchanged' if now['tasks'] == saved['tasks'] else 'CHANGED'}; "
                           f"active release {'unchanged' if now['active_sha256'] == saved['active_sha256'] else 'CHANGED'}")

    if not coord_token:
        res.record("SKIP", "MCP host allowlist", "no TS_COORD_TOKEN in the tokens file")
    else:
        r = client.post("/mcp", json=MCP_INIT, headers={**MCP_ACCEPT, **coord})
        sid = r.headers.get("mcp-session-id")
        hint = " (add this host to TASKSPRINT_MCP_ALLOWED_HOSTS and redeploy the lab)" if r.status_code == 421 else ""
        res.record("PASS" if r.status_code == 200 and sid else "FAIL", "MCP initialize accepted for this host",
                   f"-> {r.status_code}{hint}")
        if sid:
            client.delete("/mcp", headers={**coord, "Mcp-Session-Id": sid})
        r = client.get("/v1/state", headers=coord)
        if r.status_code == 404:
            res.record("SKIP", "authenticated state read", f"workspace {ws} not seeded (scripts/seed_demo.py --lab-url)")
        else:
            res.record("PASS" if r.status_code == 200 and r.json().get("record_type") == "canonical_sprint_state"
                       else "FAIL", "authenticated state read (coordinator)", f"-> {r.status_code}")
    check_app_paths(client, res, app_token, ws)

    if args.snapshot == "save":
        snap = take_snapshot(client, coord, app) if coord_token and app_token else "coordinator/application token missing"
        if isinstance(snap, str):
            res.record("FAIL", "persistence snapshot saved", snap)
        else:
            write_private_json(snap_path, snap)
            res.record("PASS", "persistence snapshot saved",
                       f"{snap_path.name}: {len(snap['event_ids'])} event IDs, {len(snap['tasks'])} tasks "
                       "(no secrets). Now redeploy the lab and run --snapshot verify")
    print("NOTE runner exposure: not testable from outside; confirm tasksprint-runner has no public domain "
          "in the Railway UI (Settings -> Networking)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", required=True, choices=["local", "railway"])
    p.add_argument("--base-url", "--lab-url", dest="base_url", default=None,
                   help="lab base URL (local default http://127.0.0.1:8000; railway: https://<lab-domain>)")
    p.add_argument("--runner-probe", default="127.0.0.1:8001",
                   help="local only: host:port where the runner must NOT be reachable")
    p.add_argument("--env-file", "--tokens-file", dest="env_file", default=None,
                   help="private role-token file (local default .local/role_tokens.env; "
                        "railway default .local/railway/role_tokens.env); values are never printed")
    p.add_argument("--workspace", default="demo-001")
    p.add_argument("--snapshot", choices=["save", "verify"], default=None, help="railway only: persistence proof")
    p.add_argument("--snapshot-file", default=None,
                   help="railway only: default <env-file folder>/railway_snapshot.json (0600, no secrets)")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--allow-skip", action="store_true", help="exit 0 even if some checks were skipped")
    p.add_argument("--allow-http-loopback", action="store_true", help=argparse.SUPPRESS)  # tests only
    args = p.parse_args(argv)

    if args.base_url is None:
        args.base_url = "http://127.0.0.1:8000" if args.target == "local" else ""
    if args.env_file is None:
        sub = ".local/role_tokens.env" if args.target == "local" else ".local/railway/role_tokens.env"
        args.env_file = str(REPO_ROOT / sub)
    url = urlparse(args.base_url)
    if url.scheme not in ("http", "https") or not url.hostname or url.path not in ("", "/") or url.query:
        print("ERROR: --base-url must be http(s)://host[:port] with no path", file=sys.stderr)
        return 2
    if args.target == "railway" and url.scheme != "https" and not (args.allow_http_loopback and is_loopback(url.hostname)):
        print("ERROR: --target railway requires an https:// lab URL", file=sys.stderr)
        return 2
    if args.target == "local" and args.snapshot:
        print("ERROR: --snapshot is only available with --target railway", file=sys.stderr)
        return 2
    if not 0 < args.timeout <= 30:
        print("ERROR: --timeout must be in (0, 30]", file=sys.stderr)
        return 2

    res = Results()
    client = httpx.Client(base_url=args.base_url.rstrip("/"), timeout=args.timeout, trust_env=False)
    try:
        if not check_liveness(client, res):
            return 1
        if args.target == "railway":
            railway_checks(args, client, res)
        else:
            reachable = tcp_reachable(args.runner_probe, min(args.timeout, 2.0))
            res.record("FAIL" if reachable else "PASS", "runner not exposed to host",
                       f"{args.runner_probe} {'accepted a TCP connection' if reachable else 'refused/unreachable'}")
            r = client.get("/v1/state", headers={"X-TaskSprint-Workspace": args.workspace})
            res.record("PASS" if r.status_code == 401 else "FAIL", "unauthenticated request refused",
                       f"-> {r.status_code}")
            tokens_path = Path(args.env_file)
            app_token = read_env(tokens_path).get("TS_APP_TOKEN", "") if tokens_path.is_file() else ""
            check_app_paths(client, res, app_token, args.workspace)
    except httpx.HTTPError as exc:
        res.record("FAIL", "transport", f"{type(exc).__name__}")
    finally:
        client.close()
    return res.summary(args.allow_skip)


if __name__ == "__main__":
    sys.exit(main())
