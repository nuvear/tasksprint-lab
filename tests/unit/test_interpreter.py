"""Interpreter semantics, limits and the three fixtures' actual behaviour (A6, Build Guide 03.5)."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from services.runner.interpreter import CandidateError, Limits, evaluate
from services.runner.validator import validate_source

REPO = Path(__file__).resolve().parents[2]
TASKS = [{"id": "T001", "title": "Draft workshop agenda", "completed": False},
         {"id": "T002", "title": "Book the sprint review room", "completed": False},
         {"id": "T003", "title": "Prepare sprint review", "completed": True}]
HEAD = "def complete(tasks, task_id):\n"


def body(*lines: str) -> str:
    return HEAD + "".join(f"    {line}\n" for line in lines)


def run(source: str, tasks=None, task_id="T001", **limits):
    return evaluate(validate_source(source), copy.deepcopy(TASKS if tasks is None else tasks), task_id,
                    Limits(**limits) if limits else Limits())


def fixture(name: str) -> str:
    return (REPO / "instructor" / "fixtures" / name).read_text()


def failure(source: str, tasks=None, task_id="T001", **limits) -> CandidateError:
    with pytest.raises(CandidateError) as exc:
        run(source, tasks, task_id, **limits)
    return exc.value


# ------------------------------------------------------------------ the three fixtures
def test_starter_v0_returns_feature_unavailable_and_unchanged_tasks():
    for tid in ("T001", "T003", "T999"):
        r = run(fixture("starter_v0.py"), task_id=tid).result
        assert r == {"ok": False, "code": "FEATURE_UNAVAILABLE", "tasks": TASKS}


def test_faulty_fixture_actually_removes_the_target():
    r = run(fixture("faulty_delete.py"), task_id="T001").result
    assert r["ok"] is True and r["code"] == "COMPLETED"
    assert [t["id"] for t in r["tasks"]] == ["T002", "T003"]
    unknown = run(fixture("faulty_delete.py"), task_id="T999").result
    assert unknown["code"] == "COMPLETED" and unknown["tasks"] == TASKS  # wrong code for an unknown id


def test_reference_fixture_retains_target_with_completed_true():
    r = run(fixture("reference_complete.py"), task_id="T001").result
    assert r["ok"] is True and r["code"] == "COMPLETED"
    assert r["tasks"][0] == {"id": "T001", "title": "Draft workshop agenda", "completed": True}
    assert r["tasks"][1:] == TASKS[1:]
    again = run(fixture("reference_complete.py"), tasks=r["tasks"], task_id="T001").result
    assert again["tasks"] == r["tasks"]
    missing = run(fixture("reference_complete.py"), task_id="T999").result
    assert missing == {"ok": False, "code": "TASK_NOT_FOUND", "tasks": TASKS}


def test_input_is_deep_copied_in_and_result_out():
    caller = copy.deepcopy(TASKS)
    out = evaluate(validate_source(fixture("reference_complete.py")), caller, "T001")
    assert caller == TASKS  # in-place mutation by the candidate never reaches the caller's objects
    out.result["tasks"][1]["title"] = "changed"
    assert caller[1]["title"] == TASKS[1]["title"]


def test_operation_counts_are_reported():
    out = run(fixture("reference_complete.py"))
    assert 0 < out.ops < 100


# ------------------------------------------------------------------ semantics
def test_boolean_operators_short_circuit_and_return_operands():
    assert run(body("return tasks and 'x'")).result == "x"
    assert run(body("return [] or 'fallback'")).result == "fallback"
    assert run(body("return not tasks")).result is False
    # short circuit: the missing key on the right is never evaluated
    assert run(body("return False and tasks[0]['missing']")).result is False


def test_membership_and_json_equality():
    assert run(body("return 'T001' in [t['id'] for t in tasks]")).result is True
    assert run(body("return 'T009' not in [t['id'] for t in tasks]")).result is True
    assert run(body("return 'id' in tasks[0]")).result is True
    assert run(body("return 'Draft' in tasks[0]['title']")).result is True
    assert run(body("return True == 1")).result is False  # JSON semantics, unlike Python
    assert run(body("return {'a': [1, 2]} == {'a': [1, 2]}")).result is True
    assert run(body("return [1] != [1, 2]")).result is True


def test_comprehension_variables_do_not_leak():
    err = failure(body("x = [t for t in tasks]", "return t"))
    assert err.code == "RUNTIME_ERROR" and "not defined" in err.message


def test_item_assignment_on_dict_and_list():
    r = run(body("d = {'a': 1}", "d['b'] = 2", "l = [0, 0]", "l[1] = d", "return l")).result
    assert r == [0, {"a": 1, "b": 2}]


def test_missing_return_yields_none():
    assert run(body("x = 1")).result is None


@pytest.mark.parametrize("source,fragment", [
    (body("return y"), "not defined"),
    (body("return tasks[0]['nope']"), "not found"),
    (body("return tasks[5]"), "out of range"),
    (body("return tasks['a']"), "integers"),
    (body("return task_id[0]"), "cannot be subscripted"),
    (body("for k in tasks[0]:", "    x = k", "return 1"), "only iterate over a list"),
    (body("return [t for t in task_id]"), "only iterate over a list"),
    (body("return {1: 2}"), "keys must be strings"),
    (body("return 1 in 2"), "not supported"),
    (body("x = 1", "x[0] = 2", "return x"), "item assignment"),
])
def test_runtime_errors_are_bounded_candidate_errors(source, fragment):
    err = failure(source)
    assert err.code == "RUNTIME_ERROR" and fragment in err.message


# ------------------------------------------------------------------ limits
def test_operation_limit_is_enforced_at_5000():
    wide = ", ".join(["t"] * 60)
    tasks = [{"id": f"T{i:03d}", "title": "x", "completed": False} for i in range(100)]
    err = failure(body("for t in tasks:", f"    x = [{wide}]", "return 1"), tasks=tasks)
    assert err.code == "OP_LIMIT_EXCEEDED"


def test_operation_limit_is_configurable_and_exact():
    assert failure(fixture("reference_complete.py"), max_ops=5).code == "OP_LIMIT_EXCEEDED"


def test_time_limit_uses_a_monotonic_deadline():
    ticks = iter(range(0, 10_000, 1))
    clock = lambda: next(ticks)  # noqa: E731 - each check advances one "second"
    with pytest.raises(CandidateError) as exc:
        evaluate(validate_source(fixture("reference_complete.py")), copy.deepcopy(TASKS), "T003",
                 Limits(max_seconds=2.0), clock=clock)
    assert exc.value.code == "TIME_LIMIT_EXCEEDED"


def test_output_size_is_bounded_even_through_aliasing():
    src = body("a = [tasks, tasks, tasks, tasks, tasks, tasks, tasks, tasks]",
               "b = [a, a, a, a, a, a, a, a]", "c = [b, b, b, b, b, b, b, b]",
               "return {'ok': True, 'code': 'X', 'tasks': c}")
    assert failure(src).code == "OUTPUT_LIMIT_EXCEEDED"


def test_cyclic_values_fail_closed():
    assert failure(body("d = {}", "d['self'] = d", "return d")).code == "OUTPUT_LIMIT_EXCEEDED"
    assert failure(body("d = {}", "d['self'] = d", "return d == d")).code == "OUTPUT_LIMIT_EXCEEDED"


def test_container_growth_is_bounded():
    src = body("d = {}", *[f"d['k{i}'] = {i}" for i in range(6)], "return d")
    assert failure(src, max_container_len=5).code == "OUTPUT_LIMIT_EXCEEDED"
