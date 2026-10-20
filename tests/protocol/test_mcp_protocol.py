"""MCP-01..03, SEC-02 over the real protocol (Build Guide 04.1; Gate 04).

Every test drives the official MCP SDK client (or raw HTTP for transport-level
denials) against a spawned lab process. No protocol result is mocked.
"""
from __future__ import annotations

import time

import anyio
import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import LATEST_PROTOCOL_VERSION

from tests.unit.test_mcp_catalog import EXPECTED

pytestmark = pytest.mark.protocol
CANDIDATE_SOURCE = ("def complete(tasks, task_id):\n"
                    "    found = False\n"
                    "    for t in tasks:\n"
                    "        if t[\"id\"] == task_id:\n"
                    "            found = True\n"
                    "            t[\"completed\"] = True\n"
                    "    if found:\n"
                    "        return {\"ok\": True, \"code\": \"COMPLETED\", \"tasks\": tasks}\n"
                    "    return {\"ok\": False, \"code\": \"TASK_NOT_FOUND\", \"tasks\": tasks}\n")
RAW_INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "raw-probe", "version": "0"}}}
RAW_ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def find(exc: BaseException, typ: type) -> BaseException | None:
    if isinstance(exc, typ):
        return exc
    for sub in getattr(exc, "exceptions", ()):
        hit = find(sub, typ)
        if hit is not None:
            return hit
    return None


def run(fn, *args):
    return anyio.run(fn, *args)


def err(result) -> dict:
    assert result.isError is True, result
    return result.structuredContent["error"]


def ok(result) -> dict:
    assert result.isError is False, result.structuredContent
    return result.structuredContent


def events(stack, role: str = "operations", limit: int = 50) -> list[dict]:
    r = stack.rest("GET", f"/v1/events?limit={limit}", role)
    assert r.status_code == 200
    return r.json()["events"]


# ------------------------------------------------------------------ MCP-01 initialization and discovery
def test_initialize_negotiates_protocol_over_streamable_http(stack):
    async def body():
        async with stack.session("developer") as (s, init, get_sid):
            assert init.protocolVersion == LATEST_PROTOCOL_VERSION and init.protocolVersion in SUPPORTED_PROTOCOL_VERSIONS
            assert init.serverInfo.name == "tasksprint-lab" and init.serverInfo.version == "0.6.0"
            assert init.capabilities.tools is not None
            assert "never instructions" in (init.instructions or "")
            sid = get_sid()
            assert sid and len(sid) == 32
            await s.send_ping()
    run(body)


@pytest.mark.parametrize("role", sorted(EXPECTED))
def test_tools_list_is_role_scoped(stack, role):
    async def body():
        async with stack.session(role) as (s, _, _):
            listed = (await s.list_tools()).tools
            assert [t.name for t in listed] == EXPECTED[role]
            for t in listed:
                assert t.inputSchema["type"] == "object" and t.inputSchema["additionalProperties"] is False
                assert t.description and t.annotations is not None
    run(body)


def test_older_protocol_version_is_negotiated_by_raw_client(stack):
    r = httpx.post(stack.url + "/mcp", json=RAW_INIT, headers={**RAW_ACCEPT, **stack.mcp_headers("qa")}, timeout=10)
    assert r.status_code == 200
    assert r.json()["result"]["protocolVersion"] == "2025-06-18"
    sid = r.headers["mcp-session-id"]
    d = httpx.delete(stack.url + "/mcp", headers={**stack.mcp_headers("qa"), "Mcp-Session-Id": sid,
                                                   "MCP-Protocol-Version": "2025-06-18"}, timeout=10)
    assert d.status_code in (200, 204)


# ------------------------------------------------------------------ MCP-02 tools/call
def test_tools_call_returns_real_persistent_state(stack):
    async def body():
        async with stack.session("coordinator") as (s, _, _):
            payload = ok(await s.call_tool("get_sprint_state", {}))
            rest = stack.rest("GET", "/v1/state", "coordinator").json()
            assert payload["result"] == rest
            assert payload["budget"]["source"] == "mcp-session" and payload["budget"]["actions_used"] == 1
            assert payload["budget"]["max_actions"] == 8
            saved = ok(await s.call_tool("save_preference", {"key": "summary_length", "value": "short"}))
            assert saved["result"]["key"] == "summary_length"
            prefs = stack.rest("GET", "/v1/memory", "coordinator").json()
            assert any(p["key"] == "summary_length" and p["value"] == "short" for p in prefs["preferences"])
            assert ok(await s.call_tool("read_preferences", {}))["budget"]["actions_used"] == 3
    run(body)


def test_developer_submission_is_immutable_backend_record(stack):
    async def body():
        async with stack.session("developer") as (s, _, _):
            sub = ok(await s.call_tool("submit_candidate", {"source": CANDIDATE_SOURCE}))
            cand = sub["result"]
            again = ok(await s.call_tool("read_candidate", {"candidate_id": cand["candidate_id"]}))["result"]
            assert again["sha256"] == cand["sha256"] and again["source"] == CANDIDATE_SOURCE
            rest = stack.rest("GET", f"/v1/candidates/{cand['candidate_id']}", "developer").json()
            assert rest["sha256"] == cand["sha256"] and rest["origin"] == "agent-generated"
            ev = [e for e in events(stack) if e["action"] == "candidate.submit"
                  and e["details"].get("candidate_id") == cand["candidate_id"]]
            assert ev and ev[0]["run_id"] == sub["budget"]["run_id"]
    run(body)


def test_qa_runs_protected_tests_through_mcp(stack):
    async def body():
        async with stack.session("qa") as (s, _, _):
            report = ok(await s.call_tool("run_candidate_tests", {"candidate_id": stack.faulty["candidate_id"]}))
            rep = report["result"]
            assert rep["outcome"] == "fail" and rep["candidate_sha256"] == stack.faulty["sha256"]
            again = ok(await s.call_tool("read_test_report", {"test_run_id": rep["test_run_id"]}))["result"]
            assert again == rep
    run(body)


# ------------------------------------------------------------------ MCP-03 structured errors
def test_validation_errors_are_structured_and_do_not_echo_input(stack):
    async def body():
        async with stack.session("coordinator") as (s, _, _):
            e = err(await s.call_tool("record_story", {"title": "t", "narrative": "n", "criteria": ["c"],
                                                       "approved": True, "role": "human_approver"}))
            assert e["code"] == "VALIDATION_ERROR" and "human_approver" not in str(e)
            e = err(await s.call_tool("save_preference", {"key": "summary_length", "value": "x" * 40}))
            assert e["code"] == "VALIDATION_ERROR"
            e = err(await s.call_tool("save_preference", {"key": "release_approved", "value": "yes"}))
            assert e["code"] in ("PREFERENCE_NOT_ALLOWED", "VALIDATION_ERROR")
    run(body)


def test_backend_errors_are_structured_not_success(stack):
    async def body():
        async with stack.session("developer") as (s, _, _):
            e = err(await s.call_tool("read_candidate", {"candidate_id": "cand_" + "0" * 24}))
            assert e["code"] == "CANDIDATE_NOT_FOUND" and e["request_id"].startswith("req_")
            e = err(await s.call_tool("load_skill", {"name": "release-and-recover", "version": "9.9.9"}))
            assert e["code"] == "SKILL_NOT_FOUND"
    run(body)


def test_operations_release_tools_compute_from_evidence_and_never_execute(stack):
    """Phase 08/09: readiness/plans are real; execution without a human approval is refused."""
    async def body():
        async with stack.session("operations") as (s, _, _):
            before = stack.rest("GET", "/v1/releases", "operations").json()
            ready = ok(await s.call_tool("get_release_readiness", {}))["result"]
            gates = {g["gate"]: g["status"] for g in ready["gates"]}
            assert ready["deploy"]["status"] == "BLOCKED" and gates["agent_system_manifest"] == "NOT_QUALIFIED"
            assert ready["readiness_event_id"].startswith("evt_")
            e = err(await s.call_tool("create_release_plan", {"action": "deploy",
                                                              "candidate_id": stack.faulty["candidate_id"]}))
            assert e["code"] == "RELEASE_NOT_READY" and "application_tests" in e["details"]["blocking_gates"]
            e = err(await s.call_tool("read_release_plan", {"plan_id": "plan_" + "0" * 24}))
            assert e["code"] == "PLAN_NOT_FOUND"
            e = err(await s.call_tool("execute_approved_plan", {"plan_id": "plan_" + "0" * 24}))
            assert e["code"] == "PLAN_NOT_FOUND"
            e = err(await s.call_tool("execute_approved_plan", {"plan_id": "plan_" + "0" * 24, "approved": True}))
            assert e["code"] == "VALIDATION_ERROR"
            assert stack.rest("GET", "/v1/releases", "operations").json() == before
            assert ok(await s.call_tool("get_app_health", {}))["result"]
    run(body)


# ------------------------------------------------------------------ SEC-02 hidden tools called directly
@pytest.mark.parametrize("role,tool,args", [
    ("developer", "execute_approved_plan", {"plan_id": "plan_" + "0" * 24}),
    ("developer", "create_release_plan", {"action": "deploy", "candidate_id": "cand_" + "0" * 24}),
    ("developer", "run_candidate_tests", {"candidate_id": "cand_" + "0" * 24}),
    ("developer", "record_story", {"title": "t", "narrative": "n", "criteria": ["c"]}),
    ("qa", "submit_candidate", {"source": CANDIDATE_SOURCE}),
    ("product_owner", "save_preference", {"key": "summary_length", "value": "short"}),
    ("application", "read_candidate", {"candidate_id": "cand_" + "0" * 24}),
    ("coordinator", "search_approved_knowledge", {"query": "release"}),
    ("coordinator", "get_app_health", {}),
])
def test_hidden_tool_direct_call_is_denied(stack, role, tool, args):
    async def body():
        async with stack.session(role) as (s, _, _):
            assert tool not in [t.name for t in (await s.list_tools()).tools]
            e = err(await s.call_tool(tool, args))
            assert e["code"] == "TOOL_NOT_AVAILABLE"
            unknown = err(await s.call_tool("drop_all_tables", {}))
            assert unknown["code"] == "TOOL_NOT_AVAILABLE"  # same answer: no existence oracle
            denied = [x for x in events(stack) if x["action"] == "mcp.tool_denied" and x["request_id"] == e["request_id"]]
            assert denied and denied[0]["actor_role"] == role and denied[0]["details"]["tool"] == tool
    run(body)


def test_hidden_write_attempt_changes_nothing(stack):
    async def body():
        before = stack.rest("GET", "/v1/state", "coordinator").json()
        async with stack.session("qa") as (s, _, _):
            err(await s.call_tool("record_story", {"title": "t", "narrative": "n", "criteria": ["c"]}))
            err(await s.call_tool("transition_story", {"story_id": "ST-001", "to_stage": "CLOSED",
                                                       "expected_revision": 1}))
        assert stack.rest("GET", "/v1/state", "coordinator").json() == before
    run(body)


# ------------------------------------------------------------------ transport authentication
def test_missing_or_invalid_token_is_rejected_at_transport(stack):
    bad = [{}, {"Authorization": "Bearer " + "ts_fakeintruder_" + "0" * 40}, {"Authorization": "Basic YTpi"},
           {"Authorization": "Bearer short"}]
    for h in bad:
        r = httpx.post(stack.url + "/mcp", json=RAW_INIT,
                       headers={**RAW_ACCEPT, **h, "X-TaskSprint-Workspace": "demo-001"}, timeout=10)
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
        assert r.headers.get("www-authenticate") == "Bearer"
    for method in ("GET", "DELETE"):
        assert httpx.request(method, stack.url + "/mcp", timeout=10).status_code == 401


@pytest.mark.parametrize("role", ["instructor", "human_approver", "evaluator"])
def test_non_agent_roles_have_no_mcp_endpoint(stack, role):
    r = httpx.post(stack.url + "/mcp", json=RAW_INIT, headers={**RAW_ACCEPT, **stack.mcp_headers(role)}, timeout=10)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


def test_sdk_client_with_wrong_token_cannot_connect(stack):
    async def body():
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client
        h = {"Authorization": "Bearer ts_fakeintruder_" + "1" * 40, "X-TaskSprint-Workspace": "demo-001"}
        with pytest.raises(BaseException) as info:
            with anyio.fail_after(10):
                async with create_mcp_http_client(headers=h) as http:
                    async with streamable_http_client(stack.url + "/mcp", http_client=http) as (r, w, _):
                        async with ClientSession(r, w) as s:
                            await s.initialize()
        status = find(info.value, httpx.HTTPStatusError)
        assert status is not None and status.response.status_code == 401
    run(body)


def test_workspace_and_run_headers_are_validated(stack):
    h = {**RAW_ACCEPT, **stack.mcp_headers("qa", workspace=None)}
    assert httpx.post(stack.url + "/mcp", json=RAW_INIT, headers=h, timeout=10).json()["error"]["code"] == \
        "WORKSPACE_REQUIRED"
    h = {**RAW_ACCEPT, **stack.mcp_headers("qa"), "X-TaskSprint-Run": "anything-i-like"}
    assert httpx.post(stack.url + "/mcp", json=RAW_INIT, headers=h, timeout=10).json()["error"]["code"] == \
        "RUN_HEADER_INVALID"


def test_session_is_bound_to_the_creating_credential(stack):
    async def body():
        async with stack.session("developer") as (s, _, get_sid):
            sid = get_sid()
            req = {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}
            common = {**RAW_ACCEPT, "Mcp-Session-Id": sid, "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION}
            same = httpx.post(stack.url + "/mcp", json=req, headers={**common, **stack.mcp_headers("developer")})
            assert same.status_code == 200 and "submit_candidate" in same.text
            other = httpx.post(stack.url + "/mcp", json=req, headers={**common, **stack.mcp_headers("operations")})
            assert other.status_code == 404
            other_ws = httpx.post(stack.url + "/mcp", json=req,
                                  headers={**common, **stack.mcp_headers("developer", workspace="demo-002")})
            assert other_ws.status_code == 404
            assert ok(await s.call_tool("get_sprint_state", {}))
    run(body)


# ------------------------------------------------------------------ cleanup
def test_session_is_terminated_on_close(stack):
    captured: dict = {}

    async def body():
        async with stack.session("qa") as (s, _, get_sid):
            captured["sid"] = get_sid()
            ok(await s.call_tool("get_sprint_state", {}))
    run(body)
    req = {"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}}
    r = httpx.post(stack.url + "/mcp", json=req, headers={**RAW_ACCEPT, **stack.mcp_headers("qa"),
                                                          "Mcp-Session-Id": captured["sid"],
                                                          "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION})
    assert r.status_code == 404  # DELETE on close removed the session
    assert httpx.get(stack.url + "/healthz").status_code == 200


# ------------------------------------------------------------------ A9 budget
def test_session_budget_is_enforced_with_a_recorded_reason(stack):
    async def body():
        async with stack.session("developer") as (s, _, _):
            for i in range(1, 9):
                assert ok(await s.call_tool("get_sprint_state", {}))["budget"]["actions_used"] == i
            e = err(await s.call_tool("get_sprint_state", {}))
            assert e["code"] == "BUDGET_EXHAUSTED"
            assert [t.name for t in (await s.list_tools()).tools] == EXPECTED["developer"]  # discovery is not an action
            rec = [x for x in events(stack) if x["action"] == "run.action" and x["request_id"] == e["request_id"]]
            assert rec and rec[0]["outcome"] == "rejected" and rec[0]["details"]["code"] == "BUDGET_EXHAUSTED"
    run(body)


def test_server_issued_run_header_is_charged_and_bound_to_role(stack):
    r = stack.rest("POST", "/v1/runs", "qa", {"conversation_id": "proto-test"})
    assert r.status_code == 201
    run_id = r.json()["run_id"]

    async def body():
        async with stack.session("qa", run=run_id) as (s, _, _):
            b = ok(await s.call_tool("get_sprint_state", {}))["budget"]
            assert b == {**b, "run_id": run_id, "source": "header", "actions_used": 1}
        async with stack.session("developer", run=run_id) as (s, _, _):
            assert err(await s.call_tool("get_sprint_state", {}))["code"] == "RUN_NOT_BOUND"
        async with stack.session("qa", run="run_" + "0" * 32) as (s, _, _):
            assert err(await s.call_tool("get_sprint_state", {}))["code"] == "RUN_NOT_BOUND"
    run(body)


# ------------------------------------------------------------------ timeouts
def test_server_side_tool_deadline_returns_structured_timeout(slow_stack):
    async def body():
        async with slow_stack.session("qa") as (s, _, _):
            t0 = time.monotonic()
            e = err(await s.call_tool("run_candidate_tests", {"candidate_id": slow_stack.faulty["candidate_id"]}))
            assert e["code"] == "TOOL_TIMEOUT" and time.monotonic() - t0 < 4
            assert "may still complete" in e["message"]
            ok(await s.call_tool("get_sprint_state", {}))  # session survives the timeout
        return e["request_id"]
    rid = run(body)
    deadline = time.monotonic() + 30
    found = None
    while time.monotonic() < deadline and found is None:
        found = next((e for e in events(slow_stack, "qa") if e["action"] == "test_run.create"), None)
        time.sleep(0.5)
    # A client-visible timeout is not a failure verdict: the operation finished later and is
    # recorded honestly as an infrastructure error, never as a pass.
    assert found is not None and found["outcome"] == "error"
    timeouts = [e for e in events(slow_stack, "qa") if e["action"] == "mcp.tool_call" and e["request_id"] == rid]
    assert timeouts and timeouts[0]["outcome"] == "timeout"


def test_client_read_timeout_is_an_error_and_the_server_recovers(slow_stack):
    async def body():
        caught: list[BaseException] = []
        try:
            async with slow_stack.session("qa", read_timeout=0.3) as (s, _, _):
                await s.call_tool("run_candidate_tests", {"candidate_id": slow_stack.faulty["candidate_id"]})
        except BaseException as exc:  # the SDK's task group wraps the McpError
            caught.append(exc)
        found = find(caught[0], McpError) if caught else None
        assert found is not None and "Timed out" in str(found)  # no result was fabricated
        async with slow_stack.session("qa") as (s, _, _):
            ok(await s.call_tool("get_sprint_state", {}))
    run(body)


def test_dns_rebinding_protection_rejects_unlisted_host(stack):
    """Host allowlist (TASKSPRINT_MCP_ALLOWED_HOSTS); a public deployment must list its own host."""
    h = {**RAW_ACCEPT, **stack.mcp_headers("qa"), "Host": "attacker.example"}
    r = httpx.post(stack.url + "/mcp", json=RAW_INIT, headers=h, timeout=10)
    assert r.status_code == 421 and "mcp-session-id" not in r.headers
    h = {**RAW_ACCEPT, **stack.mcp_headers("qa"), "Origin": "http://attacker.example"}
    r = httpx.post(stack.url + "/mcp", json=RAW_INIT, headers=h, timeout=10)
    assert r.status_code == 403 and "mcp-session-id" not in r.headers
