#!/usr/bin/env python3
"""Export the sanitized TaskSprint flow bundle and verify it re-imports without drift (A13, Build Guide 11.6, REC-04).

  uv run --frozen --no-dev python scripts/export_bundle.py --redacted [--out DIR]

Read-only against Langflow. Steps:
1. `import_flows.py --export --flows-dir DIR/flows`: GET each of the seven TaskSprint flows, drop volatile keys
   (ids, user/folder ids, timestamps, endpoint names), blank every non-bound password-field value and refuse to
   write a file that still matches a credential pattern.
2. A second, independent secret scan of every written file (the same patterns plus long bearer-like strings).
3. A bundle manifest (DIR/bundle_manifest.json): per flow the file sha256, the import_flows content digest,
   bound variable NAMES (load_from_db; values are never exported), MCP server names, Run Flow targets and the
   A2A peer.
4. Helper-ID remapping rehearsal (offline, on copies): every Run Flow `flow_id_selected` and the A2A Audit
   `peer_flow_id` / `card_url` are overwritten with foreign IDs, as an export from another instance would carry,
   then `import_flows.remap_run_flows` / `remap_a2a_peer` are applied against this instance's flow list. They
   must restore exactly the live helper IDs. Variable bindings must be NAMES that exist as Langflow globals.
5. Comparison with the committed `flows/*.json` (reported, never overwritten).
6. (Phase 12, scripts/bundle_package.py) component sources, prompts, skills, corpus, contracts, lockfile,
   Dockerfiles, redacted reports, observed UI labels, runbook, versions.json (incl. migrations), RESET.md and a
   private configuration checklist (names only); then a credential-pattern scan and an exact-value scan of every
   bundle file against .local/railway/*.env (values never printed). No fonts, fixtures or grader source.

Then run `import_flows.py --dry-run --flows-dir DIR/flows`: every flow must report `OK keep` (identical wiring,
bindings and settings), i.e. a re-import would change nothing. A real re-import onto this instance is NOT done:
`--apply --force` would rewrite the flows, and the qualified agent-system manifest binds the live flows.
The bootstrap key is read from .local/railway/langflow_bootstrap.env and never printed. Exit 0 = all PASS.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_flows as imf  # noqa: E402
import bundle_package  # noqa: E402
from lf_common import DEFAULT_BOOTSTRAP_FILE, DEFAULT_LANGFLOW_URL, REPO_ROOT, SetupError, check, langflow_client  # noqa: E402

EXTRA_PATTERNS = [re.compile(p) for p in (r"(?i)x-api-key\"?\s*[:=]\s*\"[A-Za-z0-9_\-]{20,}",
                                          r"(?i)\"api_key\"\s*:\s*\{[^{}]*\"value\"\s*:\s*\"[^\"]{12,}\"")]
FOREIGN = "00000000-0000-4000-8000-000000000000"


BOUND_NAME = re.compile(r'"load_from_db"\s*:\s*true[\s\S]*"value"\s*:\s*"[A-Z][A-Z0-9_]{2,63}"$')


def scan(text: str) -> list[str]:
    """Credential-like strings. A field bound to a global by NAME (load_from_db true, upper-case variable name such
    as TS_A2A_API_KEY) carries no value and is not a hit."""
    hits = imf.secret_hits(text)
    for p in EXTRA_PATTERNS:
        hits += [m.group(0)[:12] + "…" for m in p.finditer(text) if not BOUND_NAME.search(m.group(0))]
    return hits


def helpers(data: dict) -> dict:
    out: dict = {"run_flow": {}, "a2a_peer": None}
    for n in data["nodes"]:
        t, tpl = n["data"]["type"], n["data"]["node"].get("template", {})
        if t == "RunFlow":
            out["run_flow"][tpl["flow_name_selected"]["value"]] = tpl["flow_id_selected"]["value"]
        if t == "TaskSprintA2AAudit":
            out["a2a_peer"] = {"peer_flow_id": tpl["peer_flow_id"]["value"], "card_url": tpl["card_url"]["value"]}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--redacted", action="store_true", required=True,
                    help="required: export with credential values removed (the only supported mode)")
    ap.add_argument("--out", type=Path, default=None, help="bundle directory (default .local/bundle/<UTC stamp>)")
    ap.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    ap.add_argument("--bootstrap-file", type=Path, default=DEFAULT_BOOTSTRAP_FILE)
    a = ap.parse_args(argv)
    out = a.out or REPO_ROOT / ".local" / "bundle" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out.resolve()
    flows_dir = out / "flows"
    flows_dir.mkdir(parents=True, exist_ok=True)
    fails = 0

    def result(ok: bool, what: str) -> None:
        nonlocal fails
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'} {what}")

    rc = imf.main(["--export", "--flows-dir", str(flows_dir), "--langflow-url", a.langflow_url,
                   "--bootstrap-file", str(a.bootstrap_file)])
    result(rc == 0, f"sanitized export of {len(imf.FLOWS)} flows -> {flows_dir.relative_to(REPO_ROOT)}")
    if rc != 0:
        return 1
    try:
        with langflow_client(a.langflow_url, a.bootstrap_file) as c:
            proj = next(p for p in check(c.get("/api/v1/projects/"), "list projects") if p["name"] == imf.PROJECT)
            existing = {f["name"]: f for f in check(c.get("/api/v1/flows/", params={
                "folder_id": proj["id"], "get_all": "true", "header_flows": "true"}), "list flows")
                if f.get("folder_id") == proj["id"]}
            known_vars = {v["name"] for v in check(c.get("/api/v1/variables/"), "list variables")}
            version = (check(c.get("/api/v1/version"), "version") or {}).get("version")
    except (SetupError, StopIteration) as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1

    manifest = {"bundle_format": "tasksprint-flow-bundle/1", "langflow_version": version,
                "exported_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source_instance": a.langflow_url, "flows": {}}
    for fname, name, *_ in imf.FLOWS:
        path = flows_dir / fname
        text = path.read_text(encoding="utf-8")
        hits = scan(text)
        result(not hits, f"{fname}: independent secret scan ({len(hits)} hits)")
        doc = json.loads(text)
        data = doc["data"]
        b = imf.bindings(data)
        var_names = sorted({v.split("=", 1)[1] for v in b["variables"]})
        result(set(var_names) <= known_vars, f"{fname}: bound variable NAMES exist as globals {var_names}")
        h = helpers(data)
        live_id = existing[name]["id"]
        repo = REPO_ROOT / "flows" / fname
        same_as_repo = repo.is_file() and imf.digest(json.loads(repo.read_text(encoding="utf-8"))["data"]) == \
            imf.digest(data)
        manifest["flows"][name] = {"file": f"flows/{fname}", "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                   "digest": imf.digest(data), "variables": var_names, "mcp_servers": b["mcp_servers"],
                                   "helpers": h, "live_flow_id": live_id, "a2a_enabled": doc.get("a2a_enabled"),
                                   "mcp_enabled": doc.get("mcp_enabled"), "flow_type": doc.get("flow_type"),
                                   "matches_committed_flows_dir": same_as_repo}
        print(f"INFO {name}: digest {imf.digest(data)} committed flows/{fname} {'same' if same_as_repo else 'DIFFERS'}"
              f" a2a={doc.get('a2a_enabled')} mcp={doc.get('mcp_enabled')}")
        if h["run_flow"] or h["a2a_peer"]:
            moved = copy.deepcopy(data)
            for n in moved["nodes"]:
                tpl = n["data"]["node"].get("template", {})
                if n["data"]["type"] == "RunFlow":
                    tpl["flow_id_selected"]["value"] = FOREIGN
                if n["data"]["type"] == "TaskSprintA2AAudit":
                    tpl["peer_flow_id"]["value"] = FOREIGN
                    tpl["card_url"]["value"] = f"https://other-instance.invalid/api/v1/a2a/{FOREIGN}/.well-known/agent-card.json"
            imf.remap_run_flows(moved, existing)
            imf.remap_a2a_peer(moved, existing, a.langflow_url)
            r = helpers(moved)
            want_rf = {t: existing[t]["id"] for t in h["run_flow"]}
            result(r["run_flow"] == want_rf == h["run_flow"],
                   f"{fname}: Run Flow helper IDs remapped from a foreign export -> {r['run_flow']}")
            if h["a2a_peer"]:
                peer = existing[imf.A2A_PEER_FLOW]["id"]
                result(r["a2a_peer"]["peer_flow_id"] == peer == h["a2a_peer"]["peer_flow_id"] and
                       r["a2a_peer"]["card_url"] == h["a2a_peer"]["card_url"],
                       f"{fname}: A2A peer remapped -> {peer} (card URL on this instance)")
    for name, rec in manifest["flows"].items():
        if name == "TS-90 Instructor Console":
            result(rec["a2a_enabled"] is False and rec["mcp_enabled"] is False,
                   "TS-90 exported with a2a_enabled=false, mcp_enabled=false")
    (out / "bundle_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"INFO manifest {out.relative_to(REPO_ROOT)}/bundle_manifest.json sha256 "
          f"{hashlib.sha256((out / 'bundle_manifest.json').read_bytes()).hexdigest()[:16]}")
    gate = None
    try:  # the qualified-manifest gate (evaluator credential, read-only); optional for an offline package
        import httpx
        from lf_common import DEFAULT_LAB_URL, DEFAULT_TOKENS_FILE, read_env
        tok = read_env(DEFAULT_TOKENS_FILE).get("TS_EVALUATOR_TOKEN", "")
        r = httpx.get(DEFAULT_LAB_URL + "/v1/agent-system-manifests/qualified", timeout=30,
                      headers={"Authorization": f"Bearer {tok}", "X-TaskSprint-Workspace": "demo-001"})
        if r.status_code == 200:
            gate = {k: r.json().get(k) for k in ("status", "agent_manifest_id", "manifest_sha256", "report_id",
                                                  "qualified_at", "current_lab_side_sha256", "last_verified_at")}
    except Exception as e:  # noqa: BLE001
        print(f"NOTE qualified-manifest gate not read ({type(e).__name__}); versions.json records null")
    fails += bundle_package.build(out, version, known_vars, gate, scan)
    print(f"NEXT uv run --frozen --no-dev python scripts/import_flows.py --dry-run --flows-dir {flows_dir.relative_to(REPO_ROOT)}")
    print(f"SUMMARY export_bundle: {'PASS' if not fails else 'FAIL'} ({fails} failed)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
