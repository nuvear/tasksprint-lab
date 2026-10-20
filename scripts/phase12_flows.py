#!/usr/bin/env python3
"""Phase 12: apply the two approved fixes to the live TS-20 and TS-10 flows IN PLACE (Build Guide 12, A9).

  uv run --frozen --no-dev python scripts/phase12_flows.py --dry-run
  uv run --frozen --no-dev python scripts/phase12_flows.py --apply

Fix 1 (TS-20 Production Manager): Bounded Toolset code refreshed to components/bounded_toolset.py (1.2.0, per-role
clamp), its "Max tool actions per invocation" set to 12 (the lab's operations cap since lab 0.8.0), the Agent's
Max Iterations set to 12, and the Agent Instructions replaced with prompts/operations.md.
Fix 2 (TS-10 Sprint Room): the Agent Instructions replaced with prompts/coordinator.md and its Bounded Toolset
code refreshed to 1.2.0 (the coordinator cap stays 8; values and bindings are kept).
TS-01/02/03 are NOT touched (their Bounded Toolset 1.1.0 clamps their roles to 8, identical to 1.2.0).

Only the flow's `data` is PATCHed: flow IDs, node IDs, edges, variable bindings (NAMES), Run Flow helper IDs, the
A2A peer and the TS-20 A2A publication are kept and verified afterwards; the TS-20 Agent Card must still be
served. Run only against a lab deployed from this commit: the deployed lab-side sha256 (evaluator gate read) must equal
this checkout's; --apply refuses otherwise. Needs the bootstrap key (.local/railway/langflow_bootstrap.env, never printed). Exit 0 = PASS.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_bundle import helpers  # noqa: E402
from import_flows import MAX_ITERATIONS_BY_FLOW, PROJECT, compile_component, digest  # noqa: E402
from lf_common import (DEFAULT_BOOTSTRAP_FILE, DEFAULT_LAB_URL, DEFAULT_LANGFLOW_URL, DEFAULT_TOKENS_FILE,  # noqa: E402
                       REPO_ROOT, SetupError, check, langflow_client, read_env)

sys.path.insert(0, str(REPO_ROOT))
from services.lab import SERVICE_VERSION, agent_evaluations  # noqa: E402

TS20, TS10 = "TS-20 Production Manager", "TS-10 Sprint Room"
TOOLSET = "TaskSprintBoundedToolset"
PLAN = {TS20: {"prompt": "operations.md", "max_actions": 12, "max_iterations": MAX_ITERATIONS_BY_FLOW[TS20]},
        TS10: {"prompt": "coordinator.md", "max_actions": None, "max_iterations": None}}


def h8(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def code_version(code: str) -> str:
    for line in code.splitlines():
        if line.startswith("ADAPTER_VERSION"):
            return line.split("=", 1)[1].strip().strip('"')
    return "?"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    ap.add_argument("--lab-url", default=DEFAULT_LAB_URL)
    ap.add_argument("--bootstrap-file", type=Path, default=DEFAULT_BOOTSTRAP_FILE)
    ap.add_argument("--tokens-file", type=Path, default=DEFAULT_TOKENS_FILE)
    a = ap.parse_args(argv)
    src = (REPO_ROOT / "components/bounded_toolset.py").read_text(encoding="utf-8")
    bad = 0
    try:
        # The deployed lab must run this checkout's lab code (per-role cap, readiness baseline candidate ID).
        local = agent_evaluations.lab_side_sha256()
        tok = read_env(a.tokens_file).get("TS_EVALUATOR_TOKEN", "")
        r = httpx.get(a.lab_url.rstrip("/") + "/v1/agent-system-manifests/qualified", timeout=30,
                      headers={"Authorization": f"Bearer {tok}", "X-TaskSprint-Workspace": "demo-001"})
        deployed = (r.json() if r.status_code == 200 else {}).get("current_lab_side_sha256")
        same = deployed == local
        print(f"{'PASS' if same else 'BLOCKED'} deployed lab side {str(deployed)[:16]}… "
              f"{'==' if same else '!='} this checkout {local[:16]}… (lab {SERVICE_VERSION})")
        if a.apply and not same:
            raise SetupError("redeploy the lab from this commit first; nothing was changed in Langflow")
        with langflow_client(a.langflow_url, a.bootstrap_file) as c:
            proj = next(p for p in check(c.get("/api/v1/projects/"), "list projects") if p["name"] == PROJECT)
            flows = {f["name"]: f for f in check(c.get("/api/v1/flows/", params={
                "folder_id": proj["id"], "get_all": "true", "header_flows": "true"}), "list flows")
                if f.get("folder_id") == proj["id"]}
            compiled = None
            for name, want in PLAN.items():
                cur = flows.get(name)
                if cur is None:
                    raise SetupError(f"{name} missing")
                live = check(c.get(f"/api/v1/flows/{cur['id']}"), f"read {name}")
                data = copy.deepcopy(live["data"])
                agent = next(n for n in data["nodes"] if n["data"]["type"] == "Agent")
                tset = next(n for n in data["nodes"] if n["data"]["type"] == TOOLSET)
                atpl, ttpl = agent["data"]["node"]["template"], tset["data"]["node"]["template"]
                prompt = (REPO_ROOT / "prompts" / want["prompt"]).read_text(encoding="utf-8").rstrip("\n")
                changes = []
                if atpl["system_prompt"]["value"] != prompt:
                    changes.append(f"instructions {h8(atpl['system_prompt']['value'])} -> {h8(prompt)} ({want['prompt']})")
                if want["max_iterations"] and atpl["max_iterations"]["value"] != want["max_iterations"]:
                    changes.append(f"Agent max_iterations {atpl['max_iterations']['value']} -> {want['max_iterations']}")
                if ttpl["code"]["value"] != src:
                    changes.append(f"toolset code {code_version(ttpl['code']['value'])} -> {code_version(src)}")
                if want["max_actions"] and ttpl["max_actions"]["value"] != want["max_actions"]:
                    changes.append(f"toolset max_actions {ttpl['max_actions']['value']} -> {want['max_actions']}")
                if not changes:
                    print(f"OK keep {name} (digest {digest(live['data'])})")
                    continue
                print(f"{'PLAN' if a.dry_run else 'DO'} {name} {cur['id']}: " + "; ".join(changes))
                if a.dry_run:
                    continue
                if ttpl["code"]["value"] != src:
                    compiled = compiled or compile_component(c, REPO_ROOT / "components/bounded_toolset.py")
                    fe = copy.deepcopy(compiled[1])
                    for k, f in ttpl.items():  # keep role, bindings (NAMES) and limits; only the code changes
                        if k in fe["template"] and k != "code" and isinstance(f, dict) and "value" in f:
                            fe["template"][k]["value"] = f["value"]
                            if f.get("load_from_db"):
                                fe["template"][k]["load_from_db"] = True
                    tset["data"]["node"] = fe
                    ttpl = fe["template"]
                if want["max_actions"]:
                    ttpl["max_actions"]["value"] = want["max_actions"]
                atpl["system_prompt"]["value"] = prompt
                if want["max_iterations"]:
                    atpl["max_iterations"]["value"] = want["max_iterations"]
                check(c.patch(f"/api/v1/flows/{cur['id']}", json={"data": data}), f"update {name}")
                back = check(c.get(f"/api/v1/flows/{cur['id']}"), f"verify {name}")
                bag = next(n for n in back["data"]["nodes"] if n["data"]["type"] == "Agent")["data"]["node"]["template"]
                bts = next(n for n in back["data"]["nodes"] if n["data"]["type"] == TOOLSET)["data"]["node"]["template"]
                ok = (back["id"] == cur["id"] and bag["system_prompt"]["value"] == prompt and bts["code"]["value"] == src
                      and {n["id"] for n in back["data"]["nodes"]} == {n["id"] for n in live["data"]["nodes"]}
                      and [e["id"] for e in back["data"]["edges"]] == [e["id"] for e in live["data"]["edges"]]
                      and helpers(back["data"]) == helpers(live["data"])
                      and back.get("a2a_enabled") == live.get("a2a_enabled")
                      and back.get("mcp_enabled") == live.get("mcp_enabled")
                      and bts["role_token"].get("load_from_db") and bts["role_token"]["value"] == ttpl["role_token"]["value"])
                if want["max_actions"]:
                    ok = ok and bts["max_actions"]["value"] == want["max_actions"]
                if want["max_iterations"]:
                    ok = ok and bag["max_iterations"]["value"] == want["max_iterations"]
                extra = ""
                if name == TS20:
                    card = c.get(f"/api/v1/a2a/{cur['id']}/.well-known/agent-card.json")
                    ok = ok and back.get("a2a_enabled") is True and card.status_code == 200
                    extra = f" a2a_enabled={back.get('a2a_enabled')} card={card.status_code}"
                bad += not ok
                print(f"{'PASS' if ok else 'FAIL'} {name}: same flow/node/edge IDs, helpers and publication; digest "
                      f"{digest(live['data'])} -> {digest(back['data'])}{extra}")
    except (SetupError, StopIteration, httpx.HTTPError, KeyError) as e:
        print(f"ERROR {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(f"SUMMARY phase12_flows: {'PASS' if not bad else 'FAIL'} ({bad} failed)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
