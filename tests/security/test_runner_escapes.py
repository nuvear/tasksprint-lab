"""SEC-11 / SEC-12: escape attempts against the runner are rejected or bounded (Gate 03).

Every attempt goes through the runner's real HTTP route with the transport token,
exactly as the lab calls it. A pass means the validator rejected the source or
the interpreter stopped it within its limits; nothing here executes Python.
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FAKE_RUNNER_TOKEN, runner_app

AUTH = {"Authorization": f"Bearer {FAKE_RUNNER_TOKEN}"}
TASKS = [{"id": f"T{i:03d}", "title": "synthetic", "completed": False} for i in range(1, 101)]
HEAD = "def complete(tasks, task_id):\n"


def body(*lines: str) -> str:
    return HEAD + "".join(f"    {line}\n" for line in lines)


@pytest.fixture(scope="module")
def runner():
    return TestClient(runner_app())


def evaluate(client, source: str, tasks=None, headers=AUTH):
    payload = {"source": source, "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
               "tasks": TASKS[:3] if tasks is None else tasks, "task_id": "T001"}
    return client.post("/v1/evaluate", json=payload, headers=headers)


ESCAPES = [
    ("__class__ attribute", body("return tasks.__class__")),
    ("mro walk", body("return ().__class__.__mro__[1].__subclasses__()")),
    ("open", body("return open('/etc/passwd')")),
    ("getattr", body("return getattr(tasks, 'pop')")),
    ("__import__", body("return __import__('os').system('id')")),
    ("import os", body("import os", "return os.environ")),
    ("builtins", body("return __builtins__")),
    ("globals", body("return globals()")),
    ("exec", body("return exec('1')")),
    ("eval", body("return eval('1')")),
    ("compile", body("return compile('1', 'x', 'exec')")),
    ("format attribute leak", body("return '{0.__class__}'.format(tasks)")),
    ("method call", body("tasks.clear()", "return tasks")),
    ("dunder subscript key", body("return tasks[0]['__class__']")),
    ("lambda", body("f = lambda: tasks", "return f")),
    ("class", body("class X:", "    y = 1", "return 1")),
    ("while", body("while True:", "    x = 1", "return 1")),
    ("try", body("try:", "    x = 1", "finally:", "    x = 2", "return x")),
    ("generator", body("return (t for t in tasks)")),
    ("nested comprehension", body("return [a for a in [b for b in tasks]]")),
    ("nested loop", body("for a in tasks:", "    for b in tasks:", "        x = 1", "return 1")),
    ("deep nesting", body("return " + "not " * 40 + "tasks")),
    ("huge list literal", body("return [" + ", ".join(["1"] * 400) + "]")),
    ("recursion", body("return complete(tasks, task_id)")),
    ("f-string", body("return f'{tasks!r}'")),
    ("walrus", body("return [y := 1]")),
    ("decorator", "@print\n" + body("return 1")),
]


@pytest.mark.parametrize("label,source", ESCAPES, ids=[e[0] for e in ESCAPES])
def test_escape_attempts_are_rejected_before_execution(runner, label, source):
    r = evaluate(runner, source)
    assert r.status_code in (200, 413), r.text
    if r.status_code == 200:
        doc = r.json()
        assert doc["status"] == "rejected", doc
        assert doc["result"] is None and doc["ops"] == 0


def test_loop_beyond_the_operation_limit_is_stopped(runner):
    wide = ", ".join(["t"] * 60)
    doc = evaluate(runner, body("for t in tasks:", f"    x = [{wide}]", "return 1"), tasks=TASKS).json()
    assert doc["status"] == "error" and doc["error"]["code"] == "OP_LIMIT_EXCEEDED" and doc["result"] is None


def test_exponential_output_through_aliasing_is_stopped(runner):
    src = body("a = [tasks, tasks, tasks, tasks]", "b = [a, a, a, a]", "c = [b, b, b, b]", "d = [c, c, c, c]",
               "return d")
    doc = evaluate(runner, src, tasks=TASKS).json()
    assert doc["status"] == "error" and doc["error"]["code"] == "OUTPUT_LIMIT_EXCEEDED"


def test_cycle_is_stopped(runner):
    doc = evaluate(runner, body("d = {}", "d['me'] = d", "return d")).json()
    assert doc["status"] == "error" and doc["error"]["code"] == "OUTPUT_LIMIT_EXCEEDED"


def test_oversized_inputs_are_refused_before_interpretation(runner):
    huge = TASKS + [{"id": "T999", "title": "x", "completed": False}]
    assert evaluate(runner, body("return 1"), tasks=huge).status_code == 413
    assert evaluate(runner, body("x = 1") + "#" * 5000).status_code == 413


@pytest.mark.parametrize("hdrs", [{}, {"Authorization": "Bearer "}, {"Authorization": "Bearer wrong-token-" + "x" * 40},
                                  {"Authorization": FAKE_RUNNER_TOKEN}, {"Authorization": f"Basic {FAKE_RUNNER_TOKEN}"},
                                  {"X-Runner-Token": FAKE_RUNNER_TOKEN}])
def test_runner_rejects_requests_without_the_transport_token(runner, hdrs):
    r = evaluate(runner, body("return 1"), headers=hdrs)
    assert r.status_code == 401 and r.json()["error"]["code"] == "RUNNER_UNAUTHENTICATED"
    assert "result" not in r.json()


def test_lab_role_tokens_are_not_runner_credentials(runner):
    from tests.conftest import FAKE_TOKENS
    for token in FAKE_TOKENS.values():
        assert evaluate(runner, body("return 1"), headers={"Authorization": f"Bearer {token}"}).status_code == 401
