#!/usr/bin/env python3
"""Check a running TaskSprint stack without changing it (Architecture A13, Build Guide 03.4).

  uv run python scripts/check_stack.py --target local

Checks (each prints PASS, FAIL or SKIP; a SKIP is never counted as a pass):
  1. lab /healthz is up and minimal
  2. the runner is NOT reachable from this host at --runner-probe (it must be private)
  3. an unauthenticated business request is refused (401)
  4. with the application token from --tokens-file: `status` reports business health
  5. with the application token: `complete T999` is answered by the bounded runner
     (on v0 this returns FEATURE_UNAVAILABLE and changes nothing; it records one
     app.complete event)

Token values are read from the private file and never printed. Exit status:
0 all checks PASS (SKIPs allowed only with --allow-skip), 1 a check failed,
2 configuration error.
"""
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", required=True, choices=["local"], help="only 'local' exists in Phase 03")
    p.add_argument("--lab-url", default="http://127.0.0.1:8000")
    p.add_argument("--runner-probe", default="127.0.0.1:8001",
                   help="host:port where the runner must NOT be reachable (default: compose's internal port)")
    p.add_argument("--tokens-file", default=str(REPO_ROOT / ".local" / "role_tokens.env"))
    p.add_argument("--workspace", default="demo-001")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--allow-skip", action="store_true", help="exit 0 even if some checks were skipped")
    args = p.parse_args(argv)

    url = urlparse(args.lab_url)
    if url.scheme not in ("http", "https") or not url.hostname or url.path not in ("", "/"):
        print("ERROR: --lab-url must be http(s)://host[:port]", file=sys.stderr)
        return 2
    if not 0 < args.timeout <= 30:
        print("ERROR: --timeout must be in (0, 30]", file=sys.stderr)
        return 2
    results: list[tuple[str, str, str]] = []

    def record(status: str, name: str, detail: str) -> None:
        results.append((status, name, detail))
        print(f"{status:4} {name}: {detail}")

    client = httpx.Client(base_url=args.lab_url.rstrip("/"), timeout=args.timeout, trust_env=False)
    try:
        r = client.get("/healthz")
        ok = r.status_code == 200 and r.json() == {"status": "ok", "service": "tasksprint-lab"}
        record("PASS" if ok else "FAIL", "lab liveness", f"GET /healthz -> {r.status_code}")
    except (httpx.HTTPError, ValueError) as exc:
        record("FAIL", "lab liveness", f"unreachable ({type(exc).__name__})")
        return 1

    reachable = tcp_reachable(args.runner_probe, min(args.timeout, 2.0))
    record("FAIL" if reachable else "PASS", "runner not exposed to host",
           f"{args.runner_probe} {'accepted a TCP connection' if reachable else 'refused/unreachable'}")

    r = client.get("/v1/state", headers={"X-TaskSprint-Workspace": args.workspace})
    record("PASS" if r.status_code == 401 else "FAIL", "unauthenticated request refused", f"-> {r.status_code}")

    tokens_path = Path(args.tokens_file)
    app_token = read_env(tokens_path).get("TS_APP_TOKEN", "") if tokens_path.is_file() else ""
    if not app_token:
        record("SKIP", "application status", "no TS_APP_TOKEN in the tokens file")
        record("SKIP", "lab -> runner path", "no TS_APP_TOKEN in the tokens file")
    else:
        hdrs = {"Authorization": f"Bearer {app_token}", "X-TaskSprint-Workspace": args.workspace}
        r = client.post("/v1/app/commands", json={"command": "status"}, headers=hdrs)
        if r.status_code == 404:
            record("SKIP", "application status", f"workspace {args.workspace} not seeded")
            record("SKIP", "lab -> runner path", f"workspace {args.workspace} not seeded")
        else:
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            health = (body.get("data") or {}).get("status")
            record("PASS" if r.status_code == 200 and health == "healthy" else "FAIL", "application status",
                   f"-> {r.status_code}, business health {health}")
            r = client.post("/v1/app/commands", json={"command": "complete T999"}, headers=hdrs)
            data = (r.json().get("data") or {}) if r.status_code == 200 else {}
            ev = data.get("evaluation") or {}
            ok = r.status_code == 200 and str(ev.get("evaluated_by", "")).startswith("tasksprint-runner/") \
                and data.get("tasks_changed") == 0
            record("PASS" if ok else "FAIL", "lab -> runner path",
                   f"-> {r.status_code}, code {r.json().get('code') if r.status_code == 200 else None}, "
                   f"runner {ev.get('evaluated_by')}, ops {ev.get('ops')}")
    client.close()

    failed = [n for s, n, _ in results if s == "FAIL"]
    skipped = [n for s, n, _ in results if s == "SKIP"]
    print(f"SUMMARY: {sum(1 for s, _, _ in results if s == 'PASS')} pass, {len(failed)} fail, {len(skipped)} skip")
    if failed:
        return 1
    return 0 if (not skipped or args.allow_skip) else 1


if __name__ == "__main__":
    sys.exit(main())
