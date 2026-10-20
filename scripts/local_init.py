#!/usr/bin/env python3
"""Create NEW local TaskSprint credentials in ignored, owner-only files.

Writes two files (default directory: .local/ in the repository root):

  role_tokens.env  plaintext role tokens, for the owner to enter privately into
                   Langflow Credential variables / human-only clients.
  lab.env          lab-service configuration: token SHA-256 hashes, the runner
                   transport token, and local paths. Pass it to the lab with
                   TASKSPRINT_ENV_FILE=.local/lab.env.

Guarantees: values are never printed (only file names and variable names);
files are created with mode 0600 inside a 0700 directory; existing files are
never overwritten (exit status 3). It touches nothing outside the target
directory and never reads Langflow, Railway or existing secrets.

TS_A2A_API_KEY is deliberately NOT generated: it is a Langflow API key issued
by the Langflow instance itself (Phase 08), not a TaskSprint role token.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (token variable, hash variable, backend identity) — Architecture A4.
ROLE_TOKENS = (
    ("TS_COORD_TOKEN", "TS_COORD_TOKEN_HASH", "coordinator"),
    ("TS_PO_TOKEN", "TS_PO_TOKEN_HASH", "product_owner"),
    ("TS_DEV_TOKEN", "TS_DEV_TOKEN_HASH", "developer"),
    ("TS_QA_TOKEN", "TS_QA_TOKEN_HASH", "qa"),
    ("TS_OPS_TOKEN", "TS_OPS_TOKEN_HASH", "operations"),
    ("TS_APP_TOKEN", "TS_APP_TOKEN_HASH", "application"),
    ("TS_APPROVER_TOKEN", "TS_APPROVER_TOKEN_HASH", "human_approver"),
    ("TS_INSTRUCTOR_TOKEN", "TS_INSTRUCTOR_TOKEN_HASH", "instructor"),
    ("TS_EVALUATOR_TOKEN", "TS_EVALUATOR_TOKEN_HASH", "evaluator"),
)
RUNNER_TOKEN_VAR = "TS_RUNNER_TOKEN"
TOKEN_FILE = "role_tokens.env"
LAB_FILE = "lab.env"


def new_token(role: str) -> str:
    return f"ts_{role.replace('_', '')}_{secrets.token_urlsafe(32)}"


def write_private(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=str(REPO_ROOT / ".local"),
                        help="target directory for the private files (default: <repo>/.local)")
    parser.add_argument("--db-path", default=None,
                        help="TASKSPRINT_DB_PATH to record in lab.env (default: <dir>/tasksprint.sqlite3)")
    parser.add_argument("--workspaces", default="demo-001",
                        help="comma-separated designated demo workspaces (default: demo-001)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be created; write nothing")
    args = parser.parse_args(argv)

    target = Path(args.dir).resolve()
    token_path, lab_path = target / TOKEN_FILE, target / LAB_FILE
    existing = [p.name for p in (token_path, lab_path) if p.exists()]
    if existing:
        print(f"REFUSED: {', '.join(existing)} already exist in {target}; nothing was changed.", file=sys.stderr)
        print("Existing credentials are never overwritten. Move them aside deliberately if you intend to rotate.",
              file=sys.stderr)
        return 3
    db_path = args.db_path or str(target / "tasksprint.sqlite3")

    if args.dry_run:
        print(f"DRY RUN: would create {token_path} and {lab_path} (mode 0600).")
        print("Variables:", ", ".join(v for v, _, _ in ROLE_TOKENS), "|", RUNNER_TOKEN_VAR,
              "|", ", ".join(h for _, h, _ in ROLE_TOKENS))
        return 0

    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(target, 0o700)

    tokens = {var: new_token(role) for var, _, role in ROLE_TOKENS}
    if len(set(tokens.values())) != len(tokens):
        print("ERROR: token collision; aborting without writing.", file=sys.stderr)
        return 1
    runner_token = secrets.token_urlsafe(32)

    token_lines = ["# TaskSprint role tokens. PRIVATE. Never commit, paste into chat, or show on screen.",
                   "# Enter each value privately as a Langflow Credential variable of the same name."]
    token_lines += [f"{var}={tokens[var]}" for var, _, _ in ROLE_TOKENS]
    lab_lines = ["# TaskSprint lab configuration (hashes only for role tokens). PRIVATE; ignored by git.",
                 f"TASKSPRINT_DB_PATH={db_path}",
                 "TASKSPRINT_DEMO_ENABLED=true",
                 f"TASKSPRINT_ALLOWED_WORKSPACES={args.workspaces}",
                 f"{RUNNER_TOKEN_VAR}={runner_token}"]
    lab_lines += [f"{hvar}={hashlib.sha256(tokens[var].encode()).hexdigest()}" for var, hvar, _ in ROLE_TOKENS]

    write_private(token_path, "\n".join(token_lines) + "\n")
    try:
        write_private(lab_path, "\n".join(lab_lines) + "\n")
    except FileExistsError:
        print(f"ERROR: {lab_path.name} appeared concurrently; {token_path.name} was written, lab.env was not.",
              file=sys.stderr)
        return 1

    for p in (token_path, lab_path):
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & 0o077:
            print(f"WARNING: {p.name} has mode {oct(mode)}; expected 0600 (filesystem may not honour chmod).",
                  file=sys.stderr)
    print(f"Created {token_path} (mode 0600): " + ", ".join(v for v, _, _ in ROLE_TOKENS))
    print(f"Created {lab_path} (mode 0600): TASKSPRINT_DB_PATH, TASKSPRINT_DEMO_ENABLED, "
          f"TASKSPRINT_ALLOWED_WORKSPACES, {RUNNER_TOKEN_VAR}, " + ", ".join(h for _, h, _ in ROLE_TOKENS))
    print("No secret values were printed. Not generated here: TS_A2A_API_KEY (issued by Langflow in Phase 08).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
