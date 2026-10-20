"""Lab configuration (Architecture A4).

Configuration comes from the process environment, optionally preceded by a
private env file named by ``TASKSPRINT_ENV_FILE`` (written by
``scripts/local_init.py``). Values are never logged or returned by any route.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Backend identities from Architecture A4 and the variable holding each token hash.
ROLE_HASH_VARS: dict[str, str] = {
    "coordinator": "TS_COORD_TOKEN_HASH",
    "product_owner": "TS_PO_TOKEN_HASH",
    "developer": "TS_DEV_TOKEN_HASH",
    "qa": "TS_QA_TOKEN_HASH",
    "operations": "TS_OPS_TOKEN_HASH",
    "application": "TS_APP_TOKEN_HASH",
    "human_approver": "TS_APPROVER_TOKEN_HASH",
    "instructor": "TS_INSTRUCTOR_TOKEN_HASH",
    "evaluator": "TS_EVALUATOR_TOKEN_HASH",
}
ROLES = frozenset(ROLE_HASH_VARS)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_WORKSPACE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_JOURNAL_MODES = {"TRUNCATE", "PERSIST", "DELETE", "WAL"}

# Fixed server-side harness budgets (Architecture A9). Clients cannot change them.
RUN_MAX_ACTIONS = 8
RUN_TREE_MAX_ACTIONS = 24
RUN_MAX_DEPTH = 2
RUN_DEADLINE_SPECIALIST_S = 90
RUN_DEADLINE_PARENT_S = 180


class ConfigError(ValueError):
    """Raised for invalid configuration. Messages never contain secret values."""


@dataclass(frozen=True)
class Settings:
    db_path: str
    demo_enabled: bool = True
    token_hashes: dict[str, str] = field(default_factory=dict)
    allowed_workspaces: tuple[str, ...] = ("demo-001",)
    fixtures_dir: str = str(REPO_ROOT / "instructor" / "fixtures")
    max_body_bytes: int = 64 * 1024
    journal_mode: str = "TRUNCATE"
    # Phase 03: the separate bounded runner. The token is transport-only (lab -> runner).
    runner_url: str = ""
    runner_token: str = field(default="", repr=False)
    runner_timeout_s: float = 5.0


def parse_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser (no interpolation, no shell semantics)."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"malformed line in env file {path.name}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_settings(env: dict[str, str] | None = None) -> Settings:
    source: dict[str, str] = {}
    process_env = dict(os.environ if env is None else env)
    env_file = process_env.get("TASKSPRINT_ENV_FILE", "").strip()
    if env_file:
        path = Path(env_file)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.is_file():
            raise ConfigError("TASKSPRINT_ENV_FILE does not name a readable file")
        source.update(parse_env_file(path))
    source.update({k: v for k, v in process_env.items() if v != ""})

    db_path = source.get("TASKSPRINT_DB_PATH", "").strip()
    if not db_path:
        raise ConfigError("TASKSPRINT_DB_PATH is required")
    if db_path != ":memory:" and not Path(db_path).is_absolute():
        db_path = str(REPO_ROOT / db_path)  # relative paths are repository-relative, not CWD-relative

    hashes: dict[str, str] = {}
    for role, var in ROLE_HASH_VARS.items():
        value = source.get(var, "").strip().lower()
        if not value:
            continue  # role disabled: deny-by-default
        if not _HEX64.match(value):
            raise ConfigError(f"{var} must be a 64-character lowercase SHA-256 hex digest")
        hashes[role] = value
    if len(set(hashes.values())) != len(hashes):
        raise ConfigError("two roles share one token hash; role tokens must be independent")

    workspaces = tuple(
        w.strip() for w in source.get("TASKSPRINT_ALLOWED_WORKSPACES", "demo-001").split(",") if w.strip()
    )
    for w in workspaces:
        if not _WORKSPACE_ID.match(w):
            raise ConfigError("TASKSPRINT_ALLOWED_WORKSPACES contains an invalid workspace id")

    journal = source.get("TASKSPRINT_SQLITE_JOURNAL_MODE", "TRUNCATE").strip().upper()
    if journal not in _JOURNAL_MODES:
        raise ConfigError("TASKSPRINT_SQLITE_JOURNAL_MODE must be TRUNCATE, PERSIST, DELETE or WAL")

    try:
        max_body = int(source.get("TASKSPRINT_MAX_BODY_BYTES", str(64 * 1024)))
    except ValueError as exc:
        raise ConfigError("TASKSPRINT_MAX_BODY_BYTES must be an integer") from exc
    if not 1024 <= max_body <= 1024 * 1024:
        raise ConfigError("TASKSPRINT_MAX_BODY_BYTES must be between 1 KiB and 1 MiB")

    fixtures = source.get("TASKSPRINT_FIXTURES_DIR", str(REPO_ROOT / "instructor" / "fixtures"))

    runner_url = source.get("TASKSPRINT_RUNNER_URL", "").strip().rstrip("/")
    if runner_url and not re.match(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?$", runner_url):
        raise ConfigError("TASKSPRINT_RUNNER_URL must be http(s)://host[:port] with no path")
    runner_token = source.get("TS_RUNNER_TOKEN", "").strip()
    if runner_url and len(runner_token) < 32:
        raise ConfigError("TS_RUNNER_TOKEN (at least 32 characters) is required when TASKSPRINT_RUNNER_URL is set")
    return Settings(
        db_path=db_path,
        demo_enabled=source.get("TASKSPRINT_DEMO_ENABLED", "false").strip().lower() == "true",
        token_hashes=hashes,
        allowed_workspaces=workspaces,
        fixtures_dir=fixtures,
        max_body_bytes=max_body,
        journal_mode=journal,
        runner_url=runner_url,
        runner_token=runner_token,
    )


def valid_workspace_id(value: str) -> bool:
    return bool(_WORKSPACE_ID.match(value or ""))
