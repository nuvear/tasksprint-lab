#!/usr/bin/env python3
"""Register one Langflow MCP server per TaskSprint role (Phase 06; RAILWAY_SETUP.md section 5).

  uv run --frozen --no-dev python scripts/import_mcp_servers.py --dry-run
  uv run --frozen --no-dev python scripts/import_mcp_servers.py --apply [--force] [--roles po,dev,qa,app]

Each server: Streamable HTTP, URL <lab>/mcp, and two headers that contain NO secret:
  Authorization           Bearer {{TS_<ROLE>_TOKEN}}   (a Langflow global-variable placeholder)
  X-TaskSprint-Workspace  demo-001
Langflow 1.12.5 resolves a header value that is exactly a variable name, or a {{NAME}}
placeholder inside a value, from the owner's (decrypted) global variables at connect
time (lfx 1.12.5 base/mcp/util.py _substitute_global_variables). The UI's globe
picker only inserts a whole-value variable chip, which cannot express the required
"Bearer " prefix, so the placeholder form is used; it was first entered by hand in the
Add MCP Server dialog for tasksprint-product-owner and observed to authenticate.

Idempotent: existing servers are kept unless --force (PATCH). Verification: GET
/api/v2/mcp/servers?action_count=true must report the role's exact tool count from the
Phase 04 matrix (a wrong or unresolved token yields 401 and no count).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lf_common import (DEFAULT_BOOTSTRAP_FILE, DEFAULT_LAB_URL, DEFAULT_LANGFLOW_URL, SetupError,  # noqa: E402
                       check, langflow_client)

# key: (server name, credential variable, expected tools/list count from PHASE04_REPORT)
SERVERS = {
    "po": ("tasksprint-product-owner", "TS_PO_TOKEN", 2),
    "dev": ("tasksprint-developer", "TS_DEV_TOKEN", 6),
    "qa": ("tasksprint-qa", "TS_QA_TOKEN", 5),
    "app": ("tasksprint-application", "TS_APP_TOKEN", 2),
    "coord": ("tasksprint-coordinator", "TS_COORD_TOKEN", 7),
    "ops": ("tasksprint-operations", "TS_OPS_TOKEN", 12),
}
WORKSPACE = "demo-001"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--force", action="store_true", help="PATCH existing servers to the canonical config")
    p.add_argument("--roles", default=",".join(SERVERS), help="comma list of " + ",".join(SERVERS))
    p.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    p.add_argument("--lab-url", default=DEFAULT_LAB_URL)
    p.add_argument("--bootstrap-file", type=Path, default=DEFAULT_BOOTSTRAP_FILE)
    a = p.parse_args(argv)
    roles = [r.strip() for r in a.roles.split(",") if r.strip()]
    if not roles or any(r not in SERVERS for r in roles):
        print("ERROR unknown role key", file=sys.stderr)
        return 2
    url = a.lab_url.rstrip("/") + "/mcp"
    try:
        with langflow_client(a.langflow_url, a.bootstrap_file) as c:
            existing = {s["name"] for s in check(c.get("/api/v2/mcp/servers", params={"action_count": "false"}),
                                                 "list servers")}
            for r in roles:
                name, var, _n = SERVERS[r]
                body = {"url": url, "headers": {"Authorization": "Bearer {{" + var + "}}",
                                                "X-TaskSprint-Workspace": WORKSPACE}}
                action = "keep" if name in existing and not a.force else ("update" if name in existing else "create")
                print(f"{'PLAN' if a.dry_run else 'DO'} {action:6} {name}: {url} Authorization=Bearer {{{{{var}}}}}")
                if a.dry_run or action == "keep":
                    continue
                if action == "create":
                    check(c.post(f"/api/v2/mcp/servers/{name}", json=body), f"add {name}")
                else:
                    check(c.patch(f"/api/v2/mcp/servers/{name}", json=body), f"update {name}")
            if a.dry_run:
                return 0
            counts = {s["name"]: s for s in check(c.get("/api/v2/mcp/servers", params={"action_count": "true"}),
                                                  "verify servers")}
            bad = 0
            for r in roles:
                name, _var, n = SERVERS[r]
                got = counts.get(name, {})
                ok = got.get("toolsCount") == n and got.get("mode") == "streamable_http"
                bad += not ok
                print(f"{'PASS' if ok else 'FAIL'} {name}: mode={got.get('mode')} tools={got.get('toolsCount')} "
                      f"(expected {n})")
            return 1 if bad else 0
    except SetupError as err:
        print(f"ERROR {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
