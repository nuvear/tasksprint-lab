#!/usr/bin/env python3
"""Verify the live TaskSprint flows against the committed exports (Architecture A13, Build Guide 12.2).

  uv run --frozen --no-dev python scripts/verify_flows.py [--flows-dir flows] [--langflow-url URL]

Read-only against Langflow. It never imports, saves or publishes a flow. For each of the seven TaskSprint flows:
1. Exactly one live flow with that name exists in the TaskSprint project (no duplicate).
2. Equivalence: the import_flows content digest of the live flow (node types, wiring, bound variable NAMES, MCP
   server names, prompts, component code, key settings) equals the digest of the committed `flows/*.json`.
3. Variable bindings: every load_from_db field names a global that exists (values are never read).
4. No literal credentials: no password field carries a value unless it is bound to a global by NAME, and the
   sanitized export passes the credential-pattern scan (export_bundle.scan).
5. Publication: TS-90 Instructor Console has MCP and A2A off; TS-20 Production Manager has A2A on and its public
   Agent Card is served (protocolVersion reported); TS-10's A2A peer and card URL and its Run Flow helper IDs point
   at the live TS-20 / TS-01 / TS-02 / TS-03 on this instance.
The bootstrap key is read from .local/railway/langflow_bootstrap.env and never printed. Exit 0 = all PASS,
1 = a check failed, 2 = configuration or network error.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_flows as imf  # noqa: E402
from export_bundle import helpers, scan  # noqa: E402
from lf_common import DEFAULT_BOOTSTRAP_FILE, DEFAULT_LANGFLOW_URL, REPO_ROOT, SetupError, check, langflow_client  # noqa: E402

TS90, TS20, TS10 = "TS-90 Instructor Console", imf.A2A_PEER_FLOW, "TS-10 Sprint Room"


def literal_password_fields(data: dict) -> list[str]:
    """Names (never values) of password fields that hold a literal value instead of a bound global NAME."""
    out = []
    for n in data["nodes"]:
        for fname, f in n["data"]["node"].get("template", {}).items():
            if isinstance(f, dict) and f.get("password") and f.get("value") and not f.get("load_from_db"):
                out.append(f"{n['data']['type']}.{fname}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--flows-dir", type=Path, default=REPO_ROOT / "flows", help="committed exports to compare with")
    ap.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    ap.add_argument("--bootstrap-file", type=Path, default=DEFAULT_BOOTSTRAP_FILE)
    a = ap.parse_args(argv)
    fails = 0

    def result(ok: bool, what: str) -> None:
        nonlocal fails
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'} {what}")

    try:
        with langflow_client(a.langflow_url, a.bootstrap_file) as c:
            version = (check(c.get("/api/v1/version"), "version") or {}).get("version")
            proj = next(p for p in check(c.get("/api/v1/projects/"), "list projects") if p["name"] == imf.PROJECT)
            listed = [f for f in check(c.get("/api/v1/flows/", params={"folder_id": proj["id"], "get_all": "true",
                                                                       "header_flows": "true"}), "list flows")
                      if f.get("folder_id") == proj["id"]]
            known_vars = {v["name"] for v in check(c.get("/api/v1/variables/"), "list variables")}
            print(f"INFO Langflow {version}; project {imf.PROJECT}; {len(listed)} flows in the project; "
                  f"{len(known_vars)} globals (names only)")
            live: dict[str, dict] = {}
            for _, name, *_ in imf.FLOWS:
                same = [f for f in listed if f["name"] == name]
                result(len(same) == 1, f"{name}: exactly one live flow ({len(same)})")
                if same:
                    live[name] = check(c.get(f"/api/v1/flows/{same[0]['id']}"), f"get {name}")
            with tempfile.TemporaryDirectory(prefix="ts-verify-", dir=REPO_ROOT / ".local") as tmp:
                rc = imf.main(["--export", "--flows-dir", tmp, "--langflow-url", a.langflow_url,
                               "--bootstrap-file", str(a.bootstrap_file)])
                result(rc == 0, "sanitized export of the live flows (import_flows --export refuses credential patterns)")
                exported = {fn: (Path(tmp) / fn).read_text(encoding="utf-8") for fn, *_ in imf.FLOWS
                            if (Path(tmp) / fn).is_file()}
            ids = {n: d["id"] for n, d in live.items()}
            for fname, name, *_ in imf.FLOWS:
                doc = live.get(name)
                if doc is None:
                    continue
                data = doc["data"]
                committed = a.flows_dir / fname
                want = imf.digest(json.loads(committed.read_text(encoding="utf-8"))["data"]) if committed.is_file() else None
                got = imf.digest(data)
                result(got == want, f"{name}: live digest {got} == committed {fname} {want}")
                var_names = sorted({v.split("=", 1)[1] for v in imf.bindings(data)["variables"]})
                result(set(var_names) <= known_vars, f"{name}: bound variable NAMES exist as globals {var_names}")
                lit = literal_password_fields(data)
                result(not lit, f"{name}: no literal value in a password field {lit}")
                hits = scan(exported.get(fname, ""))
                result(fname in exported and not hits, f"{name}: export secret scan ({len(hits)} hits)")
                print(f"INFO {name}: id {doc['id']} a2a_enabled={doc.get('a2a_enabled')} mcp_enabled={doc.get('mcp_enabled')}")
            if TS90 in live:
                d = live[TS90]
                result(d.get("a2a_enabled") is False and d.get("mcp_enabled") is False,
                       f"{TS90}: MCP and A2A publication off (mcp={d.get('mcp_enabled')}, a2a={d.get('a2a_enabled')})")
            if TS20 in live:
                result(live[TS20].get("a2a_enabled") is True, f"{TS20}: A2A publication on")
                card_url = f"{a.langflow_url.rstrip('/')}/api/v1/a2a/{ids[TS20]}/.well-known/agent-card.json"
                r = httpx.get(card_url, timeout=20)
                card = r.json() if r.status_code == 200 else {}
                result(r.status_code == 200 and bool(card.get("protocolVersion")),
                       f"{TS20}: Agent Card served HTTP {r.status_code}, protocolVersion {card.get('protocolVersion')},"
                       f" name {card.get('name')!r}, advertised url scheme {str(card.get('url', ''))[:5]!r}")
            if TS10 in live:
                h = helpers(live[TS10]["data"])
                want_rf = {t: ids.get(t) for t in imf.ALLOWED_RUN_FLOW_TARGETS}
                result(h["run_flow"] == want_rf, f"{TS10}: Run Flow helper IDs point at the live specialists")
                peer = h["a2a_peer"] or {}
                result(peer.get("peer_flow_id") == ids.get(TS20) and peer.get("card_url") ==
                       f"{a.langflow_url.rstrip('/')}/api/v1/a2a/{ids.get(TS20)}/.well-known/agent-card.json",
                       f"{TS10}: A2A peer and card URL point at the live TS-20")
    except (SetupError, StopIteration, httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
        print(f"ERROR {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(f"SUMMARY verify_flows: {'PASS' if not fails else 'FAIL'} ({fails} failed)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
