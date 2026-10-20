#!/usr/bin/env python3
"""Phase 09 live checks against the deployed lab (Build Guide 09.3-09.5, Gate 09). No model is involved.

  uv run --frozen --no-dev python scripts/phase09_checks.py lab
  uv run --frozen --no-dev python scripts/phase09_checks.py plan --candidate-id cand_...      (TEST EVIDENCE)
  uv run --frozen --no-dev python scripts/phase09_checks.py direct-exec --plan-id plan_...   (SEC-05)
  uv run --frozen --no-dev python scripts/phase09_checks.py forged --plan-id plan_...        (SEC-06)
  uv run --frozen --no-dev python scripts/phase09_checks.py mismatch --plan-id plan_...      (SEC-07)
  uv run --frozen --no-dev python scripts/phase09_checks.py exec --plan-id plan_...          (approved -> step 5)
  uv run --frozen --no-dev python scripts/phase09_checks.py roles --plan-id plan_...         (Gate 09 role denials)
  uv run --frozen --no-dev python scripts/phase09_checks.py inspect --plan-id plan_... [--since ISO]

`plan` creates a deploy plan with the OPERATIONS credential from this trusted script (no model), as
the Build Guide 09.3 permits for control tests: it is labelled test evidence, not an agent action.
Expiry, identical/changed replay, stale revision and environment mismatch need a successful
execution or a 15-minute wait; they run in tests/security/test_approval_execution.py (isolated test
databases with a TEST-ONLY manifest stand-in) and are not repeated against the live lab.
Tokens are read from .local/railway/role_tokens.env and never printed. Exit 0 = every check PASS.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lf_common import DEFAULT_LAB_URL, DEFAULT_TOKENS_FILE, SetupError, read_env  # noqa: E402

WS = "demo-001"
VARS = {"coordinator": "TS_COORD_TOKEN", "product_owner": "TS_PO_TOKEN", "developer": "TS_DEV_TOKEN",
        "qa": "TS_QA_TOKEN", "operations": "TS_OPS_TOKEN", "application": "TS_APP_TOKEN",
        "human_approver": "TS_APPROVER_TOKEN", "instructor": "TS_INSTRUCTOR_TOKEN", "evaluator": "TS_EVALUATOR_TOKEN"}
AGENTS = ("coordinator", "product_owner", "developer", "qa", "operations", "application")


class Lab:
    def __init__(self, base: str, tokens: dict[str, str]):
        self.base, self.tokens, self.fails = base.rstrip("/"), tokens, 0

    def req(self, method: str, path: str, role: str, body: dict | None = None, ws: str | None = WS):
        h = {"Authorization": f"Bearer {self.tokens[VARS[role]]}", "User-Agent": "phase09_checks"}
        if ws:
            h["X-TaskSprint-Workspace"] = ws
        r = httpx.request(method, self.base + path, json=body, headers=h, timeout=60, follow_redirects=False)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}

    def check(self, ok: bool, what: str) -> None:
        self.fails += not ok
        print(f"{'PASS' if ok else 'FAIL'} {what}")


def err(body: dict) -> str:
    e = body.get("error") or {}
    return f"{e.get('code')} [{e.get('request_id')}]"


def releases(lab: Lab) -> dict:
    return lab.req("GET", "/v1/releases", "operations")[1]


def cmd_lab(lab: Lab, a) -> None:
    r = httpx.get(lab.base + "/healthz", timeout=20)
    lab.check(r.status_code == 200, f"GET /healthz -> {r.status_code}")
    code, body = lab.req("POST", "/v1/approvals", "operations", {})
    lab.check(code == 403, f"POST /v1/approvals as operations -> {code} (403 = Phase 09 route deployed)")
    code, body = lab.req("POST", "/v1/release-executions", "operations", {"plan_id": "plan_" + "0" * 24})
    lab.check(code == 404 and (body.get("error") or {}).get("code") == "PLAN_NOT_FOUND",
              f"POST /v1/release-executions unknown plan -> {code} {err(body)}")
    code, body = lab.req("POST", "/v1/instructor/actions", "instructor", {"action": "reset_preview", "workspace_id": WS},
                         ws=None)
    lab.check(code == 200 and "pending" in body, f"reset_preview (read-only) -> {code} generation={body.get('generation')}"
              f" stopped={body.get('stopped')} counts={json.dumps(body.get('counts'), sort_keys=True)}")
    st = releases(lab)["active"]
    print(f"INFO active {st['candidate_id']} sha256 {st['sha256'][:16]}... revision {st['release_revision']}")


def cmd_plan(lab: Lab, a) -> None:
    code, ready = lab.req("GET", f"/v1/readiness?candidate_id={a.candidate_id}", "operations")
    gates = {g["gate"]: g["status"] for g in ready.get("gates", [])}
    print(f"INFO readiness {ready.get('deploy')} gates={gates} event={ready.get('readiness_event_id')}")
    code, body = lab.req("POST", "/v1/release-plans", "operations", {"action": "deploy", "candidate_id": a.candidate_id})
    lab.check(code == 201, f"TEST EVIDENCE (operations credential, trusted script, no model): create deploy plan -> "
                           f"{code} {err(body) if code != 201 else ''}")
    if code == 201:
        p = body["plan"]
        print(f"INFO plan {p['plan_id']} plan_sha256 {p['plan_sha256']} snapshot_sha256 {body['snapshot_sha256']} "
              f"state {body['state']} created={body['created']} expires {p['expires_at']} manifest "
              f"{p['agent_manifest_id']} tests {p['app_test_run_id']} revision {p['expected_release_revision']}")


def cmd_direct_exec(lab: Lab, a) -> None:
    before = releases(lab)
    code, body = lab.req("POST", "/v1/release-executions", "operations", {"plan_id": a.plan_id})
    lab.check(code == 409 and (body.get("error") or {}).get("code") == "APPROVAL_REQUIRED",
              f"SEC-05 direct execution, operations token, no approval -> {code} {err(body)} step "
              f"{(body.get('error') or {}).get('details', {}).get('step')}")
    lab.check(releases(lab) == before, "no active-version change and no new release record")


def cmd_forged(lab: Lab, a) -> None:
    before = releases(lab)
    for extra in ({"approved": True}, {"role": "human_approver"}, {"approval_id": "apr_" + "0" * 24}):
        code, body = lab.req("POST", "/v1/release-executions", "operations", {"plan_id": a.plan_id, **extra})
        lab.check(code == 422, f"SEC-06 execution with {list(extra)[0]} -> {code} {err(body)}")
    _, view = lab.req("GET", f"/v1/release-plans/{a.plan_id}", "human_approver")
    code, body = lab.req("POST", "/v1/approvals", "operations", {
        "plan_id": a.plan_id, "plan_sha256": view["plan"]["plan_sha256"], "snapshot_sha256": view["snapshot_sha256"],
        "decision": "approve"})
    lab.check(code == 403, f"SEC-06 operations tries to record an approval -> {code} {err(body)}")
    lab.check(releases(lab) == before, "no active-version change")


def cmd_mismatch(lab: Lab, a) -> None:
    _, view = lab.req("GET", f"/v1/release-plans/{a.plan_id}", "human_approver")
    good = {"plan_id": a.plan_id, "plan_sha256": view["plan"]["plan_sha256"],
            "snapshot_sha256": view["snapshot_sha256"], "decision": "approve"}
    for field, expect in (("plan_sha256", "PLAN_HASH_MISMATCH"), ("snapshot_sha256", "SNAPSHOT_MISMATCH")):
        code, body = lab.req("POST", "/v1/approvals", "human_approver", {**good, field: "0" * 64})
        lab.check(code == 409 and (body.get("error") or {}).get("code") == expect,
                  f"SEC-07 approval quoting a wrong {field} -> {code} {err(body)} (nothing recorded)")
    _, after = lab.req("GET", f"/v1/release-plans/{a.plan_id}", "human_approver")
    lab.check(after.get("decision") is None or after["decision"] == view.get("decision"),
              f"decision unchanged: {after.get('decision')}")


def cmd_exec(lab: Lab, a) -> None:
    before = releases(lab)
    _, view = lab.req("GET", f"/v1/release-plans/{a.plan_id}", "human_approver")
    print(f"INFO plan {a.plan_id} state {view.get('state')} decision {json.dumps(view.get('decision'))}")
    code, body = lab.req("POST", "/v1/release-executions", "operations", {"plan_id": a.plan_id})
    e = body.get("error") or {}
    expect = {"approve": "AGENT_MANIFEST_NOT_QUALIFIED", "reject": "APPROVAL_REJECTED"}.get(
        (view.get("decision") or {}).get("decision"), "APPROVAL_REQUIRED")
    lab.check(code == 409 and e.get("code") == expect,
              f"execution after the human decision -> {code} {err(body)} step {e.get('details', {}).get('step')} "
              f"action {e.get('details', {}).get('action_id')}")
    lab.check(releases(lab) == before, "no active-version change and no new release record")
    _, again = lab.req("GET", f"/v1/release-plans/{a.plan_id}", "human_approver")
    print(f"INFO after: state {again.get('state')} decision status {(again.get('decision') or {}).get('status')}")


def cmd_roles(lab: Lab, a) -> None:
    _, view = lab.req("GET", f"/v1/release-plans/{a.plan_id}", "human_approver")
    appr = {"plan_id": a.plan_id, "plan_sha256": view["plan"]["plan_sha256"],
            "snapshot_sha256": view["snapshot_sha256"], "decision": "approve"}
    probes = [("POST", "/v1/approvals", appr, None),
              ("POST", "/v1/instructor/actions", {"action": "drill_enable", "workspace_id": WS,
                                                  "fault_type": "completion_unavailable",
                                                  "candidate_id": releases(lab)["active"]["candidate_id"]}, None),
              ("POST", "/v1/instructor/actions", {"action": "reset_confirm", "workspace_id": WS, "confirm": WS}, None),
              ("POST", "/v1/instructor/actions", {"action": "stop", "workspace_id": WS}, None),
              ("POST", "/v1/agent-evaluations", {"harness_version": "probe", "manifest": {}, "cases": [],
                                                 "repetitions": 1, "outcomes": {}}, WS)]
    for role in AGENTS:
        codes = [lab.req(m, p, role, b, ws=w)[0] for m, p, b, w in probes]
        lab.check(codes == [403] * len(probes), f"{role}: approvals/drill/reset/stop/evaluations -> {codes}")
    for role in ("human_approver", "instructor", "evaluator"):
        code = lab.req("POST", "/v1/release-executions", role, {"plan_id": a.plan_id})[0]
        lab.check(code == 403, f"{role}: release execution -> {code}")
        r = httpx.post(lab.base + "/mcp", headers={"Authorization": f"Bearer {lab.tokens[VARS[role]]}",
                                                    "X-TaskSprint-Workspace": WS, "Accept":
                                                    "application/json, text/event-stream"},
                       json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                           "protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "phase09-probe", "version": "0"}}}, timeout=30)
        lab.check(r.status_code == 403, f"{role} token at /mcp initialize -> {r.status_code}")
    _, after = lab.req("GET", f"/v1/release-plans/{a.plan_id}", "human_approver")
    lab.check(after.get("decision") == view.get("decision"), "no decision was created by any probe")


def cmd_inspect(lab: Lab, a) -> None:
    _, view = lab.req("GET", f"/v1/release-plans/{a.plan_id}", "human_approver")
    print("PLAN " + json.dumps({k: view.get(k) for k in ("state", "effective_state", "snapshot_sha256", "decision",
                                                         "execution", "generation")}, sort_keys=True))
    _, ev = lab.req("GET", "/v1/events?limit=50", "operations")
    for e in reversed(ev.get("events", [])):
        if a.since and e["created_at"] < a.since:
            continue
        d = e["details"]
        if a.plan_id in json.dumps(d) or e["action"] in ("release.execute", "approval.record", "authz.denied"):
            print(f"EVENT {e['created_at']} {e['event_id']} {e['actor_role']} {e['action']} {e['outcome']} "
                  f"{json.dumps(d, sort_keys=True)[:400]}")
    st = releases(lab)
    print(f"RELEASES active {st['active']['candidate_id']} revision {st['active']['release_revision']} history "
          f"{[(h['release_revision'], h['operation'], h['plan_id']) for h in st['history']]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("check", choices=("lab", "plan", "direct-exec", "forged", "mismatch", "exec", "roles", "inspect"))
    p.add_argument("--plan-id")
    p.add_argument("--candidate-id")
    p.add_argument("--since")
    p.add_argument("--lab-url", default=DEFAULT_LAB_URL)
    p.add_argument("--tokens-file", type=Path, default=DEFAULT_TOKENS_FILE)
    a = p.parse_args(argv)
    try:
        tokens = read_env(a.tokens_file)
        if any(len(tokens.get(v, "")) < 32 for v in VARS.values()):
            raise SetupError("tokens file lacks a role token")
        if a.check in ("direct-exec", "forged", "mismatch", "exec", "roles", "inspect") and not (
                a.plan_id or "").startswith("plan_"):
            raise SetupError("--plan-id is required")
        if a.check == "plan" and not (a.candidate_id or "").startswith("cand_"):
            raise SetupError("--candidate-id is required")
        lab = Lab(a.lab_url, tokens)
        globals()["cmd_" + a.check.replace("-", "_")](lab, a)
        print(f"SUMMARY {a.check}: {'PASS' if not lab.fails else 'FAIL'} ({lab.fails} failed)")
        return 1 if lab.fails else 0
    except (SetupError, httpx.HTTPError) as e:
        print(f"ERROR {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
