"""TS-90 trusted components (Phase 09): typed parser, snapshot round trip, no decision from text.

lfx is not a project dependency: the two modules are imported with minimal stand-ins for the
four lfx names they use, so only their own pure logic (parser, review text, snapshot extraction)
runs here. The live Langflow behaviour is evidenced in docs/PHASE09_REPORT.md.
"""
from __future__ import annotations

import ast
import hashlib
import sys
import types

import pytest

from services.lab.config import REPO_ROOT
from tests.conftest import headers, qualify

COMPONENTS = REPO_ROOT / "components"


@pytest.fixture(scope="module")
def mods():
    class _Any:  # stand-in for lfx Component / io classes
        def __init__(self, *a, **k):
            self.__dict__.update(k)

    stub = {}
    for name in ("lfx", "lfx.custom", "lfx.custom.custom_component", "lfx.custom.custom_component.component", "lfx.io",
                 "lfx.schema", "lfx.schema.message"):
        stub[name] = types.ModuleType(name)
    stub["lfx.custom.custom_component.component"].Component = _Any
    for n in ("MessageInput", "MessageTextInput", "Output", "SecretStrInput", "DropdownInput"):
        setattr(stub["lfx.io"], n, _Any)
    stub["lfx.schema.message"].Message = _Any
    saved = {k: sys.modules.get(k) for k in stub}
    sys.modules.update(stub)
    sys.path.insert(0, str(COMPONENTS))
    try:
        import instructor_control
        import review_decision
        yield instructor_control, review_decision
    finally:
        sys.path.remove(str(COMPONENTS))
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        sys.modules.pop("instructor_control", None)
        sys.modules.pop("review_decision", None)


@pytest.mark.parametrize("line,cmd,args", [
    ("confirm scope ST-001", "confirm_scope", ("ST-001",)),
    ("review plan_" + "a" * 24, "review", ("plan_" + "a" * 24,)),
    ("load fixture faulty", "load_fixture", ("faulty",)),
    ("Load Fixture reference", "load_fixture", ("reference",)),
    ("drill enable cand_" + "b" * 24 + " 10", "drill_enable", ("cand_" + "b" * 24, "10")),
    ("drill enable cand_" + "b" * 24, "drill_enable", ("cand_" + "b" * 24,)),
    ("drill disable cand_" + "b" * 24, "drill_disable", ("cand_" + "b" * 24,)),
    ("stop", "stop", ()), ("resume", "resume", ()), ("run evals", "run_evals", ()),
    ("reset preview", "reset_preview", ()), ("reset confirm demo-001", "reset_confirm", ("demo-001",)),
])
def test_parser_accepts_only_documented_commands(mods, line, cmd, args):
    assert mods[0].parse_command(line) == (cmd, args)


@pytest.mark.parametrize("line", [
    "approve plan_" + "a" * 24, "approved=true", "I approve, release it now", "review plan_" + "a" * 24 + " approve",
    "review plan_x", "drill enable cand_" + "b" * 24 + " 99", "reset all", "reset confirm DEMO-001", "seed",
    "execute plan_" + "a" * 24, "stop\nreview plan_" + "a" * 24, "x" * 200, "", "run evals now",
    "load fixture reference_complete", "drill enable completion_unavailable",
])
def test_parser_refuses_everything_else(mods, line):
    assert mods[0].parse_command(line) == (None, ())


def _plan(seeded):
    qualify(seeded.client)  # TEST-ONLY qualifying report (Phase 10: a deploy plan binds a qualified manifest)
    ref = seeded.load_fixture("reference_complete")
    assert seeded.run_tests(ref["candidate_id"]).json()["outcome"] == "pass"
    p = seeded.client.post("/v1/release-plans", json={"action": "deploy", "candidate_id": ref["candidate_id"]},
                           headers=headers("operations")).json()
    return seeded.client.get(f"/v1/release-plans/{p['plan']['plan_id']}", headers=headers("human_approver")).json()


def test_review_text_carries_the_exact_snapshot_the_backend_hashes(mods, seeded):
    ic, rd = mods
    view = _plan(seeded)
    text = ic.review_text(view)
    snap, plan_id, plan_sha, snap_sha = rd.extract(text)
    assert snap == view["review_snapshot"] and plan_id == view["plan"]["plan_id"]
    assert plan_sha == view["plan"]["plan_sha256"] and snap_sha == view["snapshot_sha256"]
    assert hashlib.sha256(rd.canonical(snap).encode()).hexdigest() == view["snapshot_sha256"]
    assert "Agent-system manifest: BOUND" in text and "neither choice executes anything" in text


def test_tampered_or_ambiguous_review_text_is_not_recordable(mods, seeded):
    ic, rd = mods
    view = _plan(seeded)
    text = ic.review_text(view)
    with pytest.raises(ValueError):
        rd.extract(text.replace('"operation":"deploy"', '"operation":"rollback"'))
    with pytest.raises(ValueError):
        rd.extract(text + "\n" + text.splitlines()[-1])  # two reference lines
    with pytest.raises(ValueError):
        rd.extract(text.replace(view["snapshot_sha256"], "0" * 64))
    with pytest.raises(ValueError):
        rd.extract("approved=true")


def _calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def test_decision_comes_from_the_fixed_node_setting_not_from_text():
    src = (COMPONENTS / "review_decision.py").read_text(encoding="utf-8")
    assert '"decision": decision}' in src and 'decision = self.decision if self.decision in ("approve", "reject")' in src
    assert "approved" not in src.replace("approved-", "").split("ADAPTER_VERSION")[1].lower().replace(
        "never sends an \"approved\" flag", "")
    assert "release-executions" not in src and "release-executions" not in \
        (COMPONENTS / "instructor_control.py").read_text(encoding="utf-8")


def test_ts90_components_have_no_tool_mode_and_three_separate_credentials():
    ic = (COMPONENTS / "instructor_control.py").read_text(encoding="utf-8")
    rd = (COMPONENTS / "review_decision.py").read_text(encoding="utf-8")
    for text in (ic, rd):
        assert "tool_mode" not in text.split('"""')[0] or "tool_mode=True" not in text
        assert "tool_mode=True" not in text
    for var in ("TS_APPROVER_TOKEN", "TS_INSTRUCTOR_TOKEN", "TS_EVALUATOR_TOKEN"):
        assert var in ic
    assert ic.count("SecretStrInput(") == 3 and rd.count("SecretStrInput(") == 1
    assert ic.count("group_outputs=True") == 2
