#!/usr/bin/env python3
"""Phase 07 backend-side evidence for the Sprint Room and harness checks (Build Guide 07.3-07.4, Gate 07).

  uv run --frozen --no-dev python scripts/phase07_checks.py events [--since ISO] [--limit 50]
  uv run --frozen --no-dev python scripts/phase07_checks.py state           # GET /v1/state (coordinator)
  uv run --frozen --no-dev python scripts/phase07_checks.py memory          # GET /v1/memory (coordinator)
  uv run --frozen --no-dev python scripts/phase07_checks.py late-write --run-id run_...   # expired-run write probe
  uv run --frozen --no-dev python scripts/phase07_checks.py runs --since ISO  # run lineage from run.create events

Reads (never prints) role tokens from .local/railway/role_tokens.env. Reads are plain REST without a run
header (no budget is consumed). `late-write` is the only mutating probe: it presents an already-issued,
expired coordinator run to the lab and asks for a preference write through the real MCP SDK; the lab
must refuse it (RUN_EXPIRED / RUN_NOT_ACTIVE) and the memory must stay unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anyio
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lf_common import DEFAULT_LAB_URL, DEFAULT_TOKENS_FILE, read_env  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402
from mcp.shared._httpx_utils import create_mcp_http_client  # noqa: E402

WS = "demo-001"


def rest(base: str, token: str, path: str, **params) -> dict:
    r = httpx.get(base + path, params=params or None, timeout=60,
                  headers={"Authorization": f"Bearer {token}", "X-TaskSprint-Workspace": WS})
    r.raise_for_status()
    return r.json()


def compact(e: dict) -> str:
    d = e.get("details") or {}
    keep = {k: d[k] for k in ("tool", "code", "source", "depth", "parent_run_id", "actions_used", "key", "value",
                              "story_id", "test_run_id", "candidate_id", "from", "to", "route") if k in d}
    return (f"{e['created_at']} {e['event_id']} {e['actor_role']:<13} {e['action']:<16} {e['outcome']:<9} "
            f"run={e.get('run_id') or '-'} {json.dumps(keep, sort_keys=True)}")


async def late_write(base: str, token: str, run_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "X-TaskSprint-Workspace": WS, "X-TaskSprint-Run": run_id}
    async with create_mcp_http_client(headers=headers) as http:
        async with streamable_http_client(base + "/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as s:
                await s.initialize()
                res = await s.call_tool("save_preference", {"key": "summary_length", "value": "long"})
                return {"isError": res.isError, "body": res.structuredContent}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=("events", "state", "memory", "late-write", "runs"))
    p.add_argument("--since", default="")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--run-id", default="")
    p.add_argument("--lab-url", default=DEFAULT_LAB_URL)
    p.add_argument("--tokens-file", type=Path, default=DEFAULT_TOKENS_FILE)
    a = p.parse_args(argv)
    t = read_env(a.tokens_file)
    base = a.lab_url.rstrip("/")
    coord = t["TS_COORD_TOKEN"]
    if a.what in ("events", "runs"):
        evs = [e for e in reversed(rest(base, coord, "/v1/events", limit=min(50, a.limit))["events"])
               if e["created_at"] >= a.since]
        if a.what == "runs":
            evs = [e for e in evs if e["action"] == "run.create"]
        for e in evs:
            print(compact(e))
        print(f"COUNT {len(evs)}")
    elif a.what == "state":
        print(json.dumps(rest(base, coord, "/v1/state"), indent=1, sort_keys=True))
    elif a.what == "memory":
        print(json.dumps(rest(base, coord, "/v1/memory"), indent=1, sort_keys=True))
    else:
        before = rest(base, coord, "/v1/memory")["preferences"]
        out = anyio.run(late_write, base, coord, a.run_id)
        after = rest(base, coord, "/v1/memory")["preferences"]
        code = ((out["body"] or {}).get("error") or {}).get("code")
        ok = out["isError"] and code in ("RUN_EXPIRED", "RUN_NOT_ACTIVE") and before == after
        print(f"{'PASS' if ok else 'FAIL'} late write with run {a.run_id[:12]}…: isError={out['isError']} code={code} "
              f"request_id={((out['body'] or {}).get('error') or {}).get('request_id')} memory_unchanged={before == after}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
