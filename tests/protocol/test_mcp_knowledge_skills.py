"""Build Guide 04.4 distinctions through the real MCP protocol (Gate 04).

1. Archived "delete completed tasks" guidance is excluded from the current-evidence tool.
2. A current retention passage is returned and cited.
3. A developer who loads the release skill still cannot plan or execute a release.
"""
from __future__ import annotations

import hashlib

import pytest

from tests.protocol.test_mcp_protocol import err, events, ok, run
from tests.unit.test_mcp_catalog import EXPECTED

pytestmark = pytest.mark.protocol
ARCHIVED = "tasksprint-early-design-note"


def test_archived_delete_guidance_is_not_current_evidence(stack):
    async def body():
        async with stack.session("product_owner") as (s, _, _):
            for q in ("delete completed tasks", "remove a task from storage when marked complete"):
                res = ok(await s.call_tool("search_approved_knowledge", {"query": q}))["result"]
                assert all(r["citation"]["doc_id"] != ARCHIVED for r in res["results"]), q
                assert all(r["document"]["status"] == "approved" for r in res["results"])
            # The instructor's unfiltered view (REST only, not a tool) does contain it.
            r = stack.rest("POST", "/v1/instructor/knowledge/search", "instructor",
                           {"query": "remove a task from storage when marked complete"}, None)
            assert ARCHIVED in {x["citation"]["doc_id"] for x in r.json()["results"]}
    run(body)


def test_current_retention_passage_is_returned_with_citation(stack):
    async def body():
        async with stack.session("product_owner") as (s, _, _):
            res = ok(await s.call_tool("search_approved_knowledge",
                                       {"query": "keep completed task records in the list"}))
            top = res["result"]["results"][0]
            assert top["citation"]["doc_id"] == "tasksprint-product-brief" and top["citation"]["version"] == "1.0"
            assert top["citation"]["section"] in {"Completion story", "Acceptance criteria"}
            assert set(top["citation"]) == {"doc_id", "version", "section", "owner", "hash"}
            assert len(res["result"]["results"]) <= 3
            ev = [e for e in events(stack, "operations") if e["action"] == "knowledge.search"
                  and e["request_id"] == res["request_id"]]
            assert ev and ev[0]["actor_role"] == "product_owner" and ev[0]["run_id"] == res["budget"]["run_id"]
    run(body)


def test_nonsense_query_abstains_over_mcp(stack):
    async def body():
        async with stack.session("developer") as (s, _, _):
            res = ok(await s.call_tool("search_approved_knowledge", {"query": "zebra quantum saxophone"}))["result"]
            assert res["status"] == "abstain" and res["results"] == []
            assert res["abstention"]["code"] == "NO_APPROVED_EVIDENCE"
    run(body)


def test_developer_loading_release_skill_still_cannot_deploy(stack):
    async def body():
        async with stack.session("developer") as (s, _, _):
            listed = ok(await s.call_tool("list_skills", {}))["result"]["skills"]
            meta = next(x for x in listed if x["name"] == "release-and-recover")
            assert "body" not in meta
            loaded = ok(await s.call_tool("load_skill", {"name": "release-and-recover", "version": meta["version"]}))
            skill = loaded["result"]
            assert hashlib.sha256(skill["body"].encode()).hexdigest() == skill["body_sha256"] == meta["body_sha256"]
            assert "execute_approved_plan" not in [t.name for t in (await s.list_tools()).tools]
            assert [t.name for t in (await s.list_tools()).tools] == EXPECTED["developer"]
            for tool, args in (("execute_approved_plan", {"plan_id": "plan_" + "0" * 24}),
                               ("create_release_plan", {"action": "deploy", "candidate_id": "cand_" + "0" * 24}),
                               ("get_release_status", {})):
                assert err(await s.call_tool(tool, args))["code"] == "TOOL_NOT_AVAILABLE", tool
            ev = [e for e in events(stack, "operations") if e["action"] == "skill_loaded"
                  and e["request_id"] == loaded["request_id"]]
            assert ev and ev[0]["details"] == {"name": "release-and-recover", "version": "1.0.0",
                                               "body_sha256": skill["body_sha256"]}
        # Same with a fresh session: skill loads do not persist as authority either.
        async with stack.session("developer") as (s, _, _):
            assert [t.name for t in (await s.list_tools()).tools] == EXPECTED["developer"]
    run(body)


def test_operations_can_load_its_skill_and_read_but_not_search_knowledge(stack):
    async def body():
        async with stack.session("operations") as (s, _, _):
            skill = ok(await s.call_tool("load_skill", {"name": "release-and-recover", "version": "1.0.0"}))
            assert skill["result"]["body"].startswith("# Release and recover")
            assert err(await s.call_tool("search_approved_knowledge", {"query": "release"}))["code"] == \
                "TOOL_NOT_AVAILABLE"
    run(body)
