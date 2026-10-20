"""Phase 10 (A12, AGENTS.md): graders, case set and evaluator credentials are outside every developer tool.

Static boundary checks plus in-process probes with the developer credential. The live probes are
``scripts/run_agent_evals.py --probe-isolation`` (same checks against the deployed lab).
"""
from __future__ import annotations

import re
from pathlib import Path

from services.lab.config import REPO_ROOT
from services.lab.mcp import CATALOG
from tests.conftest import eval_report, headers, qualify

GRADER_FILES = sorted((REPO_ROOT / "tests" / "agent_cases").glob("*.py"))
MARKERS = ("def grade(", "check_catalog", "GRADERS =", "CASE_SET_VERSION", "_ae03(")


def test_grader_files_exist_and_are_not_copied_into_the_lab_image():
    assert GRADER_FILES, "tests/agent_cases is missing"
    copies = [ln for ln in (REPO_ROOT / "Dockerfile.lab").read_text().splitlines() if ln.startswith("COPY")]
    assert copies and not [c for c in copies if re.search(r"\b(tests|scripts|reports)/", c)]
    assert not [c for c in copies if re.match(r"COPY\s+\.\s", c)], "the lab image must not copy the whole repository"


def test_no_grader_text_in_the_corpus_skills_or_fixtures():
    for folder in ("knowledge", "skills", "instructor/fixtures", "contracts"):
        for p in (REPO_ROOT / folder).rglob("*"):
            if p.is_file() and p.suffix in (".md", ".py", ".json", ".txt"):
                text = p.read_text(encoding="utf-8", errors="ignore")
                assert not [m for m in MARKERS if m in text], p


def test_developer_tools_cannot_reach_reports_graders_or_observations(seeded):
    rec = qualify(seeded.client)
    for method, path, body in (("GET", f"/v1/agent-evaluations/{rec['report_id']}", None),
                               ("GET", "/v1/agent-system-manifests/qualified", None),
                               ("GET", "/v1/evaluator/observations?since=2026-01-01T00:00:00Z", None),
                               ("POST", "/v1/agent-evaluations", eval_report()),
                               ("POST", "/v1/agent-system-manifests/attestations", {"system": {}})):
        r = seeded.client.request(method, path, json=body, headers=headers("developer"))
        assert r.status_code == 403, (method, path)
    dev_tools = {t.name for t in CATALOG if "developer" in t.roles()}
    assert dev_tools == {"get_sprint_state", "search_approved_knowledge", "list_skills", "load_skill",
                         "read_candidate", "submit_candidate"}
    for q in ("grader critical check one_repair", "agent cases graders citations_grounded", "QUALIFIED verdict"):
        r = seeded.client.post("/v1/knowledge/search", json={"query": q}, headers=headers("developer")).json()
        for hit in r.get("results") or []:
            assert hit["citation"]["doc_id"] in {"tasksprint-product-brief", "tasksprint-definition-of-done",
                                                 "tasksprint-release-policy"}
            assert not [m for m in MARKERS if m in hit["text"]]
    skills = seeded.client.get("/v1/skills", headers=headers("developer")).json()["skills"]
    assert {s["name"] for s in skills} == {p.name for p in (REPO_ROOT / "skills").iterdir() if p.is_dir()}


def test_evaluator_credential_is_not_an_mcp_identity():
    from services.lab.mcp import MCP_ROLES
    assert "evaluator" not in MCP_ROLES and "instructor" not in MCP_ROLES
    assert Path(REPO_ROOT / "components").is_dir()
    for comp in (REPO_ROOT / "components").glob("*.py"):
        if comp.name != "instructor_control.py":
            assert "TS_EVALUATOR_TOKEN" not in comp.read_text(), comp
