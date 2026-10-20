#!/usr/bin/env python3
"""Phase 08: TS-20 Production Manager and the Sprint Room's A2A peer (Build Guide 08.1, 08.5).

  uv run --frozen --no-dev python scripts/phase08_flows.py --dry-run
  uv run --frozen --no-dev python scripts/phase08_flows.py --apply --only ts20
  uv run --frozen --no-dev python scripts/phase08_flows.py --apply --only ts10     # after TS-20 is published

TS-20 Production Manager (created in project TaskSprint when missing): Chat Input -> Run Context 1.2.0
(TS_OPS_TOKEN) -> Agent (prompts/operations.md, claude-sonnet-5-5, Max Iterations 8, Calculator /
Current Date off) -> Chat Output; Bounded Toolset 1.1.0 (role operations, TS_OPS_TOKEN, 90 s; all
delegation and peer slots hidden) -> Agent Tools. Publishing as an A2A agent is done in the editor's
Agent pane ("Serve as an A2A agent"), not here.

TS-10 Sprint Room (edited in place): the Bounded Toolset node is upgraded to 1.1.0 (same node id, role,
token and edges) and one TaskSprint A2A Audit node is added, bound to the fixed TS-20 card URL and peer
flow id, TS_A2A_API_KEY and TS_COORD_TOKEN, its Toolset wired ONLY into the toolset slot
"A2A peer: TS-20 Production Manager" (operations_peer). The Agent never receives the adapter directly
and the Sprint Room gets no generic any-agent A2A tool. Variable NAMES only; no secret value is read.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_flows import MAX_ITERATIONS, MODEL_NAME, PROJECT, TS00_ID, compile_component, digest, edge, node, rid, \
    secret_hits  # noqa: E402
from lf_common import DEFAULT_BOOTSTRAP_FILE, DEFAULT_LANGFLOW_URL, REPO_ROOT, SetupError, check, \
    langflow_client  # noqa: E402

TS20 = "TS-20 Production Manager"
TS10 = "TS-10 Sprint Room"
TS20_DESCRIPTION = ("TaskSprint Production Manager (Operations agent). Assesses a release of the synthetic "
                    "demo-production to-do app from its own evidence and returns a canonical release plan reference "
                    "or a blocked assessment. Assessment never deploys; a human approves plans separately.")
SLOTS = ("product_owner_flow", "developer_flow", "qa_flow", "operations_peer", "a2a_timeout_s")


def bind_secret(fe: dict, field: str, var: str) -> None:
    fe["template"][field]["value"] = var
    fe["template"][field]["load_from_db"] = True


def toolset_fe(c, role: str, var: str, timeout_s: float) -> tuple[str, dict]:
    t, fe = compile_component(c, REPO_ROOT / "components/bounded_toolset.py")
    bind_secret(fe, "role_token", var)
    fe["template"]["expected_role"]["value"] = role
    fe["template"]["invocation_timeout_s"]["value"] = timeout_s
    if role != "coordinator":
        for slot in SLOTS:
            fe["template"][slot]["show"] = False
    return t, fe


def build_ts20(c) -> dict:
    ts00 = check(c.get(f"/api/v1/flows/{TS00_ID}"), "read TS-00 skeleton")
    by_type = {n["data"]["type"]: n for n in ts00["data"]["nodes"]}
    ci = node(rid("ChatInput"), "ChatInput", copy.deepcopy(by_type["ChatInput"]["data"]["node"]), -300, 430, show=False)
    co = node(rid("ChatOutput"), "ChatOutput", copy.deepcopy(by_type["ChatOutput"]["data"]["node"]), 1320, 430,
              show=False)
    t, fe = compile_component(c, REPO_ROOT / "components/run_context.py")
    bind_secret(fe, "role_token", "TS_OPS_TOKEN")
    rc = node(rid(t), t, fe, 20, 380)
    agent_fe = copy.deepcopy(by_type["Agent"]["data"]["node"])
    tpl = agent_fe["template"]
    if tpl["model"]["value"][0]["name"] != MODEL_NAME:
        raise SetupError("TS-00 Agent model is not the expected model")
    tpl["system_prompt"]["value"] = (REPO_ROOT / "prompts/operations.md").read_text(encoding="utf-8").rstrip("\n")
    tpl["max_iterations"]["value"] = MAX_ITERATIONS
    tpl["add_calculator_tool"]["value"] = False
    tpl["add_current_date_tool"]["value"] = False
    tpl["api_key"]["value"] = ""
    for k in [k for k in tpl if k.startswith("_frontend_node_")]:
        tpl.pop(k)
    ag = node(rid("Agent"), "Agent", agent_fe, 940, 260)
    ag["data"]["selected_output"] = "response"
    tt, tfe = toolset_fe(c, "operations", "TS_OPS_TOKEN", 90.0)
    bt = node(rid(tt), tt, tfe, 480, -120)
    edges = [edge(ci, "message", rc, "input_value"), edge(rc, "message", ag, "input_value"),
             edge(ag, "response", co, "input_value"), edge(rc, "run", bt, "run_info"),
             edge(bt, "component_as_tool", ag, "tools")]
    return {"nodes": [ci, rc, ag, co, bt], "edges": edges, "viewport": {"x": 260, "y": 260, "zoom": 0.6}}


def upgrade_ts10(c, live: dict, base_url: str, ts20_id: str) -> dict:
    data = copy.deepcopy(live["data"])
    nodes = data["nodes"]
    bt = next(n for n in nodes if n["data"]["type"] == "TaskSprintBoundedToolset")
    if bt["data"]["node"]["template"]["expected_role"]["value"] != "coordinator":
        raise SetupError("TS-10 toolset is not the coordinator toolset")
    _, fe = toolset_fe(c, "coordinator", "TS_COORD_TOKEN", 180.0)
    bt["data"]["node"] = fe
    drop = {n["id"] for n in nodes if n["data"]["type"] == "TaskSprintA2AAudit"}
    data["nodes"] = [n for n in nodes if n["id"] not in drop]
    data["edges"] = [e for e in data["edges"] if e["source"] not in drop and e["target"] not in drop]
    at, afe = compile_component(c, REPO_ROOT / "components/a2a_audit.py")
    afe["template"]["card_url"]["value"] = f"{base_url}/api/v1/a2a/{ts20_id}/.well-known/agent-card.json"
    afe["template"]["peer_flow_id"]["value"] = ts20_id
    bind_secret(afe, "api_key", "TS_A2A_API_KEY")
    bind_secret(afe, "audit_token", "TS_COORD_TOKEN")
    an = node(rid(at), at, afe, 420, 520)
    data["nodes"].append(an)
    data["edges"].append(edge(an, "component_as_tool", bt, "operations_peer"))
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--only", choices=("ts20", "ts10", "both"), default="both")
    p.add_argument("--force", action="store_true")
    p.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    p.add_argument("--bootstrap-file", type=Path, default=DEFAULT_BOOTSTRAP_FILE)
    a = p.parse_args(argv)
    try:
        with langflow_client(a.langflow_url, a.bootstrap_file) as c:
            proj = next((pr for pr in check(c.get("/api/v1/projects/"), "list projects") if pr["name"] == PROJECT), None)
            if proj is None:
                raise SetupError("project TaskSprint missing")
            flows = {f["name"]: f for f in check(c.get("/api/v1/flows/", params={
                "folder_id": proj["id"], "get_all": "true", "header_flows": "true"}), "list flows")
                if f.get("folder_id") == proj["id"]}
            if "TS-90 Instructor Console" in flows:
                print("NOTE TS-90 exists; not touched")
            known = {v["name"] for v in check(c.get("/api/v1/variables/"), "list variables")}
            for need in ("TASKSPRINT_API_BASE", "TS_OPS_TOKEN", "TS_COORD_TOKEN"):
                if need not in known:
                    raise SetupError(f"global variable {need} missing")
            bad = 0
            if a.only in ("ts20", "both"):
                cur = flows.get(TS20)
                if cur is not None and not a.force:
                    print(f"OK keep {TS20} id={cur['id']} (exists; use --force to rebuild in place)")
                else:
                    data = build_ts20(c)
                    if secret_hits(str(data)):
                        raise SetupError("credential-like string in TS-20 data")
                    print(f"{'PLAN' if a.dry_run else 'DO'} {'update' if cur else 'create'} {TS20}: nodes="
                          f"{sorted(n['data']['type'] for n in data['nodes'])} edges={len(data['edges'])}")
                    if not a.dry_run:
                        payload = {"name": TS20, "description": TS20_DESCRIPTION, "data": data,
                                   "folder_id": proj["id"], "is_component": False}
                        res = (check(c.patch(f"/api/v1/flows/{cur['id']}", json=payload), "update TS-20") if cur
                               else check(c.post("/api/v1/flows/", json=payload), "create TS-20", ok=(200, 201)))
                        back = check(c.get(f"/api/v1/flows/{res['id']}"), "verify TS-20")
                        ok = digest(back["data"]) == digest(data) and back["folder_id"] == proj["id"]
                        bad += not ok
                        flows[TS20] = back
                        print(f"{'PASS' if ok else 'FAIL'} write {TS20} id={res['id']} flow_type={back.get('flow_type')}"
                              f" a2a_enabled={back.get('a2a_enabled')}")
            if a.only in ("ts10", "both"):
                if "TS_A2A_API_KEY" not in known:
                    raise SetupError("TS_A2A_API_KEY missing; run scripts/create_a2a_key.py first")
                ts20, ts10 = flows.get(TS20), flows.get(TS10)
                if ts20 is None or ts10 is None:
                    raise SetupError("TS-20 and TS-10 must exist")
                live = check(c.get(f"/api/v1/flows/{ts10['id']}"), "read TS-10")
                types = [n["data"]["type"] for n in live["data"]["nodes"]]
                if "TaskSprintA2AAudit" in types and not a.force:
                    print(f"OK keep {TS10} id={ts10['id']} (A2A peer already wired)")
                else:
                    data = upgrade_ts10(c, live, a.langflow_url.rstrip("/"), ts20["id"])
                    if secret_hits(str(data)):
                        raise SetupError("credential-like string in TS-10 data")
                    print(f"{'PLAN' if a.dry_run else 'DO'} update {TS10}: nodes="
                          f"{sorted(n['data']['type'] for n in data['nodes'])} edges={len(data['edges'])}")
                    if not a.dry_run:
                        payload = {"name": TS10, "description": "TaskSprint Phase 08: Scrum Coordinator agent with "
                                   "three bounded specialist delegations and one A2A assessment peer (TS-20).",
                                   "data": data, "folder_id": proj["id"], "is_component": False}
                        check(c.patch(f"/api/v1/flows/{ts10['id']}", json=payload), "update TS-10")
                        back = check(c.get(f"/api/v1/flows/{ts10['id']}"), "verify TS-10")
                        ok = digest(back["data"]) == digest(data)
                        bad += not ok
                        print(f"{'PASS' if ok else 'FAIL'} write {TS10} id={ts10['id']}")
            return 1 if bad else 0
    except SetupError as err:
        print(f"ERROR {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
