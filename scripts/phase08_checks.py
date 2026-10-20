#!/usr/bin/env python3
"""Phase 08 protocol and backend evidence (Build Guide 08.3-08.6, Gate 08; Acceptance A2A-01..04).

  uv run --frozen --no-dev python scripts/phase08_checks.py card            # A2A-01 discovery
  uv run --frozen --no-dev python scripts/phase08_checks.py auth            # A2A-03 unauthorized + authorized
  uv run --frozen --no-dev python scripts/phase08_checks.py task --task-id <id>     # tasks/get read-back
  uv run --frozen --no-dev python scripts/phase08_checks.py exchange --id a2ax_...  # lab exchange record
  uv run --frozen --no-dev python scripts/phase08_checks.py events [--since ISO]
  uv run --frozen --no-dev python scripts/phase08_checks.py lab               # deployed lab version + routes

Raw A2A JSON-RPC 0.3 (the version the installed card advertises) over httpx: message/send and tasks/get.
Keys are read from git-ignored files and never printed: the runtime key TS_A2A_API_KEY
(.local/railway/a2a_runtime.env), the bootstrap key only for the owner-scoped agent listing, role tokens
for lab reads. Only IDs, states, status codes and the artifact text are printed.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lf_common import (DEFAULT_BOOTSTRAP_FILE, DEFAULT_LAB_URL, DEFAULT_LANGFLOW_URL, DEFAULT_TOKENS_FILE,  # noqa: E402
                       REPO_ROOT, read_env)

TS20 = "489890aa-4bd0-4641-b669-070f10e0922b"
A2A_FILE = REPO_ROOT / ".local/railway/a2a_runtime.env"
WS = "demo-001"
WRONG_KEY = "sk-" + "0" * 43  # syntactically plausible, not a real key


def card_url(base: str) -> str:
    return f"{base}/api/v1/a2a/{TS20}/.well-known/agent-card.json"


def rpc_url(base: str) -> str:
    return f"{base}/api/v1/a2a/{TS20}/jsonrpc"


def send_body(text: str | None, data: dict | None, context_id: str | None) -> dict:
    part = {"kind": "text", "text": text} if text is not None else {"kind": "data", "data": data}
    msg = {"kind": "message", "messageId": uuid.uuid4().hex, "role": "user", "parts": [part]}
    if context_id:
        msg["contextId"] = context_id
    return {"jsonrpc": "2.0", "id": uuid.uuid4().hex[:12], "method": "message/send", "params": {"message": msg}}


def summarize_task(t: dict) -> dict:
    return {"task_id": t.get("id"), "context_id": t.get("contextId"), "kind": t.get("kind"),
            "state": (t.get("status") or {}).get("state"),
            "artifact_ids": [a.get("artifactId") for a in t.get("artifacts") or []],
            "message_ids": [m.get("messageId") for m in t.get("history") or []],
            "artifact_text": "\n".join(p.get("text", "") for a in t.get("artifacts") or [] for p in a.get("parts") or []
                                       if p.get("kind") == "text")[:3000]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=("card", "auth", "task", "exchange", "events", "lab"))
    p.add_argument("--task-id", default="")
    p.add_argument("--id", default="")
    p.add_argument("--since", default="")
    p.add_argument("--text", default="Read-only connectivity check: report the current active release revision and "
                                     "app health using your own tools. Do not create any plan.")
    p.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    p.add_argument("--lab-url", default=DEFAULT_LAB_URL)
    a = p.parse_args(argv)
    base = a.langflow_url.rstrip("/")
    key = read_env(A2A_FILE).get("TS_A2A_API_KEY", "") if A2A_FILE.is_file() else ""
    if a.what == "card":
        boot = read_env(DEFAULT_BOOTSTRAP_FILE)["LANGFLOW_BOOTSTRAP_API_KEY"]
        agents = httpx.get(base + "/api/v1/a2a/agents", headers={"x-api-key": boot}, timeout=60).json()
        print("AGENTS", json.dumps([{k: x[k] for k in ("id", "name", "cardUrl")} for x in agents]))
        anon = httpx.get(card_url(base), timeout=60)
        authd = httpx.get(card_url(base), headers={"x-api-key": key}, timeout=60)
        print(f"CARD without key -> HTTP {anon.status_code}; with key -> HTTP {authd.status_code}; identical="
              f"{anon.status_code == 200 and anon.json() == authd.json()}")
        if anon.status_code == 200:
            card = anon.json()
            for s in card.get("skills", []):
                s["inputSchema"] = s.get("inputSchema")
            print(json.dumps(card, indent=1, sort_keys=True))
            out = REPO_ROOT / ".local/phase08/agent-card.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(card, indent=1, sort_keys=True))
        return 0
    if a.what == "auth":
        cases = [("no key", {}), ("wrong key", {"x-api-key": WRONG_KEY}), ("TS_A2A_API_KEY", {"x-api-key": key})]
        for label, hdr in cases:
            body = send_body(a.text, None, f"phase08-auth-{label.replace(' ', '-').lower()}")
            r = httpx.post(rpc_url(base), json=body, headers=hdr, timeout=170)
            line = f"message/send [{label}] -> HTTP {r.status_code}"
            try:
                j = r.json()
            except ValueError:
                j = {"text": r.text[:200]}
            if r.status_code == 200 and "result" in j:
                print(line, "ACCEPTED", json.dumps(summarize_task(j["result"]), indent=1))
            else:
                print(line, "REJECTED", json.dumps(j)[:300])
        return 0
    if a.what == "task":
        body = {"jsonrpc": "2.0", "id": "get-1", "method": "tasks/get", "params": {"id": a.task_id}}
        for label, hdr in (("no key", {}), ("TS_A2A_API_KEY", {"x-api-key": key})):
            r = httpx.post(rpc_url(base), json=body, headers=hdr, timeout=60)
            j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"text": r.text[:200]}
            print(f"tasks/get [{label}] -> HTTP {r.status_code}",
                  json.dumps(summarize_task(j["result"]), indent=1) if "result" in j else json.dumps(j)[:300])
        return 0
    t = read_env(DEFAULT_TOKENS_FILE)
    lab = a.lab_url.rstrip("/")
    if a.what == "exchange":
        r = httpx.get(f"{lab}/v1/a2a-exchanges/{a.id}", headers={"Authorization": "Bearer " + t["TS_INSTRUCTOR_TOKEN"],
                                                                  "X-TaskSprint-Workspace": WS}, timeout=60)
        j = r.json()
        j.pop("raw", None)
        print(r.status_code, json.dumps(j, indent=1, sort_keys=True))
        return 0
    if a.what == "events":
        r = httpx.get(f"{lab}/v1/events", params={"limit": 50},
                      headers={"Authorization": "Bearer " + t["TS_COORD_TOKEN"], "X-TaskSprint-Workspace": WS}, timeout=60)
        for e in reversed(r.json()["events"]):
            if e["created_at"] >= a.since:
                d = e.get("details") or {}
                keep = {k: d[k] for k in ("tool", "code", "parent_run_id", "depth", "plan_id", "exchange_id", "task_id",
                                          "context_id", "state", "gates", "peer_runs", "linked", "name", "version",
                                          "error_code", "candidate_id") if k in d}
                print(f"{e['created_at']} {e['event_id']} {e['actor_role']:<12} {e['action']:<20} {e['outcome']:<9} "
                      f"run={e.get('run_id') or '-'} {json.dumps(keep, sort_keys=True)}")
        return 0
    # lab: deployed version + whether the Phase 08 routes exist
    ops = {"Authorization": "Bearer " + t["TS_OPS_TOKEN"], "X-TaskSprint-Workspace": WS}
    r = httpx.get(f"{lab}/v1/readiness", headers=ops, timeout=60)
    print(f"GET /v1/readiness -> {r.status_code} {'(Phase 08 lab deployed)' if r.status_code == 200 else '(old lab)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
