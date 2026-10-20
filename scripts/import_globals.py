#!/usr/bin/env python3
"""Create the TaskSprint Langflow global variables (Build Guide 06.1, Architecture A4).

  uv run --frozen --no-dev python scripts/import_globals.py --dry-run
  uv run --frozen --no-dev python scripts/import_globals.py --apply [--force]

Creates, for the Langflow user who owns the bootstrap API key:
  Generic     TASKSPRINT_API_BASE = --lab-url (not secret)
  Credential  TS_COORD_TOKEN, TS_PO_TOKEN, TS_DEV_TOKEN, TS_QA_TOKEN, TS_OPS_TOKEN, TS_APP_TOKEN
              (values read from --tokens-file)
  Phase 09 (--phase09): also Credential TS_APPROVER_TOKEN, TS_INSTRUCTOR_TOKEN, TS_EVALUATOR_TOKEN for the
              human-only TS-90 Instructor Console. Only TS-90's trusted components bind them; no Agent,
              MCP server, A2A peer or tool may. Without --phase09 their presence is only reported.

Idempotent: lists existing variables first (GET /api/v1/variables/), creates only
missing names, and never overwrites an existing variable unless --force is given
(then PATCH /api/v1/variables/{id}). Never prints a value. Verifies by a second GET
(name, type, has_value). Exit 0 success, 1 API failure, 2 configuration error.
The /api/v1/variables/ routes are not in Langflow's OpenAPI schema (include_in_schema
False); the payload {name, value, type, default_fields} is the one the 1.12.5 UI and
server model (langflow-base 1.12.5 VariableCreate) use.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lf_common import (DEFAULT_BOOTSTRAP_FILE, DEFAULT_LAB_URL, DEFAULT_LANGFLOW_URL,  # noqa: E402
                       DEFAULT_TOKENS_FILE, SetupError, check, langflow_client, read_env)

CREDENTIALS = ("TS_COORD_TOKEN", "TS_PO_TOKEN", "TS_DEV_TOKEN", "TS_QA_TOKEN", "TS_OPS_TOKEN", "TS_APP_TOKEN")
HUMAN_ONLY = ("TS_APPROVER_TOKEN", "TS_INSTRUCTOR_TOKEN", "TS_EVALUATOR_TOKEN")
GENERIC = "TASKSPRINT_API_BASE"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="show what would be created; change nothing")
    mode.add_argument("--apply", action="store_true", help="create missing variables")
    p.add_argument("--force", action="store_true", help="with --apply: overwrite existing TaskSprint variables")
    p.add_argument("--phase09", action="store_true",
                   help="also create the human-only TS-90 credentials (approver, instructor, evaluator)")
    p.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    p.add_argument("--lab-url", default=DEFAULT_LAB_URL)
    p.add_argument("--tokens-file", type=Path, default=DEFAULT_TOKENS_FILE)
    p.add_argument("--bootstrap-file", type=Path, default=DEFAULT_BOOTSTRAP_FILE)
    a = p.parse_args(argv)

    try:
        lab = urlparse(a.lab_url)
        if lab.scheme != "https" or not lab.hostname or lab.path not in ("", "/") or lab.query:
            raise SetupError("--lab-url must be an https origin without a path")
        tokens = read_env(a.tokens_file)
        creds = CREDENTIALS + (HUMAN_ONLY if a.phase09 else ())
        missing = [n for n in creds if len(tokens.get(n, "")) < 32]
        if missing:
            raise SetupError(f"tokens file lacks usable values for: {', '.join(missing)}")
        wanted: dict[str, tuple[str, str]] = {GENERIC: ("Generic", a.lab_url.rstrip("/"))}
        wanted.update({n: ("Credential", tokens[n]) for n in creds})
        with langflow_client(a.langflow_url, a.bootstrap_file) as c:
            existing = {v["name"]: v for v in check(c.get("/api/v1/variables/"), "list variables")}
            if not a.phase09:
                for name in HUMAN_ONLY:
                    if name in existing:
                        print(f"NOTE {name} exists (human-only TS-90 credential; created with --phase09)")
            for name, (vtype, value) in wanted.items():
                cur = existing.get(name)
                if cur is None:
                    action = "create"
                elif a.force:
                    action = "overwrite"
                else:
                    action = "keep"
                    if cur.get("type") != vtype:
                        print(f"WARN {name} exists with type {cur.get('type')} (expected {vtype}); use --force to fix")
                print(f"{'PLAN' if a.dry_run else 'DO'} {action:9} {name} ({vtype})")
                if a.dry_run or action == "keep":
                    continue
                body = {"name": name, "value": value, "type": vtype, "default_fields": []}
                if action == "create":
                    check(c.post("/api/v1/variables/", json=body), f"create {name}", ok=(201, 200))
                else:
                    check(c.patch(f"/api/v1/variables/{cur['id']}", json={"id": cur["id"], **body}),
                          f"update {name}")
            if a.dry_run:
                return 0
            after = {v["name"]: v for v in check(c.get("/api/v1/variables/"), "verify variables")}
            bad = 0
            for name, (vtype, _value) in wanted.items():
                v = after.get(name)
                ok = v is not None and v.get("type") == vtype and v.get("has_value") is True
                bad += not ok
                print(f"{'PASS' if ok else 'FAIL'} verify {name}: type={v and v.get('type')} "
                      f"has_value={v and v.get('has_value')}")
            unrelated = sorted(set(after) - set(wanted))
            print(f"NOTE unrelated variables left untouched: {', '.join(unrelated) or 'none'}")
            return 1 if bad else 0
    except SetupError as err:
        print(f"ERROR {err}", file=sys.stderr)
        return 2 if "file" in str(err) or "--lab-url" in str(err) else 1


if __name__ == "__main__":
    sys.exit(main())
