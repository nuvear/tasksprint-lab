#!/usr/bin/env python3
"""Create the runtime Langflow API key for the fixed A2A peer and store it as TS_A2A_API_KEY (Build Guide 08.4).

  uv run --frozen --no-dev python scripts/create_a2a_key.py --dry-run
  uv run --frozen --no-dev python scripts/create_a2a_key.py --apply [--expires-days 90]

What it does (owner-approved path; equivalent to Settings -> Langflow API Keys -> Add New, without ever
showing the key on screen):
  1. POST /api/v1/api_key/ {"name": "tasksprint-a2a-runtime", "expires_at": ...} with the bootstrap key
     (the same route the Settings page uses; include_in_schema=False in 1.12.5). The new key belongs to
     the bootstrap key's owner, who also owns the TaskSprint flows, so it is a valid "owner key" for an
     apikey-folder A2A agent.
  2. Stores the value as the Credential global TS_A2A_API_KEY (POST /api/v1/variables/).
  3. Writes it to the git-ignored .local/railway/a2a_runtime.env (mode 600) for the local live checks.
  4. Verifies: the variable exists as Credential with has_value=true, and the new key authenticates
     (GET /api/v1/a2a/agents with x-api-key -> 200).
The value is never printed or logged. RISK: a Langflow API key inherits ALL of its creator's (admin)
privileges; the name does not scope it. It is used only in the fixed A2A connection configuration of
the Sprint Room's TaskSprint A2A Audit node (never in a prompt or a tool argument) and must be revoked
at handover together with the bootstrap key. Idempotent: an existing key name + variable is kept.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lf_common import (DEFAULT_BOOTSTRAP_FILE, DEFAULT_LANGFLOW_URL, REPO_ROOT, SetupError, TIMEOUT,  # noqa: E402
                       check, langflow_client)

KEY_NAME = "tasksprint-a2a-runtime"
VAR = "TS_A2A_API_KEY"
LOCAL_FILE = REPO_ROOT / ".local/railway/a2a_runtime.env"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--expires-days", type=int, default=90)
    p.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    p.add_argument("--bootstrap-file", type=Path, default=DEFAULT_BOOTSTRAP_FILE)
    a = p.parse_args(argv)
    try:
        if not 1 <= a.expires_days <= 365:
            raise SetupError("--expires-days must be 1..365")
        with langflow_client(a.langflow_url, a.bootstrap_file) as c:
            keys = check(c.get("/api/v1/api_key/"), "list API keys")["api_keys"]
            existing = [k for k in keys if k.get("name") == KEY_NAME and k.get("is_active")]
            variables = {v["name"]: v for v in check(c.get("/api/v1/variables/"), "list variables")}
            if existing or VAR in variables:
                state = f"key={'present id=' + existing[0]['id'] if existing else 'absent'} variable=" \
                        f"{'present' if VAR in variables else 'absent'}"
                if existing and VAR in variables and LOCAL_FILE.is_file():
                    print(f"OK keep {KEY_NAME} / {VAR} ({state})")
                    return 0
                raise SetupError(f"partial state ({state}); not changing anything. Ask the owner to delete the "
                                 f"stale key/variable in Settings, then rerun")
            expires = (datetime.now(timezone.utc) + timedelta(days=a.expires_days)).replace(microsecond=0)
            print(f"{'PLAN' if a.dry_run else 'DO'} create API key '{KEY_NAME}' (expires {expires.isoformat()}), "
                  f"Credential variable {VAR}, local file {LOCAL_FILE.relative_to(REPO_ROOT)}")
            if a.dry_run:
                return 0
            created = check(c.post("/api/v1/api_key/", json={"name": KEY_NAME, "expires_at": expires.isoformat()}),
                            "create API key")
            value = created.get("api_key") or ""
            if not value.startswith("sk-") or "*" in value:
                raise SetupError("the API key response did not contain an unmasked key")
            print(f"PASS created API key id={created['id']} (value not shown)")
            check(c.post("/api/v1/variables/", json={"name": VAR, "value": value, "type": "Credential",
                                                     "default_fields": []}), f"create {VAR}", ok=(200, 201))
            LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(LOCAL_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(f"# Langflow API key '{KEY_NAME}' for the fixed TS-20 A2A peer. Admin-privileged. Revoke at handover.\n")
                fh.write(f"{VAR}={value}\n")
            after = {v["name"]: v for v in check(c.get("/api/v1/variables/"), "verify variables")}
            v = after.get(VAR) or {}
            ok_var = v.get("type") == "Credential" and v.get("has_value") is True
            print(f"{'PASS' if ok_var else 'FAIL'} verify {VAR}: type={v.get('type')} has_value={v.get('has_value')}")
        r = httpx.get(a.langflow_url.rstrip("/") + "/api/v1/a2a/agents", headers={"x-api-key": value}, timeout=TIMEOUT)
        print(f"{'PASS' if r.status_code == 200 else 'FAIL'} new key authenticates as the owner: "
              f"GET /api/v1/a2a/agents -> {r.status_code}")
        return 0 if ok_var and r.status_code == 200 else 1
    except SetupError as err:
        print(f"ERROR {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
