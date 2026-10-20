"""Phase 09 over the real MCP protocol: execute_approved_plan is reachable only by Operations and
only ever acts on a human decision recorded through the REST approver route (no MCP tool for it).

Uses the shared spawned stack (real lab + runner processes). Phase 10: a TEST-ONLY qualifying
report is recorded through the evaluator REST route so the deploy plan binds its manifest; after
the human approval a later failing evaluation of the same manifest invalidates the baseline, so
the approved plan is refused at A11 step 5. The stack's gate is left INVALIDATED (never PASS).
"""
from __future__ import annotations

import pytest

from tests.conftest import eval_report
from tests.protocol.test_mcp_protocol import err, ok, run

pytestmark = pytest.mark.protocol


def test_execution_over_mcp_needs_a_human_approval_and_the_manifest_gate(stack):
    ref = stack.rest("POST", "/v1/instructor/actions", "instructor",
                     {"action": "load_fixture", "workspace_id": "demo-001", "fixture": "reference_complete"},
                     None).json()["candidate"]
    report = stack.rest("POST", "/v1/test-runs", "qa", {"candidate_id": ref["candidate_id"]}).json()
    assert report["outcome"] == "pass"
    before = stack.rest("GET", "/v1/releases", "operations").json()
    for role in ("operations", "coordinator", "developer", "qa", "instructor"):
        assert stack.rest("POST", "/v1/agent-evaluations", role, eval_report()).status_code == 403, role
    q = stack.rest("POST", "/v1/agent-evaluations", "evaluator", eval_report())
    assert q.status_code == 201 and q.json()["verdict"] == "QUALIFIED", q.text
    manifest_id = q.json()["manifest_id"]

    async def body():
        async with stack.session("operations") as (s, _, _):
            names = [t.name for t in (await s.list_tools()).tools]
            assert "execute_approved_plan" in names and not {"record_approval", "approve_plan"} & set(names)
            plan = ok(await s.call_tool("create_release_plan", {"action": "deploy",
                                                                "candidate_id": ref["candidate_id"]}))["result"]
            pid = plan["plan"]["plan_id"]
            assert plan["state"] == "AWAITING_APPROVAL" and plan["plan"]["agent_manifest_id"] == manifest_id
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
            bad = stack.rest("POST", "/v1/agent-evaluations", "evaluator",
                             eval_report(purpose="partial", cases=["AE-04"], repetitions=1, fail=(("AE-04", 1),)))
            assert bad.status_code == 201 and bad.json()["manifest_id"] == manifest_id
            e = err(await s.call_tool("execute_approved_plan", {"plan_id": pid}))
            assert e["code"] == "AGENT_MANIFEST_NOT_QUALIFIED"
            after = stack.rest("GET", f"/v1/release-plans/{pid}", "human_approver").json()
            assert after["state"] == "APPROVED" and after["decision"]["status"] == "active"
    run(body)
    assert stack.rest("GET", "/v1/releases", "operations").json() == before
