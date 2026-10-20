#!/usr/bin/env python3
"""MCP smoke check: real SDK client over Streamable HTTP, one session per role.

For each agent role it initializes a session, prints the negotiated protocol
version and the tool names that role can see, compares them with the expected
A8 matrix, and closes the session (DELETE). It also checks that a missing token
gets 401 and that human/instructor tokens get 403 at the transport.

Tokens are read from a private env file (default .local/role_tokens.env) and
are never printed, logged or placed on a command line. Listing tools does not
spend any run budget; ``--call-state`` additionally calls get_sprint_state once
per role (get_release_status for the application role); this creates one bounded
server-side run per role and is recorded in the event log.

    uv run python scripts/mcp_smoke.py --lab-url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anyio
import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402
from mcp.shared._httpx_utils import create_mcp_http_client  # noqa: E402

from services.lab.config import parse_env_file  # noqa: E402
from services.lab.mcp import visibility_matrix  # noqa: E402

AGENT_VARS = {"coordinator": "TS_COORD_TOKEN", "product_owner": "TS_PO_TOKEN", "developer": "TS_DEV_TOKEN",
              "qa": "TS_QA_TOKEN", "operations": "TS_OPS_TOKEN", "application": "TS_APP_TOKEN"}
REFUSED_VARS = {"human_approver": "TS_APPROVER_TOKEN", "instructor": "TS_INSTRUCTOR_TOKEN",
                "evaluator": "TS_EVALUATOR_TOKEN"}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}}}
ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def check_role(url: str, token: str, workspace: str, call_state: bool) -> tuple[str, list[str], str]:
    headers = {"Authorization": f"Bearer {token}", "X-TaskSprint-Workspace": workspace}
    async with create_mcp_http_client(headers=headers) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                names = [t.name for t in (await session.list_tools()).tools]
                note = ""
                if call_state:
                    tool = "get_sprint_state" if "get_sprint_state" in names else "get_release_status"
                    res = await session.call_tool(tool, {})
                    sc = res.structuredContent or {}
                    note = (f"{tool} ok, budget %s/%s" % (sc["budget"]["actions_used"], sc["budget"]["max_actions"])
                            if not res.isError else f"{tool} error " + sc.get("error", {}).get("code", "?"))
                return init.protocolVersion, names, note


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lab-url", default="http://127.0.0.1:8000")
    ap.add_argument("--tokens-file", default=str(REPO_ROOT / ".local" / "role_tokens.env"))
    ap.add_argument("--workspace", default="demo-001")
    ap.add_argument("--call-state", action="store_true", help="also call one read-only tool per role")
    args = ap.parse_args()
    url = args.lab_url.rstrip("/") + "/mcp"
    tokens = parse_env_file(Path(args.tokens_file))
    expected = visibility_matrix()
    failures = 0

    try:
        r = httpx.post(url, json=INIT, headers={**ACCEPT, "X-TaskSprint-Workspace": args.workspace}, timeout=10)
    except httpx.HTTPError as exc:
        print(f"FAIL lab not reachable at {url} ({type(exc).__name__})")
        print("RESULT FAIL (1)")
        return 1
    status = "PASS" if r.status_code == 401 else "FAIL"
    failures += status == "FAIL"
    print(f"{status} no token -> HTTP {r.status_code}")
    for role, var in REFUSED_VARS.items():
        if var not in tokens:
            print(f"SKIP {role}: {var} not in tokens file")
            continue
        r = httpx.post(url, json=INIT, headers={**ACCEPT, "Authorization": f"Bearer {tokens[var]}",
                                                "X-TaskSprint-Workspace": args.workspace}, timeout=10)
        status = "PASS" if r.status_code == 403 else "FAIL"
        failures += status == "FAIL"
        print(f"{status} {role} token refused at /mcp -> HTTP {r.status_code}")

    for role, var in AGENT_VARS.items():
        if var not in tokens:
            print(f"SKIP {role}: {var} not in tokens file")
            failures += 1
            continue
        try:
            version, names, note = anyio.run(check_role, url, tokens[var], args.workspace, args.call_state)
        except BaseException as exc:  # noqa: BLE001 - report the failure class only, never headers
            print(f"FAIL {role}: could not open an MCP session ({type(exc).__name__})")
            failures += 1
            continue
        status = "PASS" if names == expected[role] else "FAIL"
        failures += status == "FAIL"
        print(f"{status} {role} protocol {version}: {len(names)} tools: {', '.join(names)}" + (f" [{note}]" if note else ""))
    print("RESULT", "PASS" if failures == 0 else f"FAIL ({failures})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
