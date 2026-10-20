#!/usr/bin/env python3
"""Phase 06 backend-side verification of the Langflow specialist checks (Build Guide 06.5, Gate 06).

  uv run --frozen --no-dev python scripts/phase06_checks.py --candidate-id cand_... --test-run-id tr_... \
      [--since 2026-10-20T11:40:00Z] [--probes]

Reads (never prints) tokens from .local/railway/role_tokens.env and checks, against the deployed lab:
  1. the protected test report: written by the runner for exactly the candidate's hash;
  2. the event log (coordinator read): each specialist's tool calls are recorded under its own
     identity (product_owner: knowledge.search; developer: skill_loaded + candidate.submit;
     qa: test_run), and the To-do App's commands under `application`;
  3. --probes: impersonation attempts with a real MCP SDK client and plain REST, which must be
     denied: developer -> run_candidate_tests / read_test_report, product_owner -> submit_candidate,
     qa -> submit_candidate, an `acting_as`/`role` field on a call, a `X-TaskSprint-Role` header on
     REST, developer GET of the test report. Each probe opens its own MCP session (one recorded
     root run) and records denial events; nothing is mutated.
Exit 0 when every check passes.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import anyio
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lf_common import DEFAULT_LAB_URL, DEFAULT_TOKENS_FILE, read_env  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402
from mcp.shared._httpx_utils import create_mcp_http_client  # noqa: E402

WS = "demo-001"
results: list[tuple[bool, str]] = []


def record(ok: bool, msg: str) -> None:
    results.append((ok, msg))
    print(("PASS " if ok else "FAIL ") + msg)


def rest(base: str, token: str, method: str, path: str, **kw) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}", "X-TaskSprint-Workspace": WS, **kw.pop("headers", {})}
    return httpx.request(method, base + path, headers=headers, timeout=60, **kw)


async def mcp_call(base: str, token: str, tool: str, args: dict) -> tuple[list[str], dict, bool]:
    headers = {"Authorization": f"Bearer {token}", "X-TaskSprint-Workspace": WS}
    async with create_mcp_http_client(headers=headers) as http:
        async with streamable_http_client(base + "/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as s:
                await s.initialize()
                names = [t.name for t in (await s.list_tools()).tools]
                res = await s.call_tool(tool, args)
                return names, res.structuredContent or {}, bool(res.isError)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lab-url", default=DEFAULT_LAB_URL)
    p.add_argument("--tokens-file", type=Path, default=DEFAULT_TOKENS_FILE)
    p.add_argument("--candidate-id", required=True)
    p.add_argument("--test-run-id", required=True)
    p.add_argument("--since", default="", help="only consider events at/after this UTC ISO time")
    p.add_argument("--probes", action="store_true")
    a = p.parse_args(argv)
    t = read_env(a.tokens_file)
    base = a.lab_url.rstrip("/")

    # 1. report ------------------------------------------------------------------------------
    cand = rest(base, t["TS_QA_TOKEN"], "GET", f"/v1/candidates/{a.candidate_id}").json()
    rep = rest(base, t["TS_COORD_TOKEN"], "GET", f"/v1/test-runs/{a.test_run_id}").json()
    cases = rep.get("cases", [])
    failed = [c["case_id"] for c in cases if not c.get("passed")]
    record(rep.get("candidate_id") == a.candidate_id and rep.get("candidate_sha256") == cand.get("sha256"),
           f"report {a.test_run_id} is for {a.candidate_id} sha256 {str(cand.get('sha256'))[:16]}… "
           f"(report says {str(rep.get('candidate_sha256'))[:16]}…)")
    record(bool(rep.get("runner_version")) and bool(rep.get("suite_sha256")),
           f"report written by {rep.get('runner_version')} suite {rep.get('suite_version')} "
           f"{str(rep.get('suite_sha256'))[:16]}… outcome={rep.get('outcome')} "
           f"cases={len(cases)} failed={failed}")
    record(cand.get("origin") == "agent-generated" and cand.get("author_role") == "developer",
           f"candidate provenance origin={cand.get('origin')} author_role={cand.get('author_role')}")

    # 2. events ------------------------------------------------------------------------------
    evs = rest(base, t["TS_COORD_TOKEN"], "GET", "/v1/events", params={"limit": 50}).json()["events"]
    evs = [e for e in evs if e["created_at"] >= a.since]
    by: dict[str, set[str]] = defaultdict(set)
    for e in evs:
        key = e["action"] + (":" + e["details"].get("tool", "") if e["action"] == "mcp.tool_call" else "")
        by[key].add(e["actor_role"])
    expect = {"knowledge.search": {"product_owner", "developer"}, "skill_loaded": {"developer"},
              "candidate.submit": {"developer"}, "mcp.tool_call:run_candidate_tests": {"qa"},
              "mcp.tool_call:search_approved_knowledge": {"product_owner", "developer"},
              "mcp.tool_call:load_skill": {"developer"}, "mcp.tool_call:submit_candidate": {"developer"},
              "app.add": {"application"}, "app.complete": {"application"}}
    for key, roles in expect.items():
        seen = by.get(key, set())
        record(bool(seen) and seen <= roles, f"events {key}: recorded under {sorted(seen) or 'NONE'}")
    print("NOTE events considered:", len(evs), "since", a.since or "(all returned)")

    # 3. probes ------------------------------------------------------------------------------
    if a.probes:
        probes = [("TS_DEV_TOKEN", "run_candidate_tests", {"candidate_id": a.candidate_id}, "TOOL_NOT_AVAILABLE"),
                  ("TS_DEV_TOKEN", "read_test_report", {"test_run_id": a.test_run_id}, "TOOL_NOT_AVAILABLE"),
                  ("TS_PO_TOKEN", "submit_candidate", {"source": "def complete(tasks, task_id):\n    return 1\n"},
                   "TOOL_NOT_AVAILABLE"),
                  ("TS_QA_TOKEN", "submit_candidate", {"source": "def complete(tasks, task_id):\n    return 1\n"},
                   "TOOL_NOT_AVAILABLE"),
                  ("TS_DEV_TOKEN", "read_candidate", {"candidate_id": a.candidate_id, "acting_as": "qa"},
                   "VALIDATION_ERROR"),
                  ("TS_DEV_TOKEN", "submit_candidate", {"source": "def complete(tasks, task_id):\n    return 1\n",
                                                        "role": "qa"}, "VALIDATION_ERROR")]
        for var, tool, args, want in probes:
            try:
                names, sc, is_err = anyio.run(mcp_call, base, t[var], tool, args)
                code = (sc.get("error") or {}).get("code")
                record(is_err and code == want,
                       f"probe {var[3:-6].lower()} -> {tool}{' +' + [k for k in args if k in ('acting_as', 'role')][0] if any(k in args for k in ('acting_as', 'role')) else ''}: "
                       f"{code} (listed={tool in names})")
            except Exception as exc:  # noqa: BLE001
                record(False, f"probe {tool}: client error {type(exc).__name__}")
        r = rest(base, t["TS_DEV_TOKEN"], "GET", f"/v1/test-runs/{a.test_run_id}")
        record(r.status_code == 403, f"REST developer GET /v1/test-runs/{{id}} -> {r.status_code}")
        r = rest(base, t["TS_DEV_TOKEN"], "POST", "/v1/test-runs", json={"candidate_id": a.candidate_id},
                 headers={"X-TaskSprint-Role": "qa"})
        record(r.status_code == 403, f"REST developer POST /v1/test-runs with X-TaskSprint-Role: qa -> {r.status_code}")
        r = rest(base, t["TS_DEV_TOKEN"], "POST", "/v1/test-runs", json={"candidate_id": a.candidate_id, "role": "qa"})
        record(r.status_code in (403, 422), f"REST developer POST /v1/test-runs with body role=qa -> {r.status_code}")
    bad = sum(1 for ok, _ in results if not ok)
    print(f"SUMMARY {len(results) - bad} pass, {bad} fail")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
