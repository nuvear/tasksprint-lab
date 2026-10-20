"""Shared helpers for the Langflow setup scripts (Phase 06).

Reads private values from git-ignored files and never prints them. The Langflow
bootstrap API key is an admin-privileged key (it inherits its creator's rights);
it is used only by these local setup scripts and is never placed in a flow,
a prompt, a model input or a log line.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LANGFLOW_URL = "https://langflow-railway-production-f493.up.railway.app"
DEFAULT_LAB_URL = "https://tasksprint-lab-production.up.railway.app"
DEFAULT_TOKENS_FILE = REPO_ROOT / ".local/railway/role_tokens.env"
DEFAULT_BOOTSTRAP_FILE = REPO_ROOT / ".local/railway/langflow_bootstrap.env"
TIMEOUT = httpx.Timeout(60.0, connect=15.0)


class SetupError(RuntimeError):
    """Configuration or API failure; the message never contains a secret value."""


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SetupError(f"private file not found: {path}")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def langflow_client(base_url: str, bootstrap_file: Path) -> httpx.Client:
    key = read_env(bootstrap_file).get("LANGFLOW_BOOTSTRAP_API_KEY", "")
    if not key:
        raise SetupError(f"LANGFLOW_BOOTSTRAP_API_KEY missing in {bootstrap_file}")
    return httpx.Client(base_url=base_url.rstrip("/"), headers={"x-api-key": key}, timeout=TIMEOUT)


def check(resp: httpx.Response, what: str, ok: tuple[int, ...] = (200, 201)) -> Any:
    if resp.status_code not in ok:
        detail = resp.text[:300]
        raise SetupError(f"{what}: HTTP {resp.status_code}: {redact_text(detail)}")
    return resp.json() if resp.content else None


_LONG = re.compile(r"[A-Za-z0-9_\-+/=]{32,}")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def redact_text(text: str) -> str:
    """Mask any long opaque run (possible secret) in error text."""
    return _LONG.sub(lambda m: m.group(0) if _UUID.match(m.group(0)) else "<redacted>", text)
