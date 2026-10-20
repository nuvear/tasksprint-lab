#!/usr/bin/env python3
"""Phase 07: bounded toolset in the three specialists and the TS-10 Sprint Room (Build Guide 07.1-07.2).

  uv run --frozen --no-dev python scripts/phase07_flows.py --dry-run
  uv run --frozen --no-dev python scripts/phase07_flows.py --apply [--only "TS-02 Developer,TS-10 Sprint Room"]

Specialists (TS-01/02/03, edited in place, ids kept): the Run Context node is upgraded to
components/run_context.py 1.1.0 (its role-token binding is kept); the native MCP Tools node and its
edge are removed; a TaskSprint Bounded Toolset node (components/bounded_toolset.py) is added with the
same role Credential global, wired Run Context **Run** -> Toolset **Run** and Toolset -> Agent **Tools**.

TS-10 Sprint Room (created in project TaskSprint when missing): Chat Input -> Run Context (TS_COORD_TOKEN)
-> Agent (prompts/coordinator.md, claude-sonnet-5-5, Max Iterations 8, Calculator/Current Date off)
-> Chat Output; Bounded Toolset (role coordinator, 180 s) -> Agent Tools; three native **Run Flow**
nodes, each selected (POST /api/v1/custom_component/update, the editor's own refresh route) to
exactly one of TS-01/02/03 by id, switched to Tool Mode, Session ID wired from Run Context **Run ID**
(lineage), Toolset wired into the matching Bounded Toolset slot. No Run Flow reaches the Agent
directly and no node can select an arbitrary flow at run time.

Templates come from the installed instance (TS-00 nodes, /api/v1/all, compile route); no field is
guessed. Variable NAMES only; no secret value is read or written. Idempotent: an up-to-date flow is
kept (same digest as scripts/import_flows.py). Never touches flows outside project TaskSprint.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_flows import (MAX_ITERATIONS, MODEL_NAME, PROJECT, TS00_ID, compile_component, digest, edge,  # noqa: E402
                          node, rid, secret_hits)
from lf_common import DEFAULT_BOOTSTRAP_FILE, DEFAULT_LANGFLOW_URL, REPO_ROOT, SetupError, check, langflow_client  # noqa: E402

SPECIALISTS = {  # flow name -> (role, credential variable)
    "TS-01 Product Owner": ("product_owner", "TS_PO_TOKEN"),
    "TS-02 Developer": ("developer", "TS_DEV_TOKEN"),
    "TS-03 QA": ("qa", "TS_QA_TOKEN"),
}
SPRINT_ROOM = "TS-10 Sprint Room"
SLOTS = (("product_owner_flow", "TS-01 Product Owner"), ("developer_flow", "TS-02 Developer"), ("qa_flow", "TS-03 QA"))
DESCRIPTIONS = {
    "TS-01 Product Owner": "TaskSprint Phase 07: Product Owner specialist agent (bounded product_owner toolset).",
    "TS-02 Developer": "TaskSprint Phase 07: Developer specialist agent (bounded developer toolset).",
    "TS-03 QA": "TaskSprint Phase 07: QA specialist agent (bounded qa toolset).",
    SPRINT_ROOM: "TaskSprint Phase 07: Scrum Coordinator agent with three bounded specialist delegations.",
}


def bind_secret(fe: dict, field: str, var: str) -> None:
    fe["template"][field]["value"] = var
    fe["template"][field]["load_from_db"] = True


def toolset_node(c, role: str, var: str, x: int, y: int, timeout_s: float) -> dict:
    t, fe = compile_component(c, REPO_ROOT / "components/bounded_toolset.py")
    bind_secret(fe, "role_token", var)
    fe["template"]["expected_role"]["value"] = role
    fe["template"]["invocation_timeout_s"]["value"] = timeout_s
    if role != "coordinator":  # delegation slots exist only for the coordinator; hide them elsewhere
        for slot, _ in SLOTS:
            fe["template"][slot]["show"] = False
    return node(rid(t), t, fe, x, y)


def run_context_fe(c, var: str) -> tuple[str, dict]:
    t, fe = compile_component(c, REPO_ROOT / "components/run_context.py")
    bind_secret(fe, "role_token", var)
    return t, fe


def upgrade_specialist(c, flow: dict, role: str, var: str) -> dict:
    data = copy.deepcopy(flow["data"])
    nodes = data["nodes"]
    rc = next(n for n in nodes if n["data"]["type"] == "TaskSprintRunContext")
    agent = next(n for n in nodes if n["data"]["type"] == "Agent")
    if rc["data"]["node"]["template"]["role_token"].get("value") != var:
        raise SetupError(f"{flow['name']}: Run Context is not bound to {var}")
    _, fe = run_context_fe(c, var)
    rc["data"]["node"] = fe
    drop = {n["id"] for n in nodes if n["data"]["type"] in ("MCP", "TaskSprintBoundedToolset")}
    data["nodes"] = [n for n in nodes if n["id"] not in drop]
    data["edges"] = [e for e in data["edges"] if e["source"] not in drop and e["target"] not in drop]
    bt = toolset_node(c, role, var, 330, -430, 90.0)
    data["nodes"].append(bt)
    data["edges"] += [edge(rc, "run", bt, "run_info"), edge(bt, "component_as_tool", agent, "tools")]
    return data


def run_flow_node(c, rf_template: dict, flow_name: str, flow_id: str, x: int, y: int) -> dict:
    t = copy.deepcopy(rf_template["template"])
    code = t["code"]["value"]
    t["flow_name_selected"]["value"] = flow_name
    t["flow_name_selected"]["options"] = [flow_name]
    t["flow_id_selected"]["value"] = flow_id
    n1 = check(c.post("/api/v1/custom_component/update", json={"code": code, "template": t, "field": "flow_id_selected",
                                                                "field_value": flow_id, "tool_mode": False}),
               f"select {flow_name} in Run Flow")
    n2 = check(c.post("/api/v1/custom_component/update", json={"code": code, "template": n1["template"],
                                                                "field": "tool_mode", "field_value": True,
                                                                "tool_mode": True}), "Run Flow tool mode")
    fe = {**copy.deepcopy(rf_template), **n2}
    fe["tool_mode"] = True
    fe["template"]["session_id"]["advanced"] = False  # show the handle; it is not a tool argument
    if [o["name"] for o in fe["outputs"]] != ["component_as_tool"]:
        raise SetupError("Run Flow did not switch to Tool Mode")
    return node(rid("RunFlow"), "RunFlow", fe, x, y)


def build_sprint_room(c, flows_by_name: dict) -> dict:
    ts00 = check(c.get(f"/api/v1/flows/{TS00_ID}"), "read TS-00 skeleton")
    by_type = {n["data"]["type"]: n for n in ts00["data"]["nodes"]}
    ci = node(rid("ChatInput"), "ChatInput", copy.deepcopy(by_type["ChatInput"]["data"]["node"]), -300, 430, show=False)
    co = node(rid("ChatOutput"), "ChatOutput", copy.deepcopy(by_type["ChatOutput"]["data"]["node"]), 1620, 430,
              show=False)
    t, fe = run_context_fe(c, "TS_COORD_TOKEN")
    rc = node(rid(t), t, fe, 20, 380)
    agent_fe = copy.deepcopy(by_type["Agent"]["data"]["node"])
    tpl = agent_fe["template"]
    if tpl["model"]["value"][0]["name"] != MODEL_NAME:
        raise SetupError("TS-00 Agent model is not the expected model")
    tpl["system_prompt"]["value"] = (REPO_ROOT / "prompts/coordinator.md").read_text(encoding="utf-8").rstrip("\n")
    tpl["max_iterations"]["value"] = MAX_ITERATIONS
    tpl["add_calculator_tool"]["value"] = False
    tpl["add_current_date_tool"]["value"] = False
    tpl["api_key"]["value"] = ""
    for k in [k for k in tpl if k.startswith("_frontend_node_")]:
        tpl.pop(k)
    ag = node(rid("Agent"), "Agent", agent_fe, 1240, 260)
    ag["data"]["selected_output"] = "response"
    bt = toolset_node(c, "coordinator", "TS_COORD_TOKEN", 840, -180, 180.0)
    allc = check(c.get("/api/v1/all"), "component catalog")
    rf_tpl = next(comps["RunFlow"] for comps in allc.values() if isinstance(comps, dict) and "RunFlow" in comps)
    nodes, edges = [ci, rc, ag, co, bt], []
    for i, (slot, flow_name) in enumerate(SLOTS):
        target = flows_by_name.get(flow_name)
        if target is None:
            raise SetupError(f"{flow_name} not found in project {PROJECT}")
        rf = run_flow_node(c, rf_tpl, flow_name, target["id"], 420, -760 + i * 420)
        nodes.append(rf)
        edges += [edge(rc, "run_id", rf, "session_id"), edge(rf, "component_as_tool", bt, slot)]
    edges += [edge(ci, "message", rc, "input_value"), edge(rc, "message", ag, "input_value"),
              edge(ag, "response", co, "input_value"), edge(rc, "run", bt, "run_info"),
              edge(bt, "component_as_tool", ag, "tools")]
    return {"nodes": nodes, "edges": edges, "viewport": {"x": 200, "y": 420, "zoom": 0.55}}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--only", default="")
    p.add_argument("--force", action="store_true", help="rebuild even when the flow already uses the toolset")
    p.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    p.add_argument("--bootstrap-file", type=Path, default=DEFAULT_BOOTSTRAP_FILE)
    a = p.parse_args(argv)
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    try:
        with langflow_client(a.langflow_url, a.bootstrap_file) as c:
            proj = next((pr for pr in check(c.get("/api/v1/projects/"), "list projects") if pr["name"] == PROJECT), None)
            if proj is None:
                raise SetupError("project TaskSprint missing; run scripts/import_flows.py first")
            flows = {f["name"]: f for f in check(c.get("/api/v1/flows/", params={
                "folder_id": proj["id"], "get_all": "true", "header_flows": "true"}), "list flows")
                if f.get("folder_id") == proj["id"]}
            known_vars = {v["name"] for v in check(c.get("/api/v1/variables/"), "list variables")}
            for need in ("TASKSPRINT_API_BASE", "TS_COORD_TOKEN", *[v for _, v in SPECIALISTS.values()]):
                if need not in known_vars:
                    raise SetupError(f"global variable {need} missing")
            bad = 0
            for name in [*SPECIALISTS, SPRINT_ROOM]:
                if only and name not in only:
                    continue
                cur = flows.get(name)
                if name in SPECIALISTS:
                    if cur is None:
                        raise SetupError(f"{name} missing")
                    live = check(c.get(f"/api/v1/flows/{cur['id']}"), f"read {name}")
                    types = [n["data"]["type"] for n in live["data"]["nodes"]]
                    if "TaskSprintBoundedToolset" in types and "MCP" not in types and not a.force:
                        print(f"OK keep {name} id={cur['id']} (already bounded)")
                        continue
                    data = upgrade_specialist(c, live, *SPECIALISTS[name])
                else:
                    data = build_sprint_room(c, flows)
                    if cur is not None and not a.force:
                        live = check(c.get(f"/api/v1/flows/{cur['id']}"), f"read {name}")
                        if digest(live["data"]) == digest(data):
                            print(f"OK keep {name} id={cur['id']}")
                            continue
                        print(f"DIFF {name} id={cur['id']} exists and differs; not replaced (use --force)")
                        continue
                if secret_hits(str(data)):
                    raise SetupError(f"{name}: credential-like string in flow data; refusing to write")
                summary = sorted(n["data"]["type"] for n in data["nodes"])
                print(f"{'PLAN' if a.dry_run else 'DO'} {'update' if cur else 'create'} {name}: nodes={summary} "
                      f"edges={len(data['edges'])}")
                if a.dry_run:
                    continue
                payload = {"name": name, "description": DESCRIPTIONS[name], "data": data, "folder_id": proj["id"],
                           "is_component": False}
                res = (check(c.patch(f"/api/v1/flows/{cur['id']}", json=payload), f"update {name}") if cur else
                       check(c.post("/api/v1/flows/", json=payload), f"create {name}", ok=(200, 201)))
                back = check(c.get(f"/api/v1/flows/{res['id']}"), f"verify {name}")
                ok = digest(back["data"]) == digest(data) and back["folder_id"] == proj["id"]
                bad += not ok
                print(f"{'PASS' if ok else 'FAIL'} write {name} id={res['id']}")
            return 1 if bad else 0
    except SetupError as err:
        print(f"ERROR {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
