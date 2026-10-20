#!/usr/bin/env python3
"""Create or re-import the TaskSprint Phase 06 Langflow flows (Architecture A3, A13).

  uv run --frozen --no-dev python scripts/import_flows.py --dry-run [--source exports|skeleton]
  uv run --frozen --no-dev python scripts/import_flows.py --apply   [--source exports|skeleton] [--force]
  uv run --frozen --no-dev python scripts/import_flows.py --export   # write sanitized flows/*.json

Writes ONLY flows named in FLOWS, ONLY inside the Langflow project "TaskSprint" (created when
missing). Unrelated flows/projects (TS-00, Starter Project, ...) are never modified.

--source skeleton  builds flows from installed parts: Chat Input / Agent / Chat Output nodes
                   copied from the live TS-00 flow (GET /api/v1/flows/{id}), the two reviewed
                   custom components (components/*.py, compiled by POST /api/v1/custom_component),
                   role instructions verbatim from prompts/*.md. MCP Tools nodes are NOT generated
                   here (their tool list is server-refreshed; they were added in the editor).
--source exports   (default) re-imports the sanitized exports in flows/ (the reviewed result of the
                   editor step), re-pointing folder ids, checking that every MCP server name and
                   global-variable NAME the flow references exists, and binding names only.

Idempotent: a flow that already exists with identical content is kept; a differing one is
reported and only replaced with --force. A second run creates no duplicates. After writing,
each flow is read back and compared (node ids/types, edges, bound variable names, MCP
server names) = round-trip verification. Secrets: the export step removes every non-empty
password-field value and fails if a credential-like string remains.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import re
import string
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lf_common import DEFAULT_BOOTSTRAP_FILE, DEFAULT_LANGFLOW_URL, REPO_ROOT, SetupError, check, langflow_client  # noqa: E402

PROJECT = "TaskSprint"
TS00_ID = "3f476c53-e39f-4157-8f73-5e488a0a43e9"
MODEL_NAME = "claude-sonnet-5-5"
MAX_ITERATIONS = 8
# file, flow name, kind, prompt file, role credential variable, MCP server
FLOWS = (
    ("30_todo_app.json", "TS-30 To-do App", "app", None, "TS_APP_TOKEN", None),
    ("01_product_owner.json", "TS-01 Product Owner", "agent", "product_owner.md", "TS_PO_TOKEN",
     "tasksprint-product-owner"),
    ("02_developer.json", "TS-02 Developer", "agent", "developer.md", "TS_DEV_TOKEN", "tasksprint-developer"),
    ("03_qa.json", "TS-03 QA", "agent", "qa.md", "TS_QA_TOKEN", "tasksprint-qa"),
)
DESCRIPTIONS = {
    "TS-30 To-do App": "TaskSprint Phase 06: deterministic To-do App console (no model).",
    "TS-01 Product Owner": "TaskSprint Phase 06: Product Owner specialist agent (product_owner MCP tools).",
    "TS-02 Developer": "TaskSprint Phase 06: Developer specialist agent (developer MCP tools).",
    "TS-03 QA": "TaskSprint Phase 06: QA specialist agent (qa MCP tools).",
}
SECRET_PATTERNS = [re.compile(p) for p in (
    r"sk-[A-Za-z0-9_-]{16,}", r"sk-ant-[A-Za-z0-9_-]{16,}", r"AKIA[0-9A-Z]{16}", r"xox[abpr]-[A-Za-z0-9-]{10,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}", r"Bearer\s+[A-Za-z0-9_\-.]{20,}", r"ts_[A-Za-z0-9_-]{30,}")]
VOLATILE_FLOW_KEYS = ("id", "user_id", "folder_id", "workspace_id", "updated_at", "name_key", "webhook",
                      "endpoint_name", "action_name", "action_description")


# --------------------------------------------------------------------------- helpers
def rid(prefix: str) -> str:
    return prefix + "-" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(5))


def handle(d: dict) -> str:
    return json.dumps(d, separators=(",", ":")).replace('"', "œ")


def edge(src: dict, out: str, tgt: dict, field: str) -> dict:
    """Edge whose handle types are taken from the installed templates (no guessed types)."""
    sh = {"dataType": src["data"]["type"], "id": src["id"], "name": out,
          "output_types": next(o["types"] for o in src["data"]["node"]["outputs"] if o["name"] == out)}
    f = tgt["data"]["node"]["template"][field]
    th = {"fieldName": field, "id": tgt["id"], "inputTypes": f["input_types"], "type": f["type"]}
    return {"source": src["id"], "sourceHandle": handle(sh), "target": tgt["id"], "targetHandle": handle(th),
            "data": {"targetHandle": th, "sourceHandle": sh},
            "id": f"xy-edge__{src['id']}{handle(sh)}-{tgt['id']}{handle(th)}", "selected": False, "animated": False,
            "className": ""}


def node(node_id: str, ntype: str, frontend: dict, x: int, y: int, show: bool = True) -> dict:
    return {"id": node_id, "type": "genericNode", "position": {"x": x, "y": y}, "selected": False,
            "data": {"node": frontend, "showNode": show, "type": ntype, "id": node_id}}


def bindings(flow_data: dict) -> dict[str, Any]:
    """Variable NAMES bound via load_from_db, MCP server names, node types and edge pairs."""
    vars_, servers, types = set(), set(), {}
    for n in flow_data["nodes"]:
        types[n["id"]] = n["data"]["type"]
        for fname, f in n["data"]["node"].get("template", {}).items():
            if isinstance(f, dict) and f.get("load_from_db") and isinstance(f.get("value"), str) and f["value"]:
                vars_.add(f"{n['data']['type']}.{fname}={f['value']}")
            if isinstance(f, dict) and f.get("type") == "mcp" and isinstance(f.get("value"), dict):
                servers.add(f["value"].get("name"))
    edges = sorted(f"{e['source']}.{e['data']['sourceHandle']['name']}->{e['target']}.{e['data']['targetHandle']['fieldName']}"
                   f":{e['data']['targetHandle'].get('type')}" for e in flow_data["edges"])
    return {"variables": sorted(vars_), "mcp_servers": sorted(s for s in servers if s), "nodes": types, "edges": edges}


def scrub(obj: Any) -> Any:
    """Remove values of password fields and any credential-like strings (export sanitizer)."""
    if isinstance(obj, dict):
        out = {k: scrub(v) for k, v in obj.items()}
        if out.get("password") is True and out.get("value") and not out.get("load_from_db"):
            out["value"] = ""
        return out
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def secret_hits(text: str) -> list[str]:
    hits = []
    for p in SECRET_PATTERNS:
        hits += [m.group(0)[:10] + "…" for m in p.finditer(text)]
    return hits


def digest(flow_data: dict) -> str:
    """Content identity independent of random node ids: types, wiring, bound names, prompts, key settings."""
    b = bindings(flow_data)
    types = b["nodes"]
    edges = sorted(re.sub(r"^([^.]+)", lambda m: types.get(m.group(1), "?"), e.split("->")[0]) + "->" +
                   re.sub(r"^([^.]+)", lambda m: types.get(m.group(1), "?"), e.split("->")[1]) for e in b["edges"])
    settings = []
    for n in flow_data["nodes"]:
        t = n["data"]["node"].get("template", {})
        for k in ("system_prompt", "max_iterations", "add_calculator_tool", "add_current_date_tool", "code", "tool"):
            if isinstance(t.get(k), dict):
                settings.append(f"{n['data']['type']}.{k}={json.dumps(t[k].get('value'), sort_keys=True)}")
        settings.append(f"{n['data']['type']}.tool_mode={n['data']['node'].get('tool_mode')}")
    ident = {"types": sorted(types.values()), "edges": edges, "variables": b["variables"],
             "mcp": b["mcp_servers"], "settings": sorted(settings)}
    return hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- skeleton builder
def compile_component(c, path: Path) -> tuple[str, dict]:
    body = check(c.post("/api/v1/custom_component", json={"code": path.read_text(encoding="utf-8")}),
                 f"compile {path.name}")
    return body["type"], body["data"]


def build_skeleton(c, name: str, kind: str, prompt: str | None, var: str) -> dict:
    ts00 = check(c.get(f"/api/v1/flows/{TS00_ID}"), "read TS-00 skeleton")
    by_type = {n["data"]["type"]: n for n in ts00["data"]["nodes"]}
    chat_in = copy.deepcopy(by_type["ChatInput"]["data"]["node"])
    chat_out = copy.deepcopy(by_type["ChatOutput"]["data"]["node"])
    ci = node(rid("ChatInput"), "ChatInput", chat_in, 80, 260, show=False)
    co = node(rid("ChatOutput"), "ChatOutput", chat_out, 1180, 260, show=False)
    if kind == "app":
        t, fe = compile_component(c, REPO_ROOT / "components/app_console.py")
        ac = node(rid(t), t, fe, 480, 200)
        nodes = [ci, ac, co]
        edges = [edge(ci, "message", ac, "command"), edge(ac, "result", co, "input_value")]
    else:
        t, fe = compile_component(c, REPO_ROOT / "components/run_context.py")
        fe["template"]["role_token"]["value"] = var
        fe["template"]["role_token"]["load_from_db"] = True
        rc = node(rid(t), t, fe, 360, 200)
        agent_fe = copy.deepcopy(by_type["Agent"]["data"]["node"])
        tpl = agent_fe["template"]
        if tpl["model"]["value"][0]["name"] != MODEL_NAME:
            raise SetupError("TS-00 Agent model is not the expected model")
        tpl["system_prompt"]["value"] = (REPO_ROOT / "prompts" / prompt).read_text(encoding="utf-8").rstrip("\n")
        tpl["max_iterations"]["value"] = MAX_ITERATIONS
        tpl["add_calculator_tool"]["value"] = False
        tpl["add_current_date_tool"]["value"] = False
        tpl["api_key"]["value"] = ""
        for k in [k for k in tpl if k.startswith("_frontend_node_")]:
            tpl.pop(k)
        ag = node(rid("Agent"), "Agent", agent_fe, 760, 120)
        ag["data"]["selected_output"] = "response"
        nodes = [ci, rc, ag, co]
        edges = [edge(ci, "message", rc, "input_value"), edge(rc, "message", ag, "input_value"),
                 edge(ag, "response", co, "input_value")]
    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.8}}


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--export", action="store_true", help="GET the live flows and write sanitized flows/*.json")
    p.add_argument("--source", choices=("exports", "skeleton"), default="exports")
    p.add_argument("--force", action="store_true", help="replace a differing existing flow")
    p.add_argument("--only", default="", help="comma list of flow names to process")
    p.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    p.add_argument("--bootstrap-file", type=Path, default=DEFAULT_BOOTSTRAP_FILE)
    p.add_argument("--flows-dir", type=Path, default=REPO_ROOT / "flows")
    a = p.parse_args(argv)
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    selected = [f for f in FLOWS if not only or f[1] in only]
    try:
        with langflow_client(a.langflow_url, a.bootstrap_file) as c:
            projects = check(c.get("/api/v1/projects/"), "list projects")
            proj = next((pr for pr in projects if pr["name"] == PROJECT), None)
            if proj is None:
                print(f"{'PLAN' if a.dry_run else 'DO'} create project {PROJECT}")
                if a.export:
                    raise SetupError("project TaskSprint does not exist; nothing to export")
                if a.apply:
                    proj = check(c.post("/api/v1/projects/", json={"name": PROJECT, "description":
                                 "TaskSprint workshop flows (managed by scripts/import_flows.py)"}),
                                 "create project", ok=(200, 201))
            else:
                print(f"OK project {PROJECT} id={proj['id']}")
            existing: dict[str, dict] = {}
            if proj is not None:
                for f in check(c.get("/api/v1/flows/", params={"folder_id": proj["id"], "get_all": "true",
                                                              "header_flows": "true"}), "list flows"):
                    if f.get("folder_id") == proj["id"]:
                        if f["name"] in existing:
                            print(f"WARN duplicate flow name in project: {f['name']}")
                        existing[f["name"]] = f
            known_vars = {v["name"] for v in check(c.get("/api/v1/variables/"), "list variables")}
            known_servers = {s["name"] for s in check(c.get("/api/v2/mcp/servers", params={"action_count": "false"}),
                                                      "list mcp servers")}
            bad = 0
            for fname, name, kind, prompt, var, server in selected:
                path = a.flows_dir / fname
                if a.export:
                    if name not in existing:
                        print(f"FAIL export {name}: not found in project")
                        bad += 1
                        continue
                    full = check(c.get(f"/api/v1/flows/{existing[name]['id']}"), f"read {name}")
                    clean = scrub({k: v for k, v in full.items() if k not in VOLATILE_FLOW_KEYS})
                    text = json.dumps(clean, indent=2, ensure_ascii=False) + "\n"
                    hits = secret_hits(text)
                    if hits:
                        print(f"FAIL export {name}: credential-like strings found ({len(hits)}); not written")
                        bad += 1
                        continue
                    a.flows_dir.mkdir(exist_ok=True)
                    path.write_text(text, encoding="utf-8")
                    b = bindings(clean["data"])
                    print(f"OK export {name} -> flows/{fname} ({len(text)} bytes, sha256 "
                          f"{hashlib.sha256(text.encode()).hexdigest()[:16]}) vars={b['variables']} "
                          f"mcp={b['mcp_servers']}")
                    continue
                if a.source == "exports":
                    if not path.is_file():
                        print(f"SKIP {name}: flows/{fname} not present (use --source skeleton first)")
                        continue
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    if doc.get("name") != name:
                        raise SetupError(f"flows/{fname} has name {doc.get('name')!r}, expected {name!r}")
                    data = doc["data"]
                else:
                    data = build_skeleton(c, name, kind, prompt, var)
                b = bindings(data)
                missing_vars = sorted({v.split("=", 1)[1] for v in b["variables"]} - known_vars)
                missing_srv = sorted(set(b["mcp_servers"]) - known_servers)
                if missing_vars or missing_srv:
                    print(f"FAIL {name}: missing global variables {missing_vars} / MCP servers {missing_srv}")
                    bad += 1
                    continue
                if secret_hits(json.dumps(data)):
                    print(f"FAIL {name}: credential-like string in flow data; refusing to write")
                    bad += 1
                    continue
                cur = existing.get(name)
                if cur is not None:
                    live = check(c.get(f"/api/v1/flows/{cur['id']}"), f"read {name}")
                    if digest(live["data"]) == digest(data):
                        print(f"OK keep {name} id={cur['id']} (identical bindings/wiring)")
                        continue
                    if not a.force:
                        print(f"DIFF {name} id={cur['id']} differs from {a.source}; not replaced (use --force)")
                        continue
                action = "update" if cur else "create"
                print(f"{'PLAN' if a.dry_run else 'DO'} {action} {name} from {a.source}: nodes={list(b['nodes'].values())} "
                      f"vars={b['variables']} mcp={b['mcp_servers']}")
                if a.dry_run:
                    continue
                payload = {"name": name, "description": DESCRIPTIONS[name], "data": data, "folder_id": proj["id"],
                           "is_component": False}
                if cur:
                    res = check(c.patch(f"/api/v1/flows/{cur['id']}", json=payload), f"update {name}")
                else:
                    res = check(c.post("/api/v1/flows/", json=payload), f"create {name}", ok=(200, 201))
                back = check(c.get(f"/api/v1/flows/{res['id']}"), f"verify {name}")
                ok = bindings(back["data"]) == b and back["folder_id"] == proj["id"]
                bad += not ok
                print(f"{'PASS' if ok else 'FAIL'} round-trip {name} id={res['id']}")
            return 1 if bad else 0
    except SetupError as err:
        print(f"ERROR {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
