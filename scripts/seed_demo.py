#!/usr/bin/env python3
"""Seed a designated demo workspace with starter v0 and two synthetic tasks (A13).

Calls the lab's in-process application with the instructor identity loaded from
.local/role_tokens.env. Never prints token values.

  uv run python scripts/seed_demo.py --workspace demo-001 --dry-run
  uv run python scripts/seed_demo.py --workspace demo-001 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True, help="designated workspace id, e.g. demo-001")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="preview counts only (no mutation)")
    mode.add_argument("--apply", action="store_true", help="seed the workspace if it does not exist")
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".local" / "lab.env"))
    parser.add_argument("--tokens-file", default=str(REPO_ROOT / ".local" / "role_tokens.env"))
    args = parser.parse_args(argv)

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from fastapi.testclient import TestClient

    from services.lab.config import ConfigError, load_settings, parse_env_file
    from services.lab.main import create_app

    try:
        settings = load_settings({**os.environ, "TASKSPRINT_ENV_FILE": args.env_file})
        token = parse_env_file(Path(args.tokens_file)).get("TS_INSTRUCTOR_TOKEN", "")
    except (ConfigError, OSError) as exc:
        print(f"ERROR: configuration unavailable ({type(exc).__name__}). Run scripts/local_init.py first.", file=sys.stderr)
        return 2
    if not token:
        print("ERROR: TS_INSTRUCTOR_TOKEN missing from the tokens file.", file=sys.stderr)
        return 2
    client = TestClient(create_app(settings))
    action = "seed" if args.apply else "reset_preview"
    resp = client.post("/v1/instructor/actions", json={"action": action, "workspace_id": args.workspace},
                       headers={"Authorization": f"Bearer {token}"})
    print(f"HTTP {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))
    if args.apply and resp.status_code == 409 and resp.json()["error"]["code"] == "ALREADY_SEEDED":
        return 0
    return 0 if resp.status_code < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
