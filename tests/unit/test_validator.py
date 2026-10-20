"""Grammar accept/reject matrix for the candidate validator (Architecture A6, SEC-11)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from services.runner.validator import ALLOWED_NODES, MAX_AST_NODES, ValidationRejected, validate_source

REPO = Path(__file__).resolve().parents[2]
FIXTURES = ("starter_v0.py", "faulty_delete.py", "reference_complete.py")
HEAD = "def complete(tasks, task_id):\n"


def body(*lines: str) -> str:
    return HEAD + "".join(f"    {line}\n" for line in lines)


def rejected(source: str) -> ValidationRejected:
    with pytest.raises(ValidationRejected) as exc:
        validate_source(source)
    return exc.value


def test_allowlist_is_exactly_the_documented_grammar():
    expected = {ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.For, ast.If, ast.Return, ast.Assign,
                ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Dict, ast.Subscript, ast.Compare,
                ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
                ast.ListComp, ast.comprehension}
    assert set(ALLOWED_NODES) == expected


@pytest.mark.parametrize("name", FIXTURES)
def test_all_three_fixtures_validate(name):
    prog = validate_source((REPO / "instructor" / "fixtures" / name).read_text())
    assert prog.function.name == "complete" and prog.node_count <= MAX_AST_NODES


@pytest.mark.parametrize("source", [
    body("if task_id == 'T001':", "    return 1", "elif task_id != 'T002':", "    return 2", "else:", "    return 3"),
    body("x = {'ok': True, 'code': 'X', 'tasks': tasks}", "return x"),
    body("ids = [t['id'] for t in tasks if not t['completed']]", "return ids"),
    body("found = task_id in [t['id'] for t in tasks]", "return found and task_id not in ['T999'] or None"),
    body("tasks[0] = {'id': 'a', 'title': 'b', 'completed': False}", "return tasks[0]"),
    body("for t in tasks:", "    if t['id'] == task_id and not t['completed']:", "        t['completed'] = True",
         "return {'ok': True, 'code': 'COMPLETED', 'tasks': tasks}"),
])
def test_accepts_the_allowed_grammar(source):
    validate_source(source)


REJECT_MATRIX = [
    # (label, source, expected code)
    ("import", body("import os", "return 1"), "FORBIDDEN_SYNTAX"),
    ("import-from", body("from os import path", "return 1"), "FORBIDDEN_SYNTAX"),
    ("module-level import", "import os\n" + body("return 1"), "BAD_SIGNATURE"),
    ("call", body("return len(tasks)"), "FORBIDDEN_SYNTAX"),
    ("call open", body("return open('/etc/passwd')"), "FORBIDDEN_SYNTAX"),
    ("attribute", body("return tasks.copy"), "FORBIDDEN_SYNTAX"),
    ("dunder name", body("__x = 1", "return __x"), "FORBIDDEN_NAME"),
    ("underscore name", body("_x = 1", "return _x"), "FORBIDDEN_NAME"),
    ("builtins name", body("return __builtins__"), "FORBIDDEN_NAME"),
    ("inner dunder", body("a__b = 1", "return a__b"), "FORBIDDEN_NAME"),
    ("dunder string", body("return tasks['__class__']"), "FORBIDDEN_NAME"),
    ("class", body("class A:", "    pass", "return 1"), "FORBIDDEN_SYNTAX"),
    ("lambda", body("f = lambda: 1", "return f"), "FORBIDDEN_SYNTAX"),
    ("decorator", "@staticmethod\n" + body("return 1"), "FORBIDDEN_SYNTAX"),
    ("while", body("while True:", "    return 1"), "FORBIDDEN_SYNTAX"),
    ("try", body("try:", "    return 1", "except Exception:", "    return 2"), "FORBIDDEN_SYNTAX"),
    ("raise", body("raise ValueError"), "FORBIDDEN_SYNTAX"),
    ("assert", body("assert tasks", "return 1"), "FORBIDDEN_SYNTAX"),
    ("with", body("with tasks:", "    return 1"), "FORBIDDEN_SYNTAX"),
    ("walrus", body("if (x := tasks):", "    return x", "return 1"), "FORBIDDEN_SYNTAX"),
    ("f-string", body("return f'{task_id}'"), "FORBIDDEN_SYNTAX"),
    ("starred", body("x = [*tasks]", "return x"), "FORBIDDEN_SYNTAX"),
    ("augmented assignment", body("x = 1", "x += 1", "return x"), "FORBIDDEN_SYNTAX"),
    ("annotated assignment", body("x: int = 1", "return x"), "FORBIDDEN_SYNTAX"),
    ("global", body("global tasks", "return 1"), "FORBIDDEN_SYNTAX"),
    ("nonlocal", body("nonlocal tasks", "return 1"), "FORBIDDEN_SYNTAX"),
    ("del", body("del tasks", "return 1"), "FORBIDDEN_SYNTAX"),
    ("yield", body("yield 1"), "FORBIDDEN_SYNTAX"),
    ("generator expression", body("return (t for t in tasks)"), "FORBIDDEN_SYNTAX"),
    ("set literal", body("return {1}"), "FORBIDDEN_SYNTAX"),
    ("set comprehension", body("return {t for t in tasks}"), "FORBIDDEN_SYNTAX"),
    ("dict comprehension", body("return {t: t for t in tasks}"), "FORBIDDEN_SYNTAX"),
    ("tuple", body("return (1, 2)"), "FORBIDDEN_SYNTAX"),
    ("tuple target", body("for a, b in tasks:", "    return a", "return 1"), "FORBIDDEN_SYNTAX"),
    ("slice", body("return tasks[0:1]"), "FORBIDDEN_SYNTAX"),
    ("arithmetic", body("return 1 + 1"), "FORBIDDEN_SYNTAX"),
    ("unary minus", body("return -1"), "FORBIDDEN_SYNTAX"),
    ("is", body("return task_id is None"), "FORBIDDEN_SYNTAX"),
    ("ordering", body("return 1 < 2"), "FORBIDDEN_SYNTAX"),
    ("chained comparison", body("return 1 == 1 == 1"), "FORBIDDEN_SYNTAX"),
    ("conditional expression", body("return 1 if tasks else 2"), "FORBIDDEN_SYNTAX"),
    ("expression statement", body("'docstring'", "return 1"), "FORBIDDEN_SYNTAX"),
    ("pass", body("pass", "return 1"), "FORBIDDEN_SYNTAX"),
    ("break", body("for t in tasks:", "    break", "return 1"), "FORBIDDEN_SYNTAX"),
    ("continue", body("for t in tasks:", "    continue", "return 1"), "FORBIDDEN_SYNTAX"),
    ("for-else", body("for t in tasks:", "    x = 1", "else:", "    x = 2", "return 1"), "FORBIDDEN_SYNTAX"),
    ("nested for", body("for a in tasks:", "    for b in tasks:", "        x = 1", "return 1"), "NESTED_ITERATION"),
    ("comprehension in loop", body("for a in tasks:", "    x = [b for b in tasks]", "return 1"), "NESTED_ITERATION"),
    ("nested comprehension", body("return [a for a in [b for b in tasks]]"), "NESTED_ITERATION"),
    ("two for clauses", body("return [a for a in tasks for b in tasks]"), "NESTED_ITERATION"),
    ("chained assignment", body("a = b = 1", "return a"), "FORBIDDEN_SYNTAX"),
    ("attribute target", body("tasks.x = 1", "return 1"), "FORBIDDEN_SYNTAX"),
    ("bare return", body("return"), "FORBIDDEN_SYNTAX"),
    ("float", body("return 1.5"), "FORBIDDEN_SYNTAX"),
    ("bytes", body("return b'x'"), "FORBIDDEN_SYNTAX"),
    ("ellipsis", body("return ..."), "FORBIDDEN_SYNTAX"),
    ("huge int", body("return 10000000000"), "CONSTANT_TOO_LARGE"),
    ("long string", body("return '" + "x" * 201 + "'"), "CONSTANT_TOO_LARGE"),
    ("dict unpacking", body("return {**tasks}"), "FORBIDDEN_SYNTAX"),
    ("nested function", body("def inner(a, b):", "    return 1", "return 1"), "FORBIDDEN_SYNTAX"),
    ("self reference (recursion)", body("x = complete", "return x"), "RECURSION_FORBIDDEN"),
    ("recursive call", body("return complete(tasks, task_id)"), "FORBIDDEN_SYNTAX"),
    ("match", body("match task_id:", "    case 'a':", "        return 1", "return 2"), "FORBIDDEN_SYNTAX"),
    ("type alias", body("type X = int", "return 1"), "FORBIDDEN_SYNTAX"),
    ("await", "async " + body("return 1"), "BAD_SIGNATURE"),
    ("default argument", "def complete(tasks, task_id=None):\n    return 1\n", "BAD_SIGNATURE"),
    ("varargs", "def complete(tasks, *task_id):\n    return 1\n", "BAD_SIGNATURE"),
    ("kwargs", "def complete(tasks, task_id, **kw):\n    return 1\n", "BAD_SIGNATURE"),
    ("keyword-only", "def complete(tasks, *, task_id):\n    return 1\n", "BAD_SIGNATURE"),
    ("positional-only", "def complete(tasks, task_id, /):\n    return 1\n", "BAD_SIGNATURE"),
    ("annotation", "def complete(tasks: list, task_id):\n    return 1\n", "FORBIDDEN_SYNTAX"),
    ("return annotation", "def complete(tasks, task_id) -> dict:\n    return 1\n", "FORBIDDEN_SYNTAX"),
    ("type params", "def complete[T](tasks, task_id):\n    return 1\n", "FORBIDDEN_SYNTAX"),
    ("wrong argument names", "def complete(items, task_id):\n    return 1\n", "BAD_SIGNATURE"),
    ("wrong function name", "def finish(tasks, task_id):\n    return 1\n", "BAD_SIGNATURE"),
    ("two functions", body("return 1") + body("return 2"), "BAD_SIGNATURE"),
    ("module statement", "x = 1\n" + body("return 1"), "BAD_SIGNATURE"),
    ("empty", "", "SOURCE_TOO_LARGE"),
    ("syntax error", body("return ("), "SYNTAX_ERROR"),
    ("null byte", body("return 1") + "\x00", "SYNTAX_ERROR"),
]


@pytest.mark.parametrize("label,source,code", REJECT_MATRIX, ids=[r[0] for r in REJECT_MATRIX])
def test_rejects_everything_outside_the_grammar(label, source, code):
    assert rejected(source).code == code


def test_source_size_limit():
    big = body("x = 1") + "#" + "x" * 4096 + "\n"
    assert rejected(big).code == "SOURCE_TOO_LARGE"


def test_node_count_limit():
    elements = ", ".join(["1"] * 300)
    assert rejected(body(f"return [{elements}]")).code == "TOO_MANY_NODES"


def test_depth_limit():
    assert rejected(body("return " + "not " * 25 + "tasks")).code == "TOO_DEEP"
    nested = body("return " + "[" * 30 + "1" + "]" * 30)
    assert rejected(nested).code in ("TOO_DEEP", "SYNTAX_ERROR")


def test_rejection_reports_a_line_number():
    err = rejected(body("x = 1", "return len(x)"))
    assert err.line == 3 and "Call" in err.message
