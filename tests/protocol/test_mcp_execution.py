"""Phase 09 over the real MCP protocol: execute_approved_plan is reachable only by Operations and
only ever acts on a human decision recorded through the REST approver route (no MCP tool for it).

Uses the shared spawned stack (real lab + runner processes). No manifest qualifies in this
stack (Phase 10), so the approved deploy plan is refused at A11 step 5: this is the same
denial chain as the live demonstration.
"""
from __future__ import annotations

import pytest

from tests.protocol.test_mcp_protocol import err, ok, run

pytestmark = pytest.mark.protocol


def test_execution_over_mcp_needs_a_human_approval_and_the_manifest_gate(stack):
    ref = stack.rest("POST", "/v1/instructor/actions", "instructor",
                     {"action": "load_fixture", "workspace_id": "demo-001", "fixture": "reference_complete"},
                     None).json()["candidate"]
    report = stack.rest("POST", "/v1/test-runs", "qa", {"candidate_id": ref["candidate_id"]}).json()
    assert report["outcome"] == "pass"
    before = stack.rest("GET", "/v1/releases", "operations").json()

    async def body():
        async with stack.session("operations") as (s, _, _):
            names = [t.name for t in (await s.list_tools()).tools]
            assert "execute_approved_plan" in names and not {"record_approval", "approve_plan"} & set(names)
            plan = ok(await s.call_tool("create_release_plan", {"action": "deploy",
                                                                "candidate_id": ref["candidate_id"]}))["result"]
            pid = plan["plan"]["plan_id"]
            assert plan["state"] == "AWAITING_APPROVAL" and plan["plan"]["agent_manifest_id"] is None
            e = err(await s.call_tool("execute_approved_plan", {"plan_id": pid}))
            assert e["code"] == "APPROVAL_REQUIRED"
            e = err(await s.call_tool("execute_approved_plan", {"plan_id": pid, "approved": True}))
            assert e["code"] == "VALIDATION_ERROR"
            view = stack.rest("GET", f"/v1/release-plans/{pid}", "human_approver").json()
            for role in ("operations", "coordinator", "developer", "qa"):
                assert stack.rest("POST", "/v1/approvals", role, {"plan_id": pid}).status_code == 403, role
            a = stack.rest("POST", "/v1/approvals", "human_approver",
                           {"plan_id": pid, "plan_sha256": view["plan"]["plan_sha256"],
                            "snapshot_sha256": view["snapshot_sha256"], "decision": "approve"})
            assert a.status_code == 201, a.text
            e = err(await s.call_tool("execute_approved_plan", {"plan_id": pid}))
            assert e["code"] == "AGENT_MANIFEST_NOT_QUALIFIED"
            after = stack.rest("GET", f"/v1/release-plans/{pid}", "human_approver").json()
            assert after["state"] == "APPROVED" and after["decision"]["status"] == "active"
    run(body)
    assert stack.rest("GET", "/v1/releases", "operations").json() == before
