"""Static checks of the MCP tool catalog (A8). Protocol behaviour is in tests/protocol."""
from __future__ import annotations

from services.lab.auth import PERMISSIONS
from services.lab.mcp import CATALOG, MCP_ROLES, visibility_matrix

EXPECTED = {
    "coordinator": ["get_sprint_state", "record_story", "transition_story", "read_preferences", "save_preference",
                    "read_test_report", "read_recent_events"],
    "product_owner": ["get_sprint_state", "search_approved_knowledge"],
    "developer": ["get_sprint_state", "search_approved_knowledge", "list_skills", "load_skill", "read_candidate",
                  "submit_candidate"],
    "qa": ["get_sprint_state", "read_candidate", "run_candidate_tests", "read_test_report", "read_recent_events"],
    "operations": ["get_sprint_state", "list_skills", "load_skill", "read_candidate", "read_test_report",
                   "get_release_readiness", "create_release_plan", "read_release_plan", "execute_approved_plan",
                   "get_release_status", "get_app_health", "read_recent_events"],
    "application": ["get_release_status", "get_app_health"],
}
FORBIDDEN_PROPS = {"token", "password", "secret", "api_key", "url", "uri", "host", "sql", "query_sql", "path",
                   "file", "filename", "env", "environment", "command", "shell", "exec", "code", "role", "approved",
                   "is_admin", "acting_as", "run_id", "workspace_id", "budget", "max_actions"}


def walk_props(schema: dict):
    for name, sub in (schema.get("properties") or {}).items():
        yield name
        yield from walk_props(sub)
    for sub in (schema.get("$defs") or {}).values():
        yield from walk_props(sub)


def test_catalog_has_the_19_a8_tools():
    assert len(CATALOG) == 19 and len({t.name for t in CATALOG}) == 19


def test_visibility_matrix_matches_a8():
    assert visibility_matrix() == EXPECTED
    assert MCP_ROLES == {"coordinator", "product_owner", "developer", "qa", "operations", "application"}


def test_tool_roles_derive_from_rest_permissions():
    for t in CATALOG:
        if t.route is not None:
            assert t.route in PERMISSIONS, t.name
            assert t.roles() == PERMISSIONS[t.route] & MCP_ROLES, t.name
        else:  # pragma: no cover - since Phase 09 every tool has a real backend route
            raise AssertionError(f"{t.name} has no backing route")


def test_no_human_or_instructor_role_gets_tools():
    for role in ("human_approver", "instructor", "evaluator"):
        assert all(role not in t.roles() for t in CATALOG)


def test_schemas_are_closed_and_carry_no_authority_or_infrastructure_fields():
    for t in CATALOG:
        schema = t.tool().inputSchema
        assert schema["type"] == "object" and schema["additionalProperties"] is False, t.name
        names = set(walk_props(schema))
        assert not names & FORBIDDEN_PROPS, (t.name, names & FORBIDDEN_PROPS)


def test_annotations_mark_writes():
    writes = {t.name for t in CATALOG if not t.read_only}
    assert writes == {"record_story", "transition_story", "save_preference", "submit_candidate", "run_candidate_tests",
                      "create_release_plan", "execute_approved_plan"}
