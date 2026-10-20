"""Static review checks for the trusted Langflow components (Phase 07; A3, A9).

lfx is not a project dependency, so these tests read the component sources as AST
instead of importing them. They pin the Bounded Toolset's per-role allowlist to the
lab's own MCP visibility matrix, its delegation slots to TS-01/02/03 only, its default
limits to the A9 budgets, and scan for forbidden execution primitives.
"""
from __future__ import annotations

import ast
import re

from services.lab import config
from services.lab.config import REPO_ROOT
from services.lab.mcp import visibility_matrix

COMPONENTS = REPO_ROOT / "components"
TOOLSET = COMPONENTS / "bounded_toolset.py"


def _module(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _constant(tree: ast.Module, name: str):
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found")


def test_allowlist_equals_the_lab_visibility_matrix():
    allow = _constant(_module(TOOLSET), "ALLOWLIST")
    matrix = visibility_matrix()
    assert set(allow) == {"product_owner", "developer", "qa", "coordinator", "operations"}
    for role, tools in allow.items():
        assert list(tools) == matrix[role], role


def test_delegations_point_only_at_the_three_specialists():
    slots = _constant(_module(TOOLSET), "DELEGATIONS")
    assert [(s[0], s[1], s[2]) for s in slots] == [
        ("product_owner_flow", "ask_product_owner", "TS-01 Product Owner"),
        ("developer_flow", "ask_developer", "TS-02 Developer"),
        ("qa_flow", "ask_qa", "TS-03 QA"),
    ]
    text = TOOLSET.read_text(encoding="utf-8")
    assert "TS-90" not in text
    peer = _constant(_module(TOOLSET), "A2A_PEER")
    assert peer[:4] == ("operations_peer", "assess_production_release", "TS-20 Production Manager", "ts20_production_manager_a2a")
    assert _constant(_module(TOOLSET), "A2A_PAYLOAD_SCHEMA_VERSION") == "1.1"
    # the tool name is the one the supplied coordinator prompt uses
    assert "assess_production_release" in (REPO_ROOT / "prompts/coordinator.md").read_text(encoding="utf-8")


def test_a2a_payload_built_by_the_toolset_matches_the_contract():
    """The toolset's payload keys are exactly the contract's; allow_execute is the constant False."""
    import json as _json
    contract = _json.loads((REPO_ROOT / "contracts/handoff-task.schema.json").read_text())
    text = TOOLSET.read_text(encoding="utf-8")
    start = text.index("payload = {\"schema_version\"")
    block = text[start:text.index("started = time.time()", start)]
    keys = set(re.findall(r'"([a-z_0-9]+)":', block))
    assert keys == set(contract["required"]) == set(contract["properties"])
    assert '"allow_execute": False' in block and '"agent_manifest_id": None' in block


def test_a2a_adapter_calls_one_fixed_peer_and_records_the_exchange():
    text = (COMPONENTS / "a2a_audit.py").read_text(encoding="utf-8")
    assert 'PEER_TOOL_NAME = "ts20_production_manager_a2a"' in text
    assert "from a2a.client.client_factory import create_client" in text  # genuine SDK client, no stub server
    assert "pb.GetTaskRequest" in text and "/v1/a2a-exchanges" in text
    assert "follow_redirects=False" in text and "refusing a request outside the fixed peer origin" in text
    assert "context_id=parent_run_id" in text


def test_default_limits_match_the_a9_budgets():
    text = TOOLSET.read_text(encoding="utf-8")
    def default(name: str) -> str:
        m = re.search(rf'name="{name}".*?value=([0-9.]+)', text, re.S)
        assert m, name
        return m.group(1)
    assert int(default("max_actions")) == config.RUN_MAX_ACTIONS == 8
    assert int(default("max_depth")) == config.RUN_MAX_DEPTH == 2
    assert float(default("invocation_timeout_s")) == config.RUN_DEADLINE_SPECIALIST_S == 90
    assert float(default("delegation_timeout_s")) == config.RUN_DEADLINE_SPECIALIST_S
    assert int(default("max_repairs")) == 1
    # clamps: the model cannot raise limits; a flow author cannot exceed the lab's caps
    assert "min(8, int(self.max_actions))" in text and "min(180.0," in text and "min(2, int(self.max_depth))" in text


def test_components_use_no_execution_primitives():
    banned_names = {"exec", "eval", "__import__", "compile"}
    banned_modules = {"importlib", "pickle", "subprocess", "marshal", "shelve", "ctypes"}
    for path in COMPONENTS.glob("*.py"):
        tree = _module(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in banned_names, f"{path.name}: {node.func.id}"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for m in mods:
                    assert m.split(".")[0] not in banned_modules, f"{path.name}: {m}"
            if isinstance(node, ast.Attribute) and node.attr == "environ":
                raise AssertionError(f"{path.name}: environment access")


def test_run_context_creates_child_runs_only_for_server_issued_ids():
    text = (COMPONENTS / "run_context.py").read_text(encoding="utf-8")
    assert 'RUN_RE = re.compile(r"^run_[0-9a-f]{32}$")' in text
    assert 'body_in["parent_run_id"] = session' in text
    assert 'A2A_SESSION_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:(run_[0-9a-f]{32})$")' \
        in text
    assert text.count("group_outputs=True") == 3
