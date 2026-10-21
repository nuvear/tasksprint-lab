"""Role authentication and authorization (Architecture A4).

* Random, independent role tokens; only SHA-256 hashes are configured here.
* Constant-time comparison against every configured hash (no early exit).
* Identity comes from the token alone. Request fields or headers named role,
  approved, is_admin or acting_as never grant authority (request models reject
  unknown fields; no code reads such headers).
* Deny by default: a business route without an entry in ``PERMISSIONS`` is
  refused even for an authenticated caller.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from .config import ROLES

TOKEN_MIN_LEN = 32
TOKEN_MAX_LEN = 256

# Phase 13: the static To-do web view (webview.py, static/). It holds no data and no secret; every data call it
# makes is an existing application-role route below and needs the application token.
WEBVIEW_ROUTES = frozenset({("GET", "/app"), ("GET", "/app/"), ("GET", "/app/app.js"), ("GET", "/app/app.css")})

# Routes reachable without credentials. Nothing else.
PUBLIC_ROUTES = frozenset({("GET", "/healthz")}) | WEBVIEW_ROUTES

AGENT_RUNTIME_ROLES = frozenset({"coordinator", "product_owner", "developer", "qa", "operations", "application"})

# (method, route template) -> roles allowed. Phase 02-04 subset of Architecture A8.
# The MCP catalog (mcp.py) derives each tool's roles from this table.
PERMISSIONS: dict[tuple[str, str], frozenset[str]] = {
    ("POST", "/v1/runs"): AGENT_RUNTIME_ROLES,
    ("GET", "/v1/state"): frozenset({"coordinator", "product_owner", "developer", "qa", "operations"}),
    ("POST", "/v1/stories"): frozenset({"coordinator"}),
    ("POST", "/v1/state/transitions"): frozenset({"coordinator"}),
    ("GET", "/v1/memory"): frozenset({"coordinator"}),
    ("POST", "/v1/memory"): frozenset({"coordinator"}),
    ("GET", "/v1/candidates/{candidate_id}"): frozenset({"developer", "qa", "operations"}),
    ("POST", "/v1/candidates"): frozenset({"developer"}),
    ("POST", "/v1/test-runs"): frozenset({"qa"}),
    ("GET", "/v1/test-runs/{test_run_id}"): frozenset({"qa", "operations", "coordinator"}),
    ("GET", "/v1/releases"): frozenset({"operations", "application"}),
    ("GET", "/v1/app-health"): frozenset({"operations", "application"}),
    ("GET", "/v1/events"): frozenset({"coordinator", "qa", "operations", "instructor", "evaluator"}),
    ("POST", "/v1/app/commands"): frozenset({"application"}),
    ("POST", "/v1/instructor/actions"): frozenset({"instructor"}),
    # Phase 04 (A7/A8): approved retrieval and the skill catalog.
    ("POST", "/v1/knowledge/search"): frozenset({"product_owner", "developer"}),
    ("POST", "/v1/instructor/knowledge/search"): frozenset({"instructor"}),
    ("GET", "/v1/skills"): frozenset({"developer", "operations"}),
    ("GET", "/v1/skills/{name}/{version}"): frozenset({"developer", "operations"}),
    # Phase 08 (A8, A10): readiness and canonical plans (Operations); audited A2A exchange records.
    ("GET", "/v1/readiness"): frozenset({"operations"}),
    ("POST", "/v1/release-plans"): frozenset({"operations"}),
    ("GET", "/v1/release-plans/{plan_id}"): frozenset({"operations", "human_approver"}),
    ("POST", "/v1/a2a-exchanges"): frozenset({"coordinator"}),
    ("GET", "/v1/a2a-exchanges/{exchange_id}"): frozenset({"coordinator", "instructor", "evaluator"}),
    # Phase 09 (A8, A11, A12): human-only decisions, approved execution, evaluator reports.
    ("POST", "/v1/approvals"): frozenset({"human_approver"}),
    ("POST", "/v1/release-executions"): frozenset({"operations"}),
    ("POST", "/v1/agent-evaluations"): frozenset({"evaluator"}),
    # Phase 10 (A5, A8, A12): reports/manifests are readable by operations and humans, writable only by the
    # evaluator; the evaluator's read-only observation route is not readable by any agent role. No MCP tools.
    ("GET", "/v1/agent-evaluations/{report_id}"): frozenset({"evaluator", "operations", "human_approver", "instructor"}),
    ("GET", "/v1/agent-system-manifests/qualified"): frozenset({"evaluator", "operations", "human_approver",
                                                                "instructor"}),
    ("POST", "/v1/agent-system-manifests/attestations"): frozenset({"evaluator"}),
    ("GET", "/v1/evaluator/observations"): frozenset({"evaluator"}),
}


@dataclass(frozen=True)
class Identity:
    role: str

    @property
    def principal(self) -> str:
        return f"role:{self.role}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Authenticator:
    def __init__(self, token_hashes: dict[str, str]):
        unknown = set(token_hashes) - ROLES
        if unknown:
            raise ValueError("unknown role in token configuration")
        # Fixed iteration order over every role so timing does not depend on which matched.
        self._entries = [(role, bytes.fromhex(token_hashes[role])) for role in sorted(token_hashes)]

    def authenticate(self, authorization: str | None) -> Identity | None:
        if not authorization or not authorization.startswith("Bearer "):
            return None
        token = authorization[len("Bearer "):].strip()
        if not TOKEN_MIN_LEN <= len(token) <= TOKEN_MAX_LEN or not token.isascii():
            return None
        digest = hashlib.sha256(token.encode("ascii")).digest()
        matched: str | None = None
        for role, expected in self._entries:
            if hmac.compare_digest(digest, expected):
                matched = role
        return Identity(matched) if matched else None


def allowed_roles(method: str, route_path: str) -> frozenset[str] | None:
    """Return the allowed roles, or None when no policy exists (deny)."""
    return PERMISSIONS.get((method.upper(), route_path))
