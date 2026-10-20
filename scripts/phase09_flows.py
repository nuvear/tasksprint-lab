#!/usr/bin/env python3
"""Phase 09: TS-90 Instructor Console and the Operations prompt line (Build Guide 09.1-09.2).

  uv run --frozen --no-dev python scripts/phase09_flows.py --dry-run
  uv run --frozen --no-dev python scripts/phase09_flows.py --apply --only ts90 [--force]
  uv run --frozen --no-dev python scripts/phase09_flows.py --apply --only ts20-prompt
  uv run --frozen --no-dev python scripts/phase09_flows.py --check

TS-90 Instructor Console (project TaskSprint; NO Agent component, no model):
  Chat Input -> TaskSprint Instructor Control 1.0.0 (TS_APPROVER_TOKEN / TS_INSTRUCTOR_TOKEN /
  TS_EVALUATOR_TOKEN, TASKSPRINT_API_BASE)
    Review -> Human Input (User Choices Approve, Reject; no fallback)
                Approve -> TaskSprint Review Decision 1.0.0 (Decision = approve, TS_APPROVER_TOKEN) -> Chat Output
                Reject  -> TaskSprint Review Decision 1.0.0 (Decision = reject,  TS_APPROVER_TOKEN) -> Chat Output
    Result -> Chat Output
  The Human Input node template is copied from the installed TS-00T Templates flow (real 1.12.5
  template). After writing, the script verifies mcp_enabled=false, a2a_enabled=false, no Agent node,
  and that no other TaskSprint flow binds a human-only credential.

TS-20 prompt (owner-approved Phase 08 finding 7): only the Agent's instructions value is replaced
with prompts/operations.md (node ids, wiring, publication untouched); A2A publication is verified after.
Variable NAMES only; no secret value is read or printed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_flows import PROJECT, TS00_ID, compile_component, digest, edge, node, rid, secret_hits  # noqa: E402
from lf_common import DEFAULT_BOOTSTRAP_FILE, DEFAULT_LANGFLOW_URL, REPO_ROOT, SetupError, check, \
    langflow_client  # noqa: E402

TS90 = "TS-90 Instructor Console"
TS20 = "TS-20 Production Manager"
TS00T_ID = "0685ac65-234e-4752-bf76-ba45860e74be"
HUMAN_ONLY = ("TS_APPROVER_TOKEN", "TS_INSTRUCTOR_TOKEN", "TS_EVALUATOR_TOKEN")
TS90_DESCRIPTION = ("TaskSprint Phase 09: human-only control flow (no Agent). Typed commands; review PLAN_ID pauses "
                    "at native Human Input and records the human decision against the exact snapshot hash. Never on "
                    "MCP, A2A or any agent's tools.")


def bind(fe: dict, field: str, var: str) -> None:
    fe["template"][field]["value"] = var
    fe["template"][field]["load_from_db"] = True


def build_ts90(c) -> dict:
    ts00 = check(c.get(f"/api/v1/flows/{TS00_ID}"), "read TS-00 skeleton")
    by_type = {n["data"]["type"]: n for n in ts00["data"]["nodes"]}
    tmpl = check(c.get(f"/api/v1/flows/{TS00T_ID}"), "read TS-00T templates")
    hi_fe = copy.deepcopy(next(n for n in tmpl["data"]["nodes"] if n["data"]["type"] == "HumanInput")["data"]["node"])
    if hi_fe["template"]["decisions"]["value"] != ["Approve", "Reject"]:
        raise SetupError("Human Input template does not have the default Approve/Reject choices")
    if hi_fe["template"].get("enable_fallback", {}).get("value"):
        raise SetupError("Human Input template has fallback enabled")
    outs = [o["name"] for o in hi_fe["outputs"]]
    if outs != ["branch_approve", "branch_reject"]:
        raise SetupError(f"unexpected Human Input outputs {outs}")
    hi_fe["template"]["prompt"]["value"] = ""
    ci = node(rid("ChatInput"), "ChatInput", copy.deepcopy(by_type["ChatInput"]["data"]["node"]), -320, 300, show=False)
    t, fe = compile_component(c, REPO_ROOT / "components/instructor_control.py")
    bind(fe, "approver_token", "TS_APPROVER_TOKEN")
    bind(fe, "instructor_token", "TS_INSTRUCTOR_TOKEN")
    bind(fe, "evaluator_token", "TS_EVALUATOR_TOKEN")
    ctl = node(rid(t), t, fe, 40, 220)
    hi = node(rid("HumanInput"), "HumanInput", hi_fe, 480, 40)
    decisions = []
    for i, choice in enumerate(("approve", "reject")):
        dt, dfe = compile_component(c, REPO_ROOT / "components/review_decision.py")
        dfe["template"]["decision"]["value"] = choice
        bind(dfe, "approver_token", "TS_APPROVER_TOKEN")
        decisions.append(node(rid(dt), dt, dfe, 900, -120 + 420 * i))
    outs = [node(rid("ChatOutput"), "ChatOutput", copy.deepcopy(by_type["ChatOutput"]["data"]["node"]), x, y,
                 show=False) for x, y in ((1320, -60), (1320, 360), (900, 700))]
    edges = [edge(ci, "message", ctl, "input_value"), edge(ctl, "review", hi, "prompt"),
             edge(hi, "branch_approve", decisions[0], "reviewed"), edge(hi, "branch_reject", decisions[1], "reviewed"),
             edge(decisions[0], "record", outs[0], "input_value"), edge(decisions[1], "record", outs[1], "input_value"),
             edge(ctl, "result", outs[2], "input_value")]
    return {"nodes": [ci, ctl, hi, *decisions, *outs], "edges": edges, "viewport": {"x": 300, "y": 200, "zoom": 0.55}}


def human_only_bindings(flow_data: dict) -> list[str]:
    hits = []
    for n in flow_data.get("nodes", []):
        for fname, f in n["data"]["node"].get("template", {}).items():
            if isinstance(f, dict) and f.get("load_from_db") and f.get("value") in HUMAN_ONLY:
                hits.append(f"{n['data']['type']}.{fname}={f['value']}")
    return hits


def verify_ts90(back: dict) -> list[str]:
    problems = []
    types = [n["data"]["type"] for n in back["data"]["nodes"]]
    if "Agent" in types or any("Agent" == t or t.endswith("AgentComponent") for t in types):
        problems.append("contains an Agent")
    if back.get("mcp_enabled"):
        problems.append("mcp_enabled is true")
    if back.get("a2a_enabled"):
        problems.append("a2a_enabled is true")
    for n in back["data"]["nodes"]:
        if n["data"]["node"].get("tool_mode"):
            problems.append(f"{n['data']['type']} in tool mode")
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true", help="verify TS-90 isolation and credential scoping only")
    p.add_argument("--only", choices=("ts90", "ts20-prompt", "both"), default="both")
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
            known = {v["name"]: v for v in check(c.get("/api/v1/variables/"), "list variables")}
            bad = 0
            if a.check:
                for name, f in sorted(flows.items()):
                    full = check(c.get(f"/api/v1/flows/{f['id']}"), f"read {name}")
                    hits = human_only_bindings(full["data"])
                    if name == TS90:
                        probs = verify_ts90(full)
                        bad += bool(probs)
                        print(f"{'FAIL' if probs else 'PASS'} {TS90} id={f['id']} mcp_enabled={full.get('mcp_enabled')}"
                              f" a2a_enabled={full.get('a2a_enabled')} flow_type={full.get('flow_type')} "
                              f"human-only bindings={sorted(set(h.split('=')[1] for h in hits))} {probs or ''}")
                    else:
                        bad += bool(hits)
                        print(f"{'FAIL' if hits else 'PASS'} {name}: binds no human-only credential {hits or ''}"
                              f" (mcp_enabled={full.get('mcp_enabled')})")
                return 1 if bad else 0
            if a.only in ("ts90", "both"):
                for need in ("TASKSPRINT_API_BASE", *HUMAN_ONLY):
                    v = known.get(need)
                    if v is None or (need != "TASKSPRINT_API_BASE" and v.get("type") != "Credential"):
                        raise SetupError(f"global variable {need} missing or not a Credential "
                                         "(run scripts/import_globals.py --apply --phase09)")
                cur = flows.get(TS90)
                if cur is not None and not a.force:
                    print(f"OK keep {TS90} id={cur['id']} (exists; use --force to rebuild in place)")
                else:
                    data = build_ts90(c)
                    if secret_hits(str(data)):
                        raise SetupError("credential-like string in TS-90 data")
                    print(f"{'PLAN' if a.dry_run else 'DO'} {'update' if cur else 'create'} {TS90}: nodes="
                          f"{sorted(n['data']['type'] for n in data['nodes'])} edges={len(data['edges'])}")
                    if not a.dry_run:
                        payload = {"name": TS90, "description": TS90_DESCRIPTION, "data": data,
                                   "folder_id": proj["id"], "is_component": False, "mcp_enabled": False}
                        res = (check(c.patch(f"/api/v1/flows/{cur['id']}", json=payload), "update TS-90") if cur
                               else check(c.post("/api/v1/flows/", json=payload), "create TS-90", ok=(200, 201)))
                        back = check(c.get(f"/api/v1/flows/{res['id']}"), "verify TS-90")
                        probs = verify_ts90(back)
                        ok = digest(back["data"]) == digest(data) and back["folder_id"] == proj["id"] and not probs
                        bad += not ok
                        print(f"{'PASS' if ok else 'FAIL'} write {TS90} id={res['id']} mcp_enabled="
                              f"{back.get('mcp_enabled')} a2a_enabled={back.get('a2a_enabled')} {probs or ''}")
            if a.only in ("ts20-prompt", "both"):
                cur = flows.get(TS20)
                if cur is None:
                    raise SetupError("TS-20 missing")
                live = check(c.get(f"/api/v1/flows/{cur['id']}"), "read TS-20")
                data = copy.deepcopy(live["data"])
                agent = next(n for n in data["nodes"] if n["data"]["type"] == "Agent")
                want = (REPO_ROOT / "prompts/operations.md").read_text(encoding="utf-8").rstrip("\n")
                have = agent["data"]["node"]["template"]["system_prompt"]["value"]
                sha = hashlib.sha256(want.encode()).hexdigest()
                if have == want:
                    print(f"OK keep {TS20} prompt (sha256 {sha[:8]}...)")
                else:
                    print(f"{'PLAN' if a.dry_run else 'DO'} update {TS20} Agent Instructions "
                          f"{hashlib.sha256(have.encode()).hexdigest()[:8]}... -> {sha[:8]}...")
                    if not a.dry_run:
                        agent["data"]["node"]["template"]["system_prompt"]["value"] = want
                        check(c.patch(f"/api/v1/flows/{cur['id']}", json={"data": data}), "update TS-20 prompt")
                        back = check(c.get(f"/api/v1/flows/{cur['id']}"), "verify TS-20")
                        bag = next(n for n in back["data"]["nodes"] if n["data"]["type"] == "Agent")
                        ok = (bag["data"]["node"]["template"]["system_prompt"]["value"] == want
                              and back.get("a2a_enabled") is True and back.get("flow_type") == "agent"
                              and {n["id"] for n in back["data"]["nodes"]} == {n["id"] for n in live["data"]["nodes"]})
                        card = c.get(f"/api/v1/a2a/{cur['id']}/.well-known/agent-card.json")
                        ok = ok and card.status_code == 200
                        bad += not ok
                        print(f"{'PASS' if ok else 'FAIL'} {TS20} prompt sha256 {sha[:8]}... a2a_enabled="
                              f"{back.get('a2a_enabled')} flow_type={back.get('flow_type')} card={card.status_code}")
            return 1 if bad else 0
    except SetupError as err:
        print(f"ERROR {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
