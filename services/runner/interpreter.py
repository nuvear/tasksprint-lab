"""Tree-walking interpreter for the validated Python subset (Architecture A6).

Design rules:

* Only nodes accepted by ``validator.validate_source`` are evaluated; any other
  node type reaching the evaluator is an internal error (fail closed).
* Values are JSON-shaped: None, bool, int, str, list and dict with str keys.
  Candidate syntax can never resolve a Python attribute or call a Python
  callable: there is no attribute or call node in the grammar, and the
  evaluator itself never uses getattr on candidate-chosen names.
* Variables live in an explicit local dictionary. There are no builtins.
* Subscript get/set, equality, membership and truthiness are implemented here
  (interpreter-owned), each charged against the operation budget, so Python's
  own recursive comparison is never triggered on candidate data.
* Inputs are deep-copied in, results are deep-copied out through a bounded
  walker; cycles and oversized structures fail with OUTPUT_LIMIT_EXCEEDED.
* Every evaluation step costs one operation (limit 5,000) and checks a
  monotonic deadline (limit 2 s). Loops are bounded by the supplied lists.
"""
from __future__ import annotations

import ast
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .validator import ValidatedProgram


@dataclass(frozen=True)
class Limits:
    max_ops: int = 5000
    max_seconds: float = 2.0
    max_container_len: int = 200       # elements in any list / keys in any dict
    max_value_depth: int = 8           # nesting depth of any value walked by the evaluator
    max_output_nodes: int = 4000       # values in the returned structure
    max_output_bytes: int = 64 * 1024  # approximate encoded size of the returned structure


DEFAULT_LIMITS = Limits()


class CandidateError(Exception):
    """Bounded failure of the candidate (not of the runner)."""

    def __init__(self, code: str, message: str, line: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.line = line

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "line": self.line}


class _Return(Exception):
    def __init__(self, value: Any):
        self.value = value


@dataclass
class Outcome:
    result: Any
    ops: int
    elapsed_ms: int


@dataclass
class _Budget:
    limits: Limits
    clock: Callable[[], float]
    ops: int = 0
    deadline: float = field(default=0.0)

    def start(self) -> None:
        self.deadline = self.clock() + self.limits.max_seconds

    def charge(self, node: ast.AST | None = None, n: int = 1) -> None:
        self.ops += n
        if self.ops > self.limits.max_ops:
            raise CandidateError("OP_LIMIT_EXCEEDED", f"more than {self.limits.max_ops} interpreted operations",
                                 getattr(node, "lineno", None))
        if self.clock() > self.deadline:
            raise CandidateError("TIME_LIMIT_EXCEEDED", f"evaluation exceeded {self.limits.max_seconds} s",
                                 getattr(node, "lineno", None))


# ------------------------------------------------------------------ bounded value helpers
_SCALARS = (type(None), bool, int, str)


def _is_scalar(v: Any) -> bool:
    return type(v) in _SCALARS


def bounded_copy(value: Any, limits: Limits, *, what: str = "output") -> Any:
    """Deep copy a JSON-shaped value with node/depth/size limits (cycle-safe by depth)."""
    count = 0
    size = 0

    def walk(v: Any, depth: int) -> Any:
        nonlocal count, size
        count += 1
        if count > limits.max_output_nodes:
            raise CandidateError("OUTPUT_LIMIT_EXCEEDED", f"{what} has more than {limits.max_output_nodes} values")
        if depth > limits.max_value_depth:
            raise CandidateError("OUTPUT_LIMIT_EXCEEDED", f"{what} is nested deeper than {limits.max_value_depth}")
        t = type(v)
        if v is None or t is bool or t is int:
            size += 6
            out = v
        elif t is str:
            size += len(v) + 2
            out = v
        elif t is list:
            size += 2
            out = [walk(x, depth + 1) for x in v]
        elif t is dict:
            size += 2
            out = {}
            for k, x in v.items():
                if type(k) is not str:
                    raise CandidateError("OUTPUT_INVALID", f"{what} contains a non-string key")
                size += len(k) + 3
                out[k] = walk(x, depth + 1)
        else:
            raise CandidateError("OUTPUT_INVALID", f"{what} contains a non-JSON value")
        if size > limits.max_output_bytes:
            raise CandidateError("OUTPUT_LIMIT_EXCEEDED", f"{what} exceeds {limits.max_output_bytes} bytes")
        return out

    return walk(value, 0)


def _type_name(v: Any) -> str:
    return {type(None): "None", bool: "bool", int: "int", str: "str", list: "list", dict: "dict"}.get(type(v), "value")


class Interpreter:
    def __init__(self, program: ValidatedProgram, limits: Limits = DEFAULT_LIMITS,
                 clock: Callable[[], float] = time.monotonic):
        self.fn = program.function
        self.limits = limits
        self.clock = clock

    # -------------------------------------------------------------- entry point
    def run(self, tasks: Any, task_id: Any) -> Outcome:
        budget = _Budget(self.limits, self.clock)
        started = self.clock()
        budget.start()
        env: dict[str, Any] = {
            "tasks": bounded_copy(tasks, self.limits, what="input"),
            "task_id": bounded_copy(task_id, self.limits, what="input"),
        }
        self.budget = budget
        result: Any = None
        try:
            self._block(self.fn.body, env)
        except _Return as ret:
            result = ret.value
        except RecursionError:  # unreachable given the depth limits; fail closed anyway
            raise CandidateError("RUNTIME_ERROR", "evaluation nesting limit reached") from None
        out = bounded_copy(result, self.limits, what="result")
        return Outcome(result=out, ops=budget.ops, elapsed_ms=int((self.clock() - started) * 1000))

    # -------------------------------------------------------------- statements
    def _block(self, body: list[ast.stmt], env: dict[str, Any]) -> None:
        for stmt in body:
            self._stmt(stmt, env)

    def _stmt(self, node: ast.stmt, env: dict[str, Any]) -> None:
        self.budget.charge(node)
        kind = type(node)
        if kind is ast.Return:
            raise _Return(self._expr(node.value, env))
        if kind is ast.Assign:
            value = self._expr(node.value, env)
            target = node.targets[0]
            if type(target) is ast.Name:
                env[target.id] = value
            else:
                container = self._expr(target.value, env)
                key = self._expr(target.slice, env)
                self._set_item(container, key, value, target)
            return
        if kind is ast.If:
            if self._truthy(self._expr(node.test, env)):
                self._block(node.body, env)
            else:
                self._block(node.orelse, env)
            return
        if kind is ast.For:
            seq = self._expr(node.iter, env)
            if type(seq) is not list:
                raise CandidateError("RUNTIME_ERROR", f"for loops may only iterate over a list, not {_type_name(seq)}",
                                     node.lineno)
            for item in list(seq):  # snapshot: the loop length is fixed when it starts
                self.budget.charge(node)
                env[node.target.id] = item
                self._block(node.body, env)
            return
        raise CandidateError("INTERNAL_REJECT", f"unsupported statement {kind.__name__}", getattr(node, "lineno", None))

    # -------------------------------------------------------------- expressions
    def _expr(self, node: ast.expr, env: dict[str, Any]) -> Any:
        self.budget.charge(node)
        kind = type(node)
        if kind is ast.Constant:
            return node.value
        if kind is ast.Name:
            if node.id not in env:
                raise CandidateError("RUNTIME_ERROR", f"name '{node.id}' is not defined", node.lineno)
            return env[node.id]
        if kind is ast.List:
            if len(node.elts) > self.limits.max_container_len:
                raise CandidateError("OUTPUT_LIMIT_EXCEEDED", "list literal too long", node.lineno)
            return [self._expr(e, env) for e in node.elts]
        if kind is ast.Dict:
            out: dict[str, Any] = {}
            for k_node, v_node in zip(node.keys, node.values):
                key = self._expr(k_node, env)
                if type(key) is not str:
                    raise CandidateError("RUNTIME_ERROR", "dictionary keys must be strings", node.lineno)
                out[key] = self._expr(v_node, env)
            if len(out) > self.limits.max_container_len:
                raise CandidateError("OUTPUT_LIMIT_EXCEEDED", "dictionary literal too large", node.lineno)
            return out
        if kind is ast.Subscript:
            return self._get_item(self._expr(node.value, env), self._expr(node.slice, env), node)
        if kind is ast.UnaryOp:  # only Not passes validation
            return not self._truthy(self._expr(node.operand, env))
        if kind is ast.BoolOp:
            is_and = type(node.op) is ast.And
            value: Any = None
            for operand in node.values:
                value = self._expr(operand, env)
                if self._truthy(value) != is_and:
                    return value
            return value
        if kind is ast.Compare:
            left = self._expr(node.left, env)
            right = self._expr(node.comparators[0], env)
            op = type(node.ops[0])
            if op is ast.Eq:
                return self._equal(left, right, 0, node)
            if op is ast.NotEq:
                return not self._equal(left, right, 0, node)
            if op is ast.In:
                return self._contains(right, left, node)
            if op is ast.NotIn:
                return not self._contains(right, left, node)
        if kind is ast.ListComp:
            gen = node.generators[0]
            seq = self._expr(gen.iter, env)
            if type(seq) is not list:
                raise CandidateError("RUNTIME_ERROR", "comprehensions may only iterate over a list", node.lineno)
            local = dict(env)  # comprehension variables do not leak into the function scope
            out_list: list[Any] = []
            for item in list(seq):
                self.budget.charge(node)
                local[gen.target.id] = item
                if all(self._truthy(self._expr(c, local)) for c in gen.ifs):
                    out_list.append(self._expr(node.elt, local))
                    if len(out_list) > self.limits.max_container_len:
                        raise CandidateError("OUTPUT_LIMIT_EXCEEDED", "comprehension result too long", node.lineno)
            return out_list
        raise CandidateError("INTERNAL_REJECT", f"unsupported expression {kind.__name__}", getattr(node, "lineno", None))

    # -------------------------------------------------------------- interpreter-owned operations
    def _get_item(self, container: Any, key: Any, node: ast.AST) -> Any:
        t = type(container)
        if t is dict:
            if type(key) is not str:
                raise CandidateError("RUNTIME_ERROR", "dictionary keys must be strings", node.lineno)
            if key not in container:
                raise CandidateError("RUNTIME_ERROR", f"key '{key[:40]}' not found", node.lineno)
            return container[key]
        if t is list:
            if type(key) is not int:
                raise CandidateError("RUNTIME_ERROR", "list indices must be integers", node.lineno)
            if not -len(container) <= key < len(container):
                raise CandidateError("RUNTIME_ERROR", "list index out of range", node.lineno)
            return container[key]
        raise CandidateError("RUNTIME_ERROR", f"{_type_name(container)} values cannot be subscripted", node.lineno)

    def _set_item(self, container: Any, key: Any, value: Any, node: ast.AST) -> None:
        t = type(container)
        if t is dict:
            if type(key) is not str:
                raise CandidateError("RUNTIME_ERROR", "dictionary keys must be strings", node.lineno)
            if key not in container and len(container) >= self.limits.max_container_len:
                raise CandidateError("OUTPUT_LIMIT_EXCEEDED", "dictionary too large", node.lineno)
            container[key] = value
            return
        if t is list:
            if type(key) is not int:
                raise CandidateError("RUNTIME_ERROR", "list indices must be integers", node.lineno)
            if not -len(container) <= key < len(container):
                raise CandidateError("RUNTIME_ERROR", "list assignment index out of range", node.lineno)
            container[key] = value
            return
        raise CandidateError("RUNTIME_ERROR", f"{_type_name(container)} values do not support item assignment",
                             node.lineno)

    def _truthy(self, v: Any) -> bool:
        t = type(v)
        if v is None:
            return False
        if t is bool:
            return v
        if t is int:
            return v != 0
        if t in (str, list, dict):
            return len(v) > 0
        raise CandidateError("INTERNAL_REJECT", "non-JSON value")

    def _equal(self, a: Any, b: Any, depth: int, node: ast.AST) -> bool:
        self.budget.charge(node)
        if depth > self.limits.max_value_depth:
            raise CandidateError("OUTPUT_LIMIT_EXCEEDED", "compared values are nested too deeply", node.lineno)
        ta, tb = type(a), type(b)
        if ta is not tb:
            return False  # JSON semantics: True != 1, 1 != "1"
        if a is None or ta in (bool, int, str):
            return a == b
        if ta is list:
            return len(a) == len(b) and all(self._equal(x, y, depth + 1, node) for x, y in zip(a, b))
        if ta is dict:
            return a.keys() == b.keys() and all(self._equal(a[k], b[k], depth + 1, node) for k in a)
        raise CandidateError("INTERNAL_REJECT", "non-JSON value")

    def _contains(self, container: Any, item: Any, node: ast.AST) -> bool:
        t = type(container)
        if t is list:
            return any(self._equal(item, x, 0, node) for x in container)
        if t is dict:
            if type(item) is not str:
                raise CandidateError("RUNTIME_ERROR", "dictionary membership needs a string key", node.lineno)
            return item in container
        if t is str:
            if type(item) is not str:
                raise CandidateError("RUNTIME_ERROR", "string membership needs a string", node.lineno)
            self.budget.charge(node, 1 + len(container) // 64)
            return item in container
        raise CandidateError("RUNTIME_ERROR", f"'in' is not supported for {_type_name(container)}", node.lineno)


def evaluate(program: ValidatedProgram, tasks: Any, task_id: Any, limits: Limits = DEFAULT_LIMITS,
             clock: Callable[[], float] = time.monotonic) -> Outcome:
    return Interpreter(program, limits, clock).run(tasks, task_id)
