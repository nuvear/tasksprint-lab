"""Static validation of candidate source (Architecture A6).

The source is parsed with ``ast.parse`` (which only builds a syntax tree; no
bytecode is produced and nothing is executed). Every node is then checked
against an explicit allowlist. Anything not listed is rejected before the
interpreter sees it. The allowlist is the grammar needed by the three supplied
fixtures (starter_v0, faulty_delete, reference_complete), plus ``not in`` as the
negated form of the allowed ``in`` operator. Nothing else.

Grammar (ts-python-subset/1):

    module      := exactly one  ``def complete(tasks, task_id):``  (no defaults,
                   varargs, kwargs, keyword-only args, annotations, decorators,
                   return annotation or type parameters)
    statement   := ``for NAME in expr:`` body (no ``else``; no nested iteration)
                 | ``if expr:`` body [``elif`` ...] [``else:`` body]
                 | ``return expr``
                 | ``NAME = expr``  |  ``target[expr] = expr``  (one target)
    expr        := NAME | constant (str, int, bool, None) | [expr, ...]
                 | {expr: expr, ...} | expr[expr] | ``not`` expr
                 | expr ``and``/``or`` expr | expr (== | != | in | not in) expr
                 | [expr for NAME in expr (if expr)*]   (single level)

Rejected (non-exhaustive, because everything unlisted is rejected): imports,
calls, attribute access, names beginning with ``_`` (so all dunders), classes,
lambdas, decorators, while, try/raise, with, walrus, f-strings, starred,
augmented assignment, global/nonlocal, del, yield/await, slices, arithmetic,
``is``, chained comparisons, conditional expressions, sets, tuples, nested
functions, recursion (the function's own name may not be referenced).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

MAX_SOURCE_BYTES = 4096
MAX_AST_NODES = 256
MAX_AST_DEPTH = 20
MAX_STR_CONST = 200
MAX_INT_CONST = 10**9

FUNCTION_NAME = "complete"
ARG_NAMES = ("tasks", "task_id")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_DUNDERISH = re.compile(r"__")

# The complete allowlist of AST node classes. Membership is checked by exact
# type (not isinstance) so subclasses cannot slip through.
ALLOWED_NODES: frozenset[type] = frozenset({
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg,
    ast.For, ast.If, ast.Return, ast.Assign,
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Dict, ast.Subscript,
    ast.Compare, ast.Eq, ast.NotEq, ast.In, ast.NotIn,
    ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
    ast.ListComp, ast.comprehension,
})
ALLOWED_COMPARE_OPS: frozenset[type] = frozenset({ast.Eq, ast.NotEq, ast.In, ast.NotIn})


class ValidationRejected(Exception):
    """The candidate is outside the grammar or the static limits."""

    def __init__(self, code: str, message: str, line: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.line = line

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "line": self.line}


@dataclass(frozen=True)
class ValidatedProgram:
    function: ast.FunctionDef
    node_count: int
    max_depth: int


def _line(node: ast.AST) -> int | None:
    return getattr(node, "lineno", None)


def _reject(code: str, message: str, node: ast.AST | None = None) -> None:
    raise ValidationRejected(code, message, _line(node) if node is not None else None)


def _check_name(name: str, node: ast.AST) -> None:
    if not _NAME.match(name) or _DUNDERISH.search(name):
        _reject("FORBIDDEN_NAME", f"name '{name[:40]}' is not allowed (letters, digits and single underscores only; "
                "no leading underscore, no dunder)", node)
    if name == FUNCTION_NAME:
        _reject("RECURSION_FORBIDDEN", "the function may not refer to itself", node)


def _check_signature(fn: ast.FunctionDef) -> None:
    a = fn.args
    if fn.name != FUNCTION_NAME:
        _reject("BAD_SIGNATURE", f"the only function must be named '{FUNCTION_NAME}'", fn)
    if fn.decorator_list:
        _reject("FORBIDDEN_SYNTAX", "decorators are not allowed", fn)
    if fn.returns is not None or getattr(fn, "type_comment", None):
        _reject("FORBIDDEN_SYNTAX", "annotations are not allowed", fn)
    if getattr(fn, "type_params", None):
        _reject("FORBIDDEN_SYNTAX", "type parameters are not allowed", fn)
    if a.posonlyargs or a.vararg or a.kwonlyargs or a.kw_defaults or a.kwarg or a.defaults:
        _reject("BAD_SIGNATURE", "only 'def complete(tasks, task_id):' is allowed (no defaults, varargs, "
                "keyword-only arguments or kwargs)", fn)
    if tuple(x.arg for x in a.args) != ARG_NAMES:
        _reject("BAD_SIGNATURE", "arguments must be exactly (tasks, task_id)", fn)
    for x in a.args:
        if x.annotation is not None or getattr(x, "type_comment", None):
            _reject("FORBIDDEN_SYNTAX", "annotations are not allowed", x)


class _Checker:
    """Walks the tree once, enforcing the allowlist and structural rules."""

    def __init__(self) -> None:
        self.nodes = 0
        self.max_depth = 0

    def visit(self, node: ast.AST, depth: int, in_loop: bool, in_comp: bool) -> None:
        self.nodes += 1
        if self.nodes > MAX_AST_NODES:
            _reject("TOO_MANY_NODES", f"source has more than {MAX_AST_NODES} syntax nodes", node)
        if depth > MAX_AST_DEPTH:
            _reject("TOO_DEEP", f"syntax nesting deeper than {MAX_AST_DEPTH}", node)
        self.max_depth = max(self.max_depth, depth)
        kind = type(node)
        if kind not in ALLOWED_NODES:
            _reject("FORBIDDEN_SYNTAX", f"{kind.__name__} is not part of the allowed grammar", node)

        if kind is ast.Name:
            _check_name(node.id, node)
        elif kind is ast.Constant:
            v = node.value
            if v is None or type(v) is bool:
                pass
            elif type(v) is int:
                if abs(v) > MAX_INT_CONST:
                    _reject("CONSTANT_TOO_LARGE", "integer constant out of range", node)
            elif type(v) is str:
                if len(v) > MAX_STR_CONST:
                    _reject("CONSTANT_TOO_LARGE", f"string constant longer than {MAX_STR_CONST}", node)
                if _DUNDERISH.search(v):
                    _reject("FORBIDDEN_NAME", "string constants containing '__' are not allowed", node)
            else:
                _reject("FORBIDDEN_SYNTAX", f"constants of type {type(v).__name__} are not allowed", node)
            if getattr(node, "kind", None) is not None:
                _reject("FORBIDDEN_SYNTAX", "string prefixes are not allowed", node)
        elif kind is ast.FunctionDef:
            if depth != 1:
                _reject("FORBIDDEN_SYNTAX", "nested functions are not allowed", node)
        elif kind is ast.For:
            if in_loop or in_comp:
                _reject("NESTED_ITERATION", "nested iteration is not allowed", node)
            if node.orelse:
                _reject("FORBIDDEN_SYNTAX", "for/else is not allowed", node)
            if type(node.target) is not ast.Name:
                _reject("FORBIDDEN_SYNTAX", "a for loop target must be a single name", node.target)
            if getattr(node, "type_comment", None):
                _reject("FORBIDDEN_SYNTAX", "type comments are not allowed", node)
            self.visit(node.target, depth + 1, in_loop, in_comp)
            self.visit(node.iter, depth + 1, in_loop, in_comp)
            for stmt in node.body:
                self.visit(stmt, depth + 1, True, in_comp)
            return
        elif kind is ast.Assign:
            if len(node.targets) != 1:
                _reject("FORBIDDEN_SYNTAX", "chained assignment is not allowed", node)
            target = node.targets[0]
            if type(target) not in (ast.Name, ast.Subscript):
                _reject("FORBIDDEN_SYNTAX", "assignment target must be a name or a subscript", target)
            if getattr(node, "type_comment", None):
                _reject("FORBIDDEN_SYNTAX", "type comments are not allowed", node)
        elif kind is ast.Return:
            if node.value is None:
                _reject("FORBIDDEN_SYNTAX", "return must return a value", node)
        elif kind is ast.Subscript:
            if type(node.slice) is ast.Slice:  # also excluded by the allowlist; explicit for clarity
                _reject("FORBIDDEN_SYNTAX", "slices are not allowed", node)
        elif kind is ast.Compare:
            if len(node.ops) != 1 or len(node.comparators) != 1:
                _reject("FORBIDDEN_SYNTAX", "chained comparisons are not allowed", node)
            if type(node.ops[0]) not in ALLOWED_COMPARE_OPS:
                _reject("FORBIDDEN_SYNTAX", "only ==, !=, in and not in comparisons are allowed", node)
        elif kind is ast.UnaryOp:
            if type(node.op) is not ast.Not:
                _reject("FORBIDDEN_SYNTAX", "only the 'not' unary operator is allowed", node)
        elif kind is ast.Dict:
            if any(k is None for k in node.keys):
                _reject("FORBIDDEN_SYNTAX", "dictionary unpacking is not allowed", node)
        elif kind is ast.ListComp:
            if in_comp or in_loop:
                _reject("NESTED_ITERATION", "list comprehensions cannot be nested or used inside a loop", node)
            if len(node.generators) != 1:
                _reject("NESTED_ITERATION", "a list comprehension may have exactly one 'for' clause", node)
            gen = node.generators[0]
            if gen.is_async:
                _reject("FORBIDDEN_SYNTAX", "async comprehensions are not allowed", node)
            if type(gen.target) is not ast.Name:
                _reject("FORBIDDEN_SYNTAX", "a comprehension target must be a single name", gen.target)
            self.visit(gen, depth + 1, in_loop, True)
            self.visit(node.elt, depth + 1, in_loop, True)
            return
        elif kind is ast.comprehension:
            self.visit(node.target, depth + 1, in_loop, in_comp)
            self.visit(node.iter, depth + 1, in_loop, in_comp)
            for cond in node.ifs:
                self.visit(cond, depth + 1, in_loop, in_comp)
            return

        for child in ast.iter_child_nodes(node):
            self.visit(child, depth + 1, in_loop, in_comp)


def validate_source(source: str) -> ValidatedProgram:
    """Return the validated function definition or raise ValidationRejected."""
    if not isinstance(source, str):
        _reject("SOURCE_INVALID", "source must be text")
    raw = source.encode("utf-8")
    if not 1 <= len(raw) <= MAX_SOURCE_BYTES:
        _reject("SOURCE_TOO_LARGE", f"source must be 1..{MAX_SOURCE_BYTES} bytes")
    try:
        tree = ast.parse(source, filename="<candidate>", mode="exec", type_comments=False)
    except SyntaxError as exc:
        raise ValidationRejected("SYNTAX_ERROR", f"syntax error: {exc.msg}", exc.lineno) from None
    except (ValueError, RecursionError, MemoryError):
        raise ValidationRejected("SYNTAX_ERROR", "source could not be parsed within limits") from None
    if type(tree) is not ast.Module or tree.type_ignores:
        _reject("FORBIDDEN_SYNTAX", "unexpected module structure")
    if len(tree.body) != 1 or type(tree.body[0]) is not ast.FunctionDef:
        _reject("BAD_SIGNATURE", "the source must contain exactly one top-level 'def complete(tasks, task_id):' "
                "and nothing else", tree.body[0] if tree.body else None)
    fn = tree.body[0]
    _check_signature(fn)
    checker = _Checker()
    checker.visit(tree, 0, False, False)
    return ValidatedProgram(function=fn, node_count=checker.nodes, max_depth=checker.max_depth)
