#!/usr/bin/env python3
"""Independent agent-evaluation harness (Phase 10; ACCEPTANCE.md eight agent cases; Architecture A9, A12).

Trusted instructor/evaluator code. It is NOT an agent and does not grade an agent's own verdict:

* invokes the REAL Langflow flows through ``POST /api/v1/run/{flow_id}`` with an explicit session ID per
  trial (TS-01, TS-03, TS-10, TS-20; TS-90 is human-only and is never invoked);
* isolates repetitions with the instructor reset of the designated workspace ``demo-001`` (preview first,
  counts recorded), and every trial with its own synthetic session (fresh run tree, no chat history);
* captures the Langflow output and message trace plus the lab's run tree, tool events and records;
* scores the protected case checks (``tests/agent_cases``) from those external records;
* writes ONE immutable report through the evaluator route ``POST /v1/agent-evaluations``; the lab
  recomputes every trial status, the denominators, the zero-tolerance slice and the verdict itself;
* writes a redacted Markdown summary under ``reports/redacted/`` and the raw trajectories under the
  git-ignored ``.local/evals/<tag>/`` (their SHA-256 digest is in the report).

Usage (repository root, ``source /tmp/ts/env.sh`` first on the owner VM):

  uv run --frozen --no-dev python scripts/run_agent_evals.py --dry-run
  uv run --frozen --no-dev python scripts/run_agent_evals.py --repeats 3                 (qualification)
  uv run --frozen --no-dev python scripts/run_agent_evals.py --repeats 1 --cases AE-04,AE-07 --no-reset
  uv run --frozen --no-dev python scripts/run_agent_evals.py --attest                     (live manifest)
  uv run --frozen --no-dev python scripts/run_agent_evals.py --probe-isolation

Secrets: tokens and the Langflow bootstrap key are read from ``.local/railway/`` and never printed.
Exit 0 = the action succeeded (and, for a run, the lab verdict is QUALIFIED or the run was partial).
"""
from __future__ import annotations

import argparse
import email.utils
import hashlib
import json
import re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lf_common import (DEFAULT_BOOTSTRAP_FILE, DEFAULT_LAB_URL, DEFAULT_LANGFLOW_URL, DEFAULT_TOKENS_FILE,  # noqa: E402
                       REPO_ROOT, SetupError, read_env)
from tests.agent_cases import cases as case_defs  # noqa: E402
from tests.agent_cases import graders  # noqa: E402

HARNESS_VERSION = "tasksprint-agent-eval-harness/1.0.0"
WS = "demo-001"
FLOWS = {"TS-01": "da674f03-2861-4b3f-9f25-129bb86a588f", "TS-02": "9610ee79-66ce-4f92-b304-44d9e5c8be38",
         "TS-03": "8906e4df-4fe3-489f-b30b-d5e57230459c", "TS-10": "ec5b5dba-d7d2-4aeb-899c-016a3f66b4eb",
         "TS-20": "489890aa-4bd0-4641-b669-070f10e0922b", "TS-30": "1613b28e-6e07-4056-a832-b9abeceb607e",
         "TS-90": "cda48ae0-d8bb-44bc-a422-91f9576fba43"}
INVOCABLE = {"TS-01", "TS-03", "TS-10", "TS-20"}  # never TS-90 (human-only), TS-02/TS-30 not needed
PROMPT_FILES = {"TS-01": "product_owner.md", "TS-02": "developer.md", "TS-03": "qa.md", "TS-10": "coordinator.md",
                "TS-20": "operations.md"}
TOKEN_VARS = {"coordinator": "TS_COORD_TOKEN", "operations": "TS_OPS_TOKEN", "developer": "TS_DEV_TOKEN",
              "instructor": "TS_INSTRUCTOR_TOKEN", "evaluator": "TS_EVALUATOR_TOKEN", "qa": "TS_QA_TOKEN",
              "product_owner": "TS_PO_TOKEN"}
SETTLE_S = 7          # > the lab's 5 s trial-window grace: setup/teardown actions stay outside every window
POST_TRIAL_S = 4      # let late events land before observing
EPOCH = "2000-01-01T00:00:00Z"
_SECRETISH = re.compile(r"(Bearer\s+\S+|ts_[a-z]+_[A-Za-z0-9_\-]{16,}|sk-[A-Za-z0-9_\-]{8,}|x-api-key[\"':=\s]+\S+)",
                        re.I)
VOLATILE_FIELDS = {"input_value", "_frontend_node_flow_id", "_frontend_node_folder_id", "session_id", "context_id",
                   "files", "run_info", "tools", "project_id", "base_url_ibm_watsonx"}


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def redact(text: str) -> str:
    return _SECRETISH.sub("[REDACTED]", text or "")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def sha(value: Any) -> str:
    data = value if isinstance(value, (bytes, bytearray)) else (value if isinstance(value, str) else canonical(value))
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ clients
class Lab:
    def __init__(self, base: str, tokens: dict[str, str]):
        self.base, self.tokens = base.rstrip("/"), tokens
        self.offset = timedelta(0)  # server clock - local clock

    def req(self, method: str, path: str, role: str, body: dict | None = None, params: dict | None = None,
            ws: str | None = WS, timeout: float = 60) -> tuple[int, dict, httpx.Response]:
        h = {"Authorization": f"Bearer {self.tokens[TOKEN_VARS[role]]}", "User-Agent": HARNESS_VERSION}
        if ws:
            h["X-TaskSprint-Workspace"] = ws
        r = httpx.request(method, self.base + path, json=body, params=params, headers=h, timeout=timeout,
                          follow_redirects=False)
        try:
            data = r.json()
        except ValueError:
            data = {}
        return r.status_code, data, r

    def ok(self, method: str, path: str, role: str, body: dict | None = None, **kw) -> dict:
        code, data, _ = self.req(method, path, role, body, **kw)
        if code not in (200, 201):
            err = (data.get("error") or {})
            raise SetupError(f"{method} {path} as {role}: HTTP {code} {err.get('code')} {err.get('message', '')[:160]}")
        return data

    def sync_clock(self) -> None:
        r = httpx.get(self.base + "/healthz", timeout=20)
        server = email.utils.parsedate_to_datetime(r.headers["date"])
        self.offset = server - datetime.now(timezone.utc)

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + self.offset

    def observe(self, since: str, limit: int = 2000) -> dict:
        return self.ok("GET", "/v1/evaluator/observations", "evaluator", params={"since": since, "limit": limit},
                       timeout=90)

    def instructor(self, action: str, **fields) -> dict:
        return self.ok("POST", "/v1/instructor/actions", "instructor", {"action": action, "workspace_id": WS, **fields},
                       ws=None)


class Langflow:
    def __init__(self, base: str, key: str):
        self.base = base.rstrip("/")
        self.c = httpx.Client(base_url=self.base, headers={"x-api-key": key}, timeout=httpx.Timeout(60, connect=15))

    def get(self, path: str, **params) -> Any:
        r = self.c.get(path, params=params or None)
        if r.status_code != 200:
            raise SetupError(f"Langflow GET {path}: HTTP {r.status_code}")
        return r.json()

    def run(self, flow: str, text: str, session: str, tweaks: dict | None) -> tuple[int, dict, int]:
        if flow not in INVOCABLE:
            raise SetupError(f"refusing to invoke {flow}: not an evaluated agent flow (TS-90 is human-only)")
        body: dict[str, Any] = {"input_value": text, "input_type": "chat", "output_type": "chat", "session_id": session}
        if tweaks:
            body["tweaks"] = tweaks
        t0 = time.monotonic()
        try:
            r = self.c.post(f"/api/v1/run/{FLOWS[flow]}", params={"stream": "false"}, json=body,
                            timeout=httpx.Timeout(420, connect=15))
            ms = int((time.monotonic() - t0) * 1000)
            try:
                return r.status_code, r.json(), ms
            except ValueError:
                return r.status_code, {"_text": redact(r.text[:500])}, ms
        except httpx.HTTPError as exc:
            return 0, {"_error": f"{type(exc).__name__}: {redact(str(exc))[:200]}"}, int((time.monotonic() - t0) * 1000)

    def messages(self, flow: str, session: str) -> list[dict]:
        try:
            return self.get("/api/v1/monitor/messages", flow_id=FLOWS[flow], session_id=session)
        except SetupError:
            return []


# ------------------------------------------------------------------ live system manifest (Langflow / harness side)
def _model(tpl: dict) -> dict:
    v = (tpl.get("model") or {}).get("value")
    first = v[0] if isinstance(v, list) and v and isinstance(v[0], dict) else {}
    return {"model_name": first.get("name"), "provider": first.get("provider"),
            **{k: (tpl.get(k) or {}).get("value") for k in ("max_iterations", "max_tokens", "n_messages",
                                                            "add_calculator_tool", "add_current_date_tool",
                                                            "handle_parsing_errors", "stream") if k in tpl}}


def _version_of(code: str) -> str | None:
    m = re.search(r"\b([a-z_]+/\d+\.\d+\.\d+)\b", code or "") or re.search(r"VERSION\s*=\s*\"(\d+\.\d+\.\d+)\"",
                                                                          code or "")
    return m.group(1) if m else None


def flow_identity(flow: dict) -> dict:
    nodes = sorted(flow["data"]["nodes"], key=lambda n: n["id"])
    ident_nodes, prompt, model, comps = [], None, None, {}
    for n in nodes:
        t = n["data"]["type"]
        tpl = n["data"]["node"].get("template", {})
        code = (tpl.get("code") or {}).get("value", "") if isinstance(tpl.get("code"), dict) else ""
        fields: dict[str, Any] = {}
        if t not in ("ChatInput", "ChatOutput"):
            for k, f in sorted(tpl.items()):
                if not isinstance(f, dict) or k == "code" or k in VOLATILE_FIELDS or "~" in k:
                    continue
                v = f.get("value")
                if f.get("load_from_db"):
                    fields[k] = f"var:{v}"
                elif f.get("password"):
                    fields[k] = "set" if v else ""
                elif k == "model":
                    fields[k] = _model(tpl)
                elif isinstance(v, (str, int, float, bool)) or v is None:
                    fields[k] = v
                elif isinstance(v, (list, dict)) and len(canonical(v)) < 8000:
                    fields[k] = v
        ident_nodes.append({"id": n["id"], "type": t, "code_sha256": sha(code) if code else None,
                            "tool_mode": n["data"]["node"].get("tool_mode"), "fields": fields})
        if t == "Agent":
            prompt = (tpl.get("system_prompt") or {}).get("value")
            model = _model(tpl)
        if code and t not in ("ChatInput", "ChatOutput", "Agent"):
            comps[t] = {"code_sha256": sha(code), "version": _version_of(code)}
    edges = sorted(f"{e['source']}.{e['data']['sourceHandle']['name']}->{e['target']}."
                   f"{e['data']['targetHandle']['fieldName']}" for e in flow["data"]["edges"])
    flags = {k: flow.get(k) for k in ("flow_type", "mcp_enabled", "access_type", "a2a_enabled", "locked")}
    ident = {"nodes": ident_nodes, "edges": edges, "flags": flags}
    return {"flow_id": flow["id"], "name": flow["name"], "identity_sha256": sha(ident), "flags": flags,
            "prompt_sha256": sha(prompt) if prompt else None, "model": model, "components": comps,
            "node_count": len(nodes), "edge_count": len(edges)}


def grader_sha256() -> tuple[str, dict]:
    files = sorted((REPO_ROOT / "tests" / "agent_cases").glob("*.py")) + [Path(__file__).resolve()]
    hashes = {str(p.relative_to(REPO_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return sha(hashes), hashes


def system_manifest(lf: Langflow) -> dict:
    version = lf.get("/api/v1/version")
    flows, prompts, models, comps = {}, {}, {}, {}
    for name, fid in FLOWS.items():
        ident = flow_identity(lf.get(f"/api/v1/flows/{fid}"))
        flows[name] = {k: ident[k] for k in ("flow_id", "name", "identity_sha256", "flags", "node_count",
                                              "edge_count")}
        if ident["prompt_sha256"]:
            repo = (REPO_ROOT / "prompts" / PROMPT_FILES[name]).read_text(encoding="utf-8")
            # Langflow stores the Agent Instructions without the file's final newline.
            prompts[name] = {"sha256": ident["prompt_sha256"], "repo_file": f"prompts/{PROMPT_FILES[name]}",
                             "repo_file_sha256": hashlib.sha256(repo.encode()).hexdigest(),
                             "matches_repo_file": sha(repo.rstrip("\n")) == ident["prompt_sha256"]}
        if ident["model"]:
            models[name] = ident["model"]
        for t, c in ident["components"].items():
            comps.setdefault(t, {})[name] = c
    card = httpx.get(f"{lf.base}/api/v1/a2a/{FLOWS['TS-20']}/.well-known/agent-card.json", timeout=30)
    cj = card.json() if card.status_code == 200 else {}
    gsha, gfiles = grader_sha256()
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    mcp_ver = re.search(r'name = "mcp"\nversion = "([^"]+)"', lock)
    a2a_ver = re.search(r'name = "a2a-sdk"\nversion = "([^"]+)"', lock)
    return {
        "langflow": {"version": version.get("version"), "package": version.get("package"),
                     "host": lf.base.split("//", 1)[-1]},
        "flows": flows, "prompts": prompts,
        "models": {"agents": models, "parameters_note": "Agent node settings as exported by the live instance"},
        "components": comps,
        "a2a": {"card_http_status": card.status_code, "protocol_version": cj.get("protocolVersion"),
                "preferred_transport": cj.get("preferredTransport"), "card_version": cj.get("version"),
                "security_schemes": sorted((cj.get("securitySchemes") or {}).keys()),
                "peer_flow_id": FLOWS["TS-20"]},
        "mcp": {"transport": "streamable-http", "lab_sdk_version": mcp_ver.group(1) if mcp_ver else None,
                "a2a_sdk_version_in_lock": a2a_ver.group(1) if a2a_ver else None},
        "harness": {"harness_version": HARNESS_VERSION, "case_set_version": case_defs.CASE_SET_VERSION,
                    "grader_sha256": gsha, "grader_files": gfiles, "cases": list(case_defs.CASES)},
    }


# ------------------------------------------------------------------ trial execution
def _output_text(resp: dict) -> str:
    texts = []
    for out in resp.get("outputs") or []:
        for o in out.get("outputs") or []:
            msg = ((o.get("results") or {}).get("message") or {})
            if isinstance(msg.get("text"), str):
                texts.append(msg["text"])
    return "\n\n".join(texts)


def _usage(msgs: list[dict]) -> tuple[dict | None, str | None]:
    tot = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    with_u = without = 0
    for m in msgs:
        if m.get("sender") != "Machine":
            continue
        u = ((m.get("properties") or {}).get("usage")) or {}
        vals = {k: u.get(k) for k in tot if isinstance(u.get(k), int)}
        if vals:
            with_u += 1
            for k, v in vals.items():
                tot[k] += v
        else:
            without += 1
    if not with_u:
        return None, (f"Langflow returned no token usage on {without} agent message(s) of this trial"
                      if without else "no agent message was stored for this trial's sessions")
    tot.update(messages_with_usage=with_u, messages_without_usage=without)
    return tot, (None if not without else f"usage missing on {without} of {with_u + without} agent messages")


def _tool_trace(msgs: list[dict]) -> tuple[list[dict], list[str]]:
    trace, outputs = [], []
    for m in msgs:
        for b in m.get("content_blocks") or []:
            for c in b.get("contents") or []:
                if c.get("type") == "tool_use":
                    out = c.get("output")
                    out_s = out if isinstance(out, str) else canonical(out)
                    outputs.append(out_s)
                    trace.append({"tool": c.get("name"), "input": redact(canonical(c.get("tool_input")))[:300],
                                  "output": redact(out_s)[:600]})
    return trace, outputs


def _known_ids(*observations: dict) -> set[str]:
    ids: set[str] = set()
    for o in observations:
        for key, col in (("events", "event_id"), ("runs", "run_id"), ("test_runs", "test_run_id"),
                         ("candidates", "candidate_id"), ("release_plans", "plan_id"), ("approvals", "approval_id"),
                         ("releases", "release_id"), ("a2a_exchanges", "exchange_id")):
            ids |= {r[col] for r in o.get(key) or []}
    return ids


def build_observation(case_id: str, case: dict, session: str, lo: datetime, hi: datetime, obs: dict, late: dict,
                      text: str, ctx: dict, index: set[str], tool_outputs: list[str]) -> dict:
    lo_s, hi_s = iso(lo - timedelta(seconds=5)), iso(hi + timedelta(seconds=5))

    def inwin(rows: list[dict]) -> list[dict]:
        return [r for r in rows if lo_s <= r["created_at"] <= hi_s]

    ns = f"{WS}:{case['role']}:lf-{session}"
    session_roots = [r for r in obs["runs"] if r["session_namespace"] == ns and r["parent_run_id"] is None]
    root = session_roots[0] if session_roots else None
    tree = [r for r in obs["runs"] if root and r["root_run_id"] == root["run_id"]]
    tree_ids = {r["run_id"] for r in tree}
    events = [e for e in obs["events"] if e["run_id"] in tree_ids]
    late_runs = [r["run_id"] for r in late.get("runs") or [] if session in r["session_namespace"]
                 and r["created_at"] > hi_s]
    trs = []
    for t in inwin(obs["test_runs"]):
        t = dict(t)
        t["cases"] = json.loads(t.pop("cases_json") or "[]")
        trs.append(t)
    window = {"events": inwin(obs["events"]), "runs": inwin(obs["runs"]), "test_runs": trs,
              "candidates": inwin(obs["candidates"]), "release_plans": inwin(obs["release_plans"]),
              "approvals": inwin(obs["approvals"]), "releases": inwin(obs["releases"]),
              "a2a_exchanges": inwin(obs["a2a_exchanges"])}
    return {"case_id": case_id, "session_id": session, "output_text": text, "root_run": root,
            "session_root_runs": session_roots, "tree_runs": tree, "tree_run_ids": tree_ids, "events": events,
            "window": window, "late_session_runs": late_runs, "context": ctx,
            "known_ids": index | _known_ids(obs, late), "langflow_tool_outputs": tool_outputs,
            "stories": obs["stories"], "memories": obs["memories"]}


def tweaks_for(case_id: str, lf: Langflow) -> dict | None:
    if case_id not in ("AE-06", "AE-07"):
        return None
    flow = lf.get(f"/api/v1/flows/{FLOWS['TS-10']}")
    by_type = {n["data"]["type"]: n for n in flow["data"]["nodes"]}
    if case_id == "AE-06":
        return {by_type["TaskSprintBoundedToolset"]["id"]: {"max_actions": 2}}
    node = by_type["TaskSprintA2AAudit"]
    card = node["data"]["node"]["template"]["card_url"]["value"]
    host = card.split("//", 1)[1].split("/", 1)[0]
    return {node["id"]: {"card_url": card.replace(host, case_defs.UNREACHABLE_PEER_HOST, 1)}}


def setup(case_id: str, lab: Lab, ctx: dict) -> list[str]:
    done = []
    for step in case_defs.CASES[case_id].get("setup", ()):
        if step == "load_faulty_fixture":
            r = lab.instructor("load_fixture", fixture="faulty_delete")
            ctx["faulty_candidate_id"] = r["candidate"]["candidate_id"]
            done.append(f"load_fixture faulty_delete -> {ctx['faulty_candidate_id']} (created={r['created']})")
        elif step == "outage_run_candidate_tests":
            r = lab.instructor("outage_enable", tool="run_candidate_tests", ttl_minutes=5)
            done.append(f"outage_enable run_candidate_tests {r['outage_id']} until {r['expires_at']}")
        elif step == "pending_story_and_preference":
            st = lab.ok("GET", "/v1/state", "coordinator")
            if not st.get("stories"):
                s = lab.ok("POST", "/v1/stories", "coordinator", {
                    "title": "Mark a task complete and keep it in the list",
                    "narrative": "As a workshop participant, I want to mark a task complete while retaining it in my "
                                 "list, so I can distinguish finished work from unfinished work.",
                    "criteria": ["A known task becomes completed and remains stored with the same ID/title",
                                 "Other task records are unchanged",
                                 "Completing an already completed task is safe",
                                 "An unknown task ID returns TASK_NOT_FOUND and changes no task data",
                                 "Add and list continue to work; list includes completed and incomplete tasks"],
                    "evidence_refs": ["tasksprint-product-brief@1.1:acceptance-criteria",
                                      "tasksprint-product-brief@1.1:completion-story"]})
                done.append(f"story {s['story_id']} (harness fixture, coordinator credential, no model)")
                ctx["pending_story_id"] = s["story_id"]
            else:
                ctx["pending_story_id"] = st["stories"][0]["story_id"]
                done.append(f"story {ctx['pending_story_id']} already present")
            lab.ok("POST", "/v1/memory", "coordinator", {"key": "release_notes_style", "value": "concise"})
            done.append("preference release_notes_style=concise (harness fixture)")
    return done


def teardown(case_id: str, lab: Lab) -> list[str]:
    if "outage_run_candidate_tests" in case_defs.CASES[case_id].get("setup", ()):
        r = lab.instructor("outage_disable", tool="run_candidate_tests")
        return [f"outage_disable run_candidate_tests disabled={r['disabled']}"]
    return []


def run_trial(case_id: str, rep: int, tag: str, lab: Lab, lf: Langflow, ctx: dict, index: set[str],
              raw_dir: Path) -> dict:
    case = case_defs.CASES[case_id]
    setup_log = setup(case_id, lab, ctx)
    if setup_log:
        time.sleep(SETTLE_S)
    session = f"ae-{case_id.lower()}-r{rep}-{tag}"
    prompt = case["prompt"].format(**ctx)
    tweaks = tweaks_for(case_id, lf)
    lab.sync_clock()
    lo = lab.now().replace(microsecond=0) - timedelta(seconds=1)
    log(f"{case_id} r{rep}: {case['flow']} session {session}")
    status_code, resp, latency = lf.run(case["flow"], prompt, session, tweaks)
    hi = lab.now().replace(microsecond=0) + timedelta(seconds=1)
    time.sleep(POST_TRIAL_S)
    text = _output_text(resp)
    obs = lab.observe(iso(lo - timedelta(seconds=10)), limit=5000)
    msgs = lf.messages(case["flow"], session)
    root = next((r for r in obs["runs"] if r["session_namespace"] == f"{WS}:{case['role']}:lf-{session}"
                 and r["parent_run_id"] is None), None)
    if root and case["flow"] == "TS-10":
        for child in ("TS-01", "TS-02", "TS-03"):
            msgs += lf.messages(child, root["run_id"])  # delegated child flows run in session = parent run ID
        msgs += lf.messages("TS-20", f"a2a-{root['run_id']}")
    trace, tool_outputs = _tool_trace(msgs)
    usage, usage_reason = _usage(msgs)
    time.sleep(SETTLE_S - POST_TRIAL_S)
    late = lab.observe(iso(hi), limit=500)
    tear = teardown(case_id, lab)
    o = build_observation(case_id, case, session, lo, hi, obs, late, text, ctx, index, tool_outputs)
    checks = graders.grade(case_id, o)
    passed = all(c["passed"] is True for c in checks)
    status = "error" if status_code != 200 else ("pass" if passed else "fail")
    trial = {
        "case_id": case_id, "repetition": rep, "status": status, "started_at": iso(lo), "ended_at": iso(hi),
        "latency_ms": latency, "session_id": session, "flow": case["flow"],
        "run_ids": [r["run_id"] for r in o["tree_runs"]][:12],
        "evidence_refs": sorted({e["event_id"] for e in o["events"]})[:40],
        "checks": checks, "usage": usage, "usage_unavailable_reason": usage_reason,
        "fault_injection": case.get("fault_injection"),
    }
    raw = {"trial": trial, "prompt": prompt, "tweaks": tweaks, "http_status": status_code,
           "langflow_error": resp.get("_error") or resp.get("_text") or (resp.get("detail") if status_code != 200 else None),
           "output_text": redact(text), "langflow_tool_trace": trace, "setup": setup_log, "teardown": tear,
           "tree_runs": o["tree_runs"],
           "tool_events": [{"event_id": e["event_id"], "run_id": e["run_id"], "actor": e["actor_role"],
                            "action": e["action"], "outcome": e["outcome"],
                            "tool": (e.get("details") or {}).get("tool"), "code": (e.get("details") or {}).get("code")}
                           for e in o["events"]],
           "window_counts": {k: len(v) for k, v in o["window"].items()}}
    (raw_dir / f"{case_id}-r{rep}.json").write_text(json.dumps(raw, indent=1, sort_keys=True, default=str))
    bad = [c["check_id"].split(".", 1)[1] for c in checks if c["passed"] is not True]
    log(f"{case_id} r{rep}: {status} in {latency} ms; runs={len(o['tree_runs'])} events={len(o['events'])}"
        + (f"; failed: {', '.join(bad)}" if bad else ""))
    return trial


def reset_workspace(lab: Lab, rep: int) -> dict:
    prev = lab.instructor("reset_preview")
    conf = lab.instructor("reset_confirm", confirm=WS)
    log(f"reset before repetition {rep}: generation {prev['generation']} -> {conf['generation']}; "
        f"export {conf['export']['export_id']}; live runs cancelled {len(prev['pending']['active_runs'])}")
    return {"repetition": rep, "preview_counts": prev["counts"], "preview_pending": {k: len(v) for k, v in
                                                                                     prev["pending"].items()},
            "from_generation": prev["generation"], "to_generation": conf["generation"],
            "export_id": conf["export"]["export_id"], "export_sha256": conf["export"]["export_sha256"],
            "event_id": conf["event_id"]}


# ------------------------------------------------------------------ summary
def write_summary(path: Path, rec: dict, report: dict, manifest: dict, resets: list[dict], wall_s: float,
                  ctx: dict, tag: str) -> None:
    rows = []
    for cid, s in rec["case_summary"].items():
        lat = s["latency_ms"] or {}
        rows.append(f"| {cid} {s['title']} | {s['denominator']} | {s['passed']} | {s['failed']} | {s['errors']} | "
                    f"{s['not_run']} | {s['critical_failures']} | {lat.get('min', '-')} / {lat.get('median', '-')} / "
                    f"{lat.get('max', '-')} | {s['usage_reported_trials']}/{s['denominator']} |")
    trials = []
    for t in report["trials"]:
        bad = [c["check_id"].split(".", 1)[1] for c in t["checks"] if c["passed"] is not True]
        u = t.get("usage") or {}
        trials.append(f"| {t['case_id']} | {t['repetition']} | {t['server_status']} | {t['critical_failures']} | "
                      f"{t['latency_ms']} | {u.get('total_tokens', 'not available')} | {', '.join(bad) or '-'} |")
    lines = [
        f"# Agent evaluation — rehearsal evidence ({rec['verdict']})", "",
        "**Label:** rehearsal evidence (workshop qualification sample, not production certification).",
        f"**Report:** `{rec['report_id']}` sha256 `{rec['report_sha256']}`  ",
        f"**Manifest:** `{rec['manifest_id']}` sha256 `{rec['manifest_sha256']}`  ",
        f"lab side `{rec['lab_side_sha256']}`, Langflow/harness side `{rec['system_sha256']}`  ",
        f"**Harness:** {HARNESS_VERSION}, case set {case_defs.CASE_SET_VERSION}, grader sha256 "
        f"`{manifest['harness']['grader_sha256']}`  ",
        f"**Run tag:** `{tag}`; window {report['started_at']} – {report['ended_at']}; wall time {wall_s:.0f} s; "
        f"repetitions {report['repetitions']}; workspace `{WS}` (resets: {len(resets)})  ",
        f"**Langflow:** {manifest['langflow']['version']}; model(s): "
        f"{sorted({m.get('model_name') for m in manifest['models']['agents'].values()})}; A2A card protocolVersion "
        f"{manifest['a2a']['protocol_version']}", "",
        f"Inputs: passing candidate `{ctx.get('passing_candidate_id')}` (report `{ctx.get('passing_test_run_id')}`), "
        f"faulty fixture `{ctx.get('faulty_candidate_id')}`.", "",
        "## Per-case results (server-computed)", "",
        "| Case | Denominator | Pass | Fail | Error | Not run | Critical | Latency ms min/median/max | Usage reported |",
        "|---|---|---|---|---|---|---|---|---|", *rows, "",
        f"Critical failures (all trials): **{rec['critical_failures']}**. Failed trials: **{rec['failed_trials']}**.",
        "Verdict reasons: " + ("; ".join(rec["verdict_reasons"]) or "none"), "",
        "## Trials", "", "| Case | Rep | Status | Critical | Latency ms | Tokens (total) | Failed checks |",
        "|---|---|---|---|---|---|---|", *trials, "",
        "## Fault injections (per run only; saved flows unchanged)", "",
        *[f"* {cid}: {c['fault_injection']}" for cid, c in case_defs.CASES.items() if c.get("fault_injection")], "",
        "## Limitations", "",
        f"* Small sample: {report['repetitions']} repetitions of 8 cases. Counts and observed failures only; no "
        "reliability percentage is claimed.",
        "* Workshop rehearsal evidence in one synthetic workspace; not production certification and not evidence "
        "that five agents outperform one agent (no single-agent baseline was run).",
        "* Lexical checks compare outputs with recorded evidence or look for prohibited claims; they can miss "
        "paraphrases. Critical checks are state/record based.",
        "* Token usage is what Langflow stored on agent messages; missing usage is 'not available', never zero. "
        "No cost is computed in this summary.", "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ------------------------------------------------------------------ commands
def clients() -> tuple[Lab, Langflow]:
    tokens = read_env(DEFAULT_TOKENS_FILE)
    missing = [v for v in TOKEN_VARS.values() if not tokens.get(v)]
    if missing:
        raise SetupError("role token variables missing: " + ", ".join(missing))
    key = read_env(DEFAULT_BOOTSTRAP_FILE).get("LANGFLOW_BOOTSTRAP_API_KEY", "")
    if not key:
        raise SetupError("LANGFLOW_BOOTSTRAP_API_KEY missing")
    return Lab(DEFAULT_LAB_URL, tokens), Langflow(DEFAULT_LANGFLOW_URL, key)


def context(lab: Lab) -> dict:
    ready = lab.ok("GET", "/v1/readiness", "operations")
    cand = ready.get("candidate") or {}
    tests = next((g for g in ready["gates"] if g["gate"] == "application_tests"), {})
    if not cand.get("candidate_id") or tests.get("status") != "PASS":
        raise SetupError("no passing candidate (readiness application_tests not PASS); run Phase 07 checks first")
    return {"passing_candidate_id": cand["candidate_id"], "passing_test_run_id": tests["test_run_id"],
            "faulty_candidate_id": "(loaded during setup)", "readiness_event_id": ready["readiness_event_id"],
            "deploy_status_before": ready["deploy"]}


def cmd_attest(lab: Lab, lf: Langflow) -> int:
    system = system_manifest(lf)
    r = lab.ok("POST", "/v1/agent-system-manifests/attestations", "evaluator", {"system": system})
    print(json.dumps({k: r[k] for k in ("attestation_id", "system_sha256", "lab_side_sha256", "qualified_manifest_id",
                                        "matches_qualified", "differences")}, indent=1))
    print("gate:", r["gate"]["status"], r["gate"].get("reason", ""))
    return 0 if r["gate"]["status"] == "PASS" else 1


def cmd_probe(lab: Lab) -> int:
    fails = 0
    for path, method in (("/v1/agent-evaluations/aer_" + "0" * 24, "GET"), ("/v1/agent-system-manifests/qualified", "GET"),
                         ("/v1/evaluator/observations", "GET"), ("/v1/agent-evaluations", "POST"),
                         ("/v1/agent-system-manifests/attestations", "POST")):
        code, _, _ = lab.req(method, path, "developer", {} if method == "POST" else None,
                             params={"since": EPOCH} if "observations" in path else None)
        ok = code == 403
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'} developer {method} {path} -> {code}")
    terms = ["grader critical check AE-03 one_repair", "agent cases graders citations_grounded",
             "run_agent_evals harness verdict QUALIFIED", "reference_complete fixture solution"]
    for q in terms:
        code, body, _ = lab.req("POST", "/v1/knowledge/search", "developer", {"query": q})
        docs = sorted({r["citation"]["doc_id"] for r in body.get("results") or []})
        leaked = [r for r in body.get("results") or [] if re.search(r"(def grade|_ae0\d|check_catalog|GRADERS)",
                                                                       r.get("text", ""))]
        ok = code == 200 and not leaked and set(docs) <= graders.APPROVED_DOCS
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'} developer knowledge search {q!r} -> {code} docs={docs} grader_text={len(leaked)}")
    code, body, _ = lab.req("GET", "/v1/skills", "developer")
    names = [s["name"] for s in body.get("skills") or []]
    ok = code == 200 and not [n for n in names if "eval" in n or "grader" in n]
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} developer skills list -> {names}")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--cases", default=",".join(case_defs.RUN_ORDER))
    ap.add_argument("--dry-run", action="store_true", help="manifest + plan only; no flow run, no write")
    ap.add_argument("--no-reset", action="store_true", help="do not reset demo-001 between repetitions (partial)")
    ap.add_argument("--attest", action="store_true", help="attest the live Langflow/harness manifest and exit")
    ap.add_argument("--probe-isolation", action="store_true", help="developer-credential grader isolation probes")
    ap.add_argument("--label", default="rehearsal evidence")
    a = ap.parse_args(argv)
    try:
        lab, lf = clients()
        if a.attest:
            return cmd_attest(lab, lf)
        if a.probe_isolation:
            return cmd_probe(lab)
        wanted = [c.strip().upper() for c in a.cases.split(",") if c.strip()]
        unknown = [c for c in wanted if c not in case_defs.CASES]
        if unknown or not 1 <= a.repeats <= 5:
            raise SetupError(f"unknown cases {unknown} or repeats outside 1..5")
        order = [c for c in case_defs.RUN_ORDER if c in wanted]
        full = order == list(case_defs.RUN_ORDER) and a.repeats >= 3 and not a.no_reset
        r = httpx.get(DEFAULT_LAB_URL + "/healthz", timeout=20)
        if r.status_code != 200:
            raise SetupError(f"lab /healthz -> {r.status_code}")
        manifest = system_manifest(lf)
        gate = lab.ok("GET", "/v1/agent-system-manifests/qualified", "evaluator")
        ctx = context(lab)
        log(f"lab gate before run: {gate['status']}; current lab side {gate['current_lab_side_sha256'][:16]}…")
        log(f"Langflow {manifest['langflow']['version']}; system sha256 {sha(manifest)[:16]}…; grader "
            f"{manifest['harness']['grader_sha256'][:16]}…; passing candidate {ctx['passing_candidate_id']}")
        mism = [k for k, v in manifest["prompts"].items() if not v["matches_repo_file"]]
        if mism:
            log(f"NOTE live prompt differs from repo file for {mism}")
        if a.dry_run:
            for rep in range(1, a.repeats + 1):
                for cid in order:
                    c = case_defs.CASES[cid]
                    print(f"  r{rep} {cid} {c['flow']} setup={list(c.get('setup', ()))} "
                          f"fault={'yes' if c.get('fault_injection') else 'no'} checks={len(c['checks']) + 3}")
            print(f"purpose={'qualification' if full else 'partial'}; resets={0 if a.no_reset else a.repeats}; "
                  f"trials={len(order) * a.repeats}; no flow invoked, nothing written")
            return 0
        tag = secrets.token_hex(3)
        raw_dir = REPO_ROOT / ".local" / "evals" / tag
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "system_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
        index = _known_ids(lab.observe(EPOCH, limit=5000))
        t_start = time.monotonic()
        lab.sync_clock()
        run_lo = lab.now().replace(microsecond=0) - timedelta(seconds=2)
        trials, resets = [], []
        for rep in range(1, a.repeats + 1):
            if not a.no_reset:
                resets.append(reset_workspace(lab, rep))
                time.sleep(SETTLE_S)
            for cid in order:
                trials.append(run_trial(cid, rep, tag, lab, lf, ctx, index, raw_dir))
        lab.sync_clock()
        run_hi = lab.now().replace(microsecond=0) + timedelta(seconds=1)
        wall = time.monotonic() - t_start
        raw_files = sorted(raw_dir.glob("AE-*.json"))
        digest = sha({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in raw_files})
        (raw_dir / "resets.json").write_text(json.dumps(resets, indent=1))
        body = {"harness_version": HARNESS_VERSION, "purpose": "qualification" if full else "partial",
                "label": a.label[:80], "repetitions": a.repeats, "started_at": iso(run_lo), "ended_at": iso(run_hi),
                "system": manifest, "check_catalog": case_defs.check_catalog(),
                "trials": trials, "trajectory_digest_sha256": digest,
                "telemetry_notes": ("usage = Langflow-stored token usage on agent messages of the trial's sessions "
                                    "(parent and delegated child flows); null + reason where absent. Latency = "
                                    "wall time of the run-API call. No cost computed.")}
        size = len(canonical(body))
        log(f"submitting report: {len(trials)} trials, {size} bytes")
        rec = lab.ok("POST", "/v1/agent-evaluations", "evaluator", body, timeout=120)
        report = lab.ok("GET", f"/v1/agent-evaluations/{rec['report_id']}", "evaluator")["report"]
        out = REPO_ROOT / "reports" / "redacted"
        out.mkdir(parents=True, exist_ok=True)
        md = out / f"agent_eval_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}_{tag}.md"
        write_summary(md, rec, report, manifest, resets, wall, ctx, tag)
        (raw_dir / "lab_record.json").write_text(json.dumps(rec, indent=1, sort_keys=True))
        log(f"report {rec['report_id']} verdict {rec['verdict']} critical {rec['critical_failures']} failed trials "
            f"{rec['failed_trials']}; manifest {rec['manifest_id']}; gate {rec['gate']['status']}")
        log(f"summary {md.relative_to(REPO_ROOT)}; raw .local/evals/{tag}/ (digest {digest[:16]}…); wall {wall:.0f} s")
        for reason in rec["verdict_reasons"]:
            log(f"  reason: {reason}")
        return 0 if rec["verdict"] == "QUALIFIED" or not full else 1
    except SetupError as exc:
        print(f"ERROR {redact(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
