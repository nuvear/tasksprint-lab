#!/usr/bin/env python3
"""Phase 11 read-only evidence helper for the full rehearsal (Build Guide 11.1-11.6). No model is involved.

  uv run --frozen --no-dev python scripts/phase11_checks.py snapshot [--since ISO]
  uv run --frozen --no-dev python scripts/phase11_checks.py plan --plan-id plan_...
  uv run --frozen --no-dev python scripts/phase11_checks.py events --since ISO [--grep ACTION]
  uv run --frozen --no-dev python scripts/phase11_checks.py replay --plan-id plan_...   (SEC-09, live, safe)

`snapshot` reads: lab /healthz, app health, active release + history, workspace generation, task records
(the application role's read-only `list` command, the same command TS-30 sends), and the records created
since --since (evaluator observations: candidates, test runs, plans, approvals, releases, A2A exchanges).
It never creates a plan, an approval, an execution or an instructor action.

`replay` rehearses "response lost after a committed execution" (Build Guide 11.6, ACCEPTANCE SEC-09) against
an ALREADY EXECUTED plan: the client first reconciles by reading the plan's execution status (A5: a timeout
does not establish failure), then retries the identical request with the Operations credential. The lab must
return the ORIGINAL receipt (`replayed: true`) and change nothing: same active hash, same release revision,
same number of release records. A retry with the same server-derived action ID but a changed payload must be
refused ACTION_CONFLICT. Both requests are executions only in name: step 2 of the A11 transaction answers
them before any approval, evidence or pointer is touched. Tokens are read from
.local/railway/role_tokens.env and never printed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lf_common import DEFAULT_LAB_URL, DEFAULT_TOKENS_FILE, SetupError, read_env  # noqa: E402
from phase09_checks import VARS, Lab, err  # noqa: E402


def tasks(lab: Lab) -> list[dict]:
    code, body = lab.req("POST", "/v1/app/commands", "application", {"command": "list"})
    if code != 200:
        raise SetupError(f"list -> {code}")
    return (body.get("data") or {}).get("tasks") or []


def cmd_snapshot(lab: Lab, a) -> None:
    r = httpx.get(lab.base + "/healthz", timeout=20)
    print(f"HEALTHZ {r.status_code} {r.text[:80]}")
    _, h = lab.req("GET", "/v1/app-health", "operations")
    print("APP_HEALTH " + json.dumps({k: h.get(k) for k in ("status", "business_health", "active_candidate_id",
                                                            "active_sha256", "drills", "faults", "reasons")
                                       if k in h}, sort_keys=True)[:900])
    st = lab.req("GET", "/v1/releases", "operations")[1]
    act = st["active"]
    print(f"ACTIVE {act['candidate_id']} sha256 {act['sha256']} revision {act['release_revision']}")
    for x in st.get("history", [])[-6:]:
        print("HISTORY " + json.dumps({k: x.get(k) for k in ("release_revision", "operation", "release_id", "plan_id",
                                                             "active_sha256", "previous_sha256", "created_at")},
                                      sort_keys=True))
    for t in tasks(lab):
        print("TASK " + json.dumps(t, sort_keys=True))
    since = a.since or "2026-10-20T00:00:00Z"
    _, ob = lab.req("GET", f"/v1/evaluator/observations?since={since}&limit=1", "evaluator")
    print(f"GENERATION {ob.get('generation')} stopped={ob.get('stopped')} counts={json.dumps(ob.get('counts'), sort_keys=True)}")
    if a.since:
        _, ob = lab.req("GET", f"/v1/evaluator/observations?since={since}&limit=5000", "evaluator")
        for k in ("candidates", "test_runs", "a2a_exchanges", "release_plans", "approvals", "releases"):
            for row in ob.get(k, []):
                row = {kk: v for kk, v in row.items() if kk != "cases_json"}
                print(f"{k.upper()} " + json.dumps(row, sort_keys=True)[:400])
        for s in ob.get("stories", []):
            print("STORY " + json.dumps({k: s.get(k) for k in ("story_id", "stage", "scope_confirmed", "candidate_id",
                                                               "repair_count", "revision", "updated_at")}, sort_keys=True))
        print(f"EVENTS {len(ob.get('events', []))} since {since}")


def cmd_plan(lab: Lab, a) -> None:
    _, v = lab.req("GET", f"/v1/release-plans/{a.plan_id}", "human_approver")
    p = v.get("plan") or {}
    print("PLAN " + json.dumps({k: p.get(k) for k in ("plan_id", "operation", "environment", "candidate_id",
                                                      "target_sha256", "baseline_sha256", "expected_release_revision",
                                                      "app_test_run_id", "agent_manifest_id", "expires_at",
                                                      "plan_sha256", "created_at")}, sort_keys=True))
    print("STATE " + json.dumps({k: v.get(k) for k in ("state", "effective_state", "snapshot_sha256", "decision",
                                                       "execution", "generation")}, sort_keys=True))


def cmd_events(lab: Lab, a) -> None:
    _, ob = lab.req("GET", f"/v1/evaluator/observations?since={a.since}&limit=5000", "evaluator")
    for e in ob.get("events", []):
        if a.grep and a.grep not in e["action"]:
            continue
        print(f"EVENT {e['created_at']} {e['event_id']} {e['actor_role']} {e['action']} {e['outcome']} run={e['run_id']} "
              f"{json.dumps(e['details'], sort_keys=True)[:a.width]}")


def cmd_replay(lab: Lab, a) -> None:
    def rel_state() -> tuple:
        st = lab.req("GET", "/v1/releases", "operations")[1]
        return (st["active"]["sha256"], st["active"]["release_revision"], len(st.get("history", [])),
                tuple(h["release_id"] for h in st.get("history", [])))
    _, view = lab.req("GET", f"/v1/release-plans/{a.plan_id}", "operations")
    ex = view.get("execution") or {}
    lab.check(bool(ex.get("release_id")), f"reconcile first: plan {a.plan_id} state {view.get('state')} already has "
                                          f"receipt {ex.get('release_id')} (action {ex.get('action_id')})")
    before = rel_state()
    print(f"INFO before: active {before[0][:16]}... revision {before[1]} release records {before[2]}")
    code, body = lab.req("POST", "/v1/release-executions", "operations", {"plan_id": a.plan_id})
    rc = body.get("receipt") or {}
    lab.check(code in (200, 201) and body.get("replayed") is True and rc.get("receipt_id") == ex.get("release_id"),
              f"identical retry -> {code} replayed={body.get('replayed')} receipt {rc.get('receipt_id')} "
              f"action {rc.get('action_id')}")
    lab.check(rel_state() == before, "no second activation: active hash, release revision and release records unchanged")
    code, body = lab.req("POST", "/v1/release-executions", "operations",
                         {"plan_id": a.plan_id, "plan_sha256": view["plan"]["plan_sha256"]})
    e = body.get("error") or {}
    lab.check(code == 409 and e.get("code") == "ACTION_CONFLICT",
              f"same action ID, changed payload -> {code} {err(body)} step {(e.get('details') or {}).get('step')}")
    lab.check(rel_state() == before, "still unchanged after the conflicting retry")
    _, ev = lab.req("GET", "/v1/events?limit=10", "operations")
    for x in reversed(ev.get("events", [])):
        if x["action"] == "release.execute" and a.plan_id in json.dumps(x["details"]):
            print(f"EVENT {x['created_at']} {x['event_id']} {x['action']} {x['outcome']} "
                  f"{json.dumps(x['details'], sort_keys=True)[:200]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("check", choices=("snapshot", "plan", "events", "replay"))
    p.add_argument("--plan-id")
    p.add_argument("--since")
    p.add_argument("--grep", default="")
    p.add_argument("--width", type=int, default=300)
    p.add_argument("--lab-url", default=DEFAULT_LAB_URL)
    p.add_argument("--tokens-file", type=Path, default=DEFAULT_TOKENS_FILE)
    a = p.parse_args(argv)
    try:
        toks = read_env(a.tokens_file)
        if any(len(toks.get(v, "")) < 32 for v in VARS.values()):
            raise SetupError("tokens file lacks a role token")
        if a.check in ("plan", "replay") and not (a.plan_id or "").startswith("plan_"):
            raise SetupError("--plan-id is required")
        if a.check == "events" and not a.since:
            raise SetupError("--since is required")
        lab = Lab(a.lab_url, toks)
        {"snapshot": cmd_snapshot, "plan": cmd_plan, "events": cmd_events, "replay": cmd_replay}[a.check](lab, a)
        if a.check == "replay":
            print(f"SUMMARY replay: {'PASS' if not lab.fails else 'FAIL'} ({lab.fails} failed)")
        return 1 if lab.fails else 0
    except (SetupError, httpx.HTTPError, KeyError) as e:
        print(f"ERROR {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
