#!/usr/bin/env python3
"""Pre-class readiness check for the deployed TaskSprint workshop (Architecture A13, Build Guide 12.5).

  uv run --frozen --no-dev python scripts/doctor.py [--no-attest] [--no-model-probe] [--workspace demo-001]

Checks (each prints PASS/FAIL/NOTE; values of tokens and keys are never printed):
 1. lab liveness: GET /healthz 200 on the lab; GET /health 200 on Langflow and its reported version
 2. lab -> runner path: the application role's `complete T999` is answered by the bounded runner and changes
    nothing (records one app.complete event, the same probe as check_stack.py)
 3. workspace: generation reported, instructor stop flag off, active artifact = starter v0 (label starter-v0),
    business health healthy, exactly two tasks T001/T002, both incomplete
 4. nothing pending: the instructor `reset_preview` (read-only) lists no live run, open plan, active approval,
    enabled drill or outage
 5. agent-system manifest: the lab's qualified-manifest gate is PASS; a fresh attestation of the live flows
    (same manifest builder as run_agent_evals.py --attest) matches the qualified manifest (skip with --no-attest;
    then the age of the last verification against its 24 h window is checked instead)
 6. flows present: the seven TaskSprint flows exist exactly once in the TaskSprint project; TS-20 is published
    on A2A, TS-90 is on neither MCP nor A2A
 7. peer reachable: the TS-20 Agent Card is served (protocolVersion)
 8. model reachable: a registered model provider, every Agent node's model ID, and (unless --no-model-probe) one
    minimal live Product Owner turn that must return text (a real model call; it creates one lab run, which the
    following reset sweeps)
Langflow key: the setup-only bootstrap key (.local/railway/langflow_bootstrap.env) while it exists, otherwise the
runtime key file (.local/railway/a2a_runtime.env, TS_A2A_API_KEY). After the bootstrap key is revoked (12.3),
doctor keeps working with the runtime key. Exit 0 = no FAIL; 1 = a check failed; 2 = configuration error.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_agent_evals as rae  # noqa: E402  (read-only reuse of the harness's manifest builder and clients)
from lf_common import (DEFAULT_BOOTSTRAP_FILE, DEFAULT_LAB_URL, DEFAULT_LANGFLOW_URL, DEFAULT_TOKENS_FILE,  # noqa: E402
                       REPO_ROOT, SetupError, read_env, redact_text)

RUNTIME_KEY_FILE = REPO_ROOT / ".local/railway/a2a_runtime.env"
FLOW_NAMES = ("TS-30 To-do App", "TS-01 Product Owner", "TS-02 Developer", "TS-03 QA", "TS-20 Production Manager",
              "TS-10 Sprint Room", "TS-90 Instructor Console")
PROBE_PROMPT = ("Connectivity check before class: reply with the single word READY. Do not call any tool and do not "
                "record anything.")


class Doctor:
    def __init__(self) -> None:
        self.fails = 0

    def r(self, ok: bool, what: str) -> bool:
        self.fails += not ok
        print(f"{'PASS' if ok else 'FAIL'} {what}")
        return ok


def langflow_key(bootstrap: Path, runtime: Path, base: str) -> tuple[str, str]:
    for path, var, label in ((bootstrap, "LANGFLOW_BOOTSTRAP_API_KEY", "bootstrap (setup-only)"),
                             (runtime, "TS_A2A_API_KEY", "runtime")):
        try:
            key = read_env(path).get(var, "")
        except SetupError:
            continue
        if not key:
            continue
        code = httpx.get(base + "/api/v1/version", headers={"x-api-key": key}, timeout=20).status_code
        if code == 200:
            return key, label
        print(f"NOTE the {label} Langflow key file is present but the key is refused (HTTP {code}); "
              f"{'revoked as intended in 12.3?' if 'bootstrap' in label else ''}")
    raise SetupError("no working Langflow API key in the bootstrap or runtime key file")


def reply_text(result: dict) -> str:
    try:
        return result["outputs"][0]["outputs"][0]["results"]["message"]["text"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="demo-001")
    ap.add_argument("--lab-url", default=DEFAULT_LAB_URL)
    ap.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    ap.add_argument("--tokens-file", type=Path, default=DEFAULT_TOKENS_FILE)
    ap.add_argument("--bootstrap-file", type=Path, default=DEFAULT_BOOTSTRAP_FILE)
    ap.add_argument("--runtime-key-file", type=Path, default=RUNTIME_KEY_FILE)
    ap.add_argument("--no-attest", action="store_true", help="do not record a fresh attestation")
    ap.add_argument("--no-model-probe", action="store_true", help="skip the one live model turn")
    a = ap.parse_args(argv)
    if a.workspace != rae.WS:
        print(f"ERROR the harness clients are bound to {rae.WS}", file=sys.stderr)
        return 2
    d = Doctor()
    lab_base, lf_base = a.lab_url.rstrip("/"), a.langflow_url.rstrip("/")
    print(f"INFO doctor {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} lab {lab_base} langflow {lf_base} "
          f"workspace {a.workspace}")
    try:
        tokens = read_env(a.tokens_file)
        missing = [v for v in rae.TOKEN_VARS.values() if len(tokens.get(v, "")) < 32] + \
            ([] if len(tokens.get("TS_APP_TOKEN", "")) >= 32 else ["TS_APP_TOKEN"])
        if missing:
            raise SetupError("role token variables missing: " + ", ".join(missing))
        lab = rae.Lab(lab_base, tokens)
        # 1 liveness
        r = httpx.get(lab_base + "/healthz", timeout=20)
        d.r(r.status_code == 200, f"lab /healthz HTTP {r.status_code}")
        r = httpx.get(lf_base + "/health", timeout=20)
        d.r(r.status_code == 200, f"Langflow /health HTTP {r.status_code}")
        key, key_label = langflow_key(a.bootstrap_file, a.runtime_key_file, lf_base)
        lf = rae.Langflow(lf_base, key)
        ver = lf.get("/api/v1/version")
        d.r(ver.get("version") == "1.12.5", f"Langflow version {ver.get('version')} (Langflow key: {key_label})")
        # 2 runner path
        app = {"Authorization": f"Bearer {tokens['TS_APP_TOKEN']}", "X-TaskSprint-Workspace": a.workspace}
        rr = httpx.post(lab_base + "/v1/app/commands", json={"command": "complete T999"}, headers=app, timeout=60)
        data = (rr.json().get("data") or {}) if rr.status_code == 200 else {}
        ev = data.get("evaluation") or {}
        d.r(rr.status_code == 200 and str(ev.get("evaluated_by", "")).startswith("tasksprint-runner/")
            and data.get("tasks_changed") == 0,
            f"lab -> runner path: complete T999 -> {rr.status_code} {rr.json().get('code') if rr.status_code == 200 else ''}"
            f", runner {ev.get('evaluated_by')}, tasks changed {data.get('tasks_changed')}")
        # 3 workspace
        _, rel, _ = lab.req("GET", "/v1/releases", "operations")
        act = rel.get("active") or {}
        d.r(act.get("label") == "starter-v0", f"active artifact {act.get('candidate_id')} label {act.get('label')} "
                                             f"sha256 {str(act.get('sha256'))[:16]}… release revision {act.get('release_revision')}")
        _, h, _ = lab.req("GET", "/v1/app-health", "operations")
        d.r(h.get("status") == "healthy", f"business health {h.get('status')}")
        lr = httpx.post(lab_base + "/v1/app/commands", json={"command": "list"}, headers=app, timeout=30)
        tasks = ((lr.json().get("data") or {}).get("tasks") or []) if lr.status_code == 200 else []
        d.r([t.get("id") for t in tasks] == ["T001", "T002"] and not any(t.get("completed") for t in tasks),
            "tasks: " + ", ".join(f"{t.get('id')} {'[x]' if t.get('completed') else '[ ]'} {t.get('title')}" for t in tasks))
        # 4 nothing pending
        _, pv, _ = lab.req("POST", "/v1/instructor/actions", "instructor",
                           {"action": "reset_preview", "workspace_id": a.workspace})
        p = pv.get("pending") or {}
        busy = {k: len(v) for k, v in p.items() if v and k != "past_deadline_runs"}
        d.r(pv.get("stopped") is False and not busy,
            f"generation {pv.get('generation')}, stop flag {pv.get('stopped')}, pending {busy or 'none'} "
            f"(past-deadline runs {len(p.get('past_deadline_runs', []))}, swept by reset)" +
            (" - a live run can be doctor's own model probe from < 90 s ago; run doctor, then reset" if busy.get(
                "active_runs") else ""))
        # 5 manifest
        _, gate, _ = lab.req("GET", "/v1/agent-system-manifests/qualified", "evaluator")
        d.r(gate.get("status") == "PASS", f"qualified manifest gate {gate.get('status')}: {gate.get('agent_manifest_id')} "
                                          f"sha256 {str(gate.get('manifest_sha256'))[:16]}… qualified {gate.get('qualified_at')}")
        if a.no_attest:
            last = gate.get("last_verified_at")
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 3600 \
                if last else None
            d.r(age is not None and age < float(gate.get("verification_max_age_hours") or 24),
                f"last verification {last} ({age:.1f} h ago)" if age is not None else "never verified")
        else:
            att = lab.ok("POST", "/v1/agent-system-manifests/attestations", "evaluator", {"system": rae.system_manifest(lf)})
            d.r(att.get("matches_qualified") is True and att["gate"]["status"] == "PASS",
                f"fresh attestation {att.get('attestation_id')} matches_qualified={att.get('matches_qualified')} "
                f"differences={att.get('differences')}")
        # 6 flows
        proj = next(x for x in lf.get("/api/v1/projects/") if x["name"] == "TaskSprint")
        flows = [f for f in lf.get("/api/v1/flows/", folder_id=proj["id"], get_all="true", header_flows="true")
                 if f.get("folder_id") == proj["id"]]
        counts = {n: sum(f["name"] == n for f in flows) for n in FLOW_NAMES}
        d.r(all(c == 1 for c in counts.values()), f"seven TaskSprint flows present once each {counts}")
        by = {f["name"]: f for f in flows}
        ts20 = lf.get(f"/api/v1/flows/{by['TS-20 Production Manager']['id']}")
        ts90 = lf.get(f"/api/v1/flows/{by['TS-90 Instructor Console']['id']}")
        d.r(ts20.get("a2a_enabled") is True, "TS-20 published on A2A")
        d.r(ts90.get("a2a_enabled") is False and ts90.get("mcp_enabled") is False, "TS-90 on neither MCP nor A2A")
        # 7 peer
        card = httpx.get(f"{lf_base}/api/v1/a2a/{ts20['id']}/.well-known/agent-card.json", timeout=20)
        cj = card.json() if card.status_code == 200 else {}
        d.r(card.status_code == 200 and bool(cj.get("protocolVersion")),
            f"A2A peer card HTTP {card.status_code} protocolVersion {cj.get('protocolVersion')} name {cj.get('name')!r}")
        # 8 model
        pol = lf.get("/api/v1/model-provider-policy")
        provs = sorted({x.get("provider") for x in pol.get("registered_providers", [])})
        d.r("Anthropic" in provs, f"Anthropic is a registered provider ({len(provs)} registered; the live turn below "
                                  f"is the reachability proof)")
        idents = [rae.flow_identity(lf.get(f'/api/v1/flows/{by[n]["id"]}')).get("model") or {}
                  for n in FLOW_NAMES if n not in ("TS-30 To-do App", "TS-90 Instructor Console")]
        models = sorted({f"{m.get('provider')}/{m.get('model_name')} (max_iterations {m.get('max_iterations')})"
                         if isinstance(m, dict) else str(m) for m in idents})
        d.r(len(models) == 1 and "None" not in models[0], f"Agent model on all five agent flows: {models}")
        if a.no_model_probe:
            print("NOTE live model probe skipped (--no-model-probe): model reachability NOT verified")
        else:
            code, res, ms = lf.run("TS-01", PROBE_PROMPT, f"doctor-{uuid.uuid4().hex[:12]}", None)
            text = reply_text(res)
            d.r(code == 200 and bool(text.strip()),
                f"live model turn (TS-01) HTTP {code} in {ms / 1000:.1f} s, reply {redact_text(text.strip())[:60]!r}")
    except (SetupError, httpx.HTTPError, KeyError, StopIteration, ValueError) as e:
        print(f"ERROR {type(e).__name__}: {redact_text(str(e))}", file=sys.stderr)
        return 2
    print(f"SUMMARY doctor: {'PASS' if not d.fails else 'FAIL'} ({d.fails} failed)")
    return 1 if d.fails else 0


if __name__ == "__main__":
    sys.exit(main())
