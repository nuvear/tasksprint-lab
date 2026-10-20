# Candidate grammar for Developer-facing guidance (ts-python-subset/1)

**Status:** reference note written in Phase 04 from the Phase 03 runner code
(`services/runner/validator.py`, `services/runner/interpreter.py`, runner
`tasksprint-runner/0.3.0`). It is **not** served by any MCP tool, is **not** part of
the `knowledge/` corpus, and does **not** change `skills/implement-todo-change/SKILL.md`.
`docs/PHASE04_REPORT.md` proposes the owner-approved way to put a short version of it
into the skill (a new skill version, so the load event records a new hash).

It deliberately contains no complete solution: the instructor reference fixture must
not reach the Developer through documentation either.

## Shape of a candidate

Exactly one function, nothing else in the file (comments are fine):

```text
def complete(tasks, task_id):
    ...
```

* Arguments are exactly `tasks, task_id`: no defaults, `*args`, `**kwargs`,
  keyword-only markers, annotations, decorators or return annotation.
* Return a JSON-shaped dictionary `{"ok": <bool>, "code": <str>, "tasks": <list>}`.
  Each task in `tasks` is `{"id", "title", "completed"}` only.
* Limits: source ≤ 4 KiB, ≤ 256 syntax nodes, nesting depth ≤ 20, string constants
  ≤ 200 characters, integer constants |n| ≤ 10⁹; at run time ≤ 5,000 interpreted
  operations, ≤ 2 s, containers ≤ 200 elements, values nested ≤ 8 deep, result
  ≤ 4,000 values / 64 KiB.

## Allowed

| Construct | Notes |
|---|---|
| `for NAME in expr:` | Single name target, no `else`, no loop inside a loop or inside a comprehension |
| `if` / `elif` / `else` | |
| `return expr` | A bare `return` is rejected |
| `NAME = expr`, `target[key] = expr` | One target per assignment; no `+=`, no tuple unpacking, no chained `a = b = c` |
| Names | Letters, digits, single underscores; must not start with `_`; ≤ 32 characters; may not reference `complete` (no recursion) |
| Constants | `str`, `int`, `True`, `False`, `None`; no string prefixes (`f""`, `b""`, `r""`) and no `__` inside strings |
| Literals | `[a, b]`, `{"k": v}`; no sets, tuples or `**` unpacking |
| Subscript | `x[k]` for reading and assignment; no slices (`x[1:]`) |
| Comparisons | `==`, `!=`, `in`, `not in`, one operator per comparison (no `a == b == c`) |
| Boolean | `and`, `or`, `not` |
| List comprehension | One level: `[e for NAME in expr if cond]`, only outside loops |

## Rejected (everything not listed above), including

* imports, **any function or method call** (`len()`, `range()`, `list.append()`,
  `dict.get()`, `copy()` …), attribute access (`task.id`)
* **unary minus and all arithmetic**: negative numbers and `-1` indexing are impossible
  (write `x[0]` and loop instead of using `x[-1]`); no `+`, `-`, `*`, `%`
* `is`, `is not`, ordering comparisons (`<`, `>`, `<=`, `>=`), conditional expressions
  (`a if c else b`)
* `pass`, `break`, `continue`, docstrings, `while`, `try`/`raise`/`assert`, `with`,
  `lambda`, `class`, nested `def`, `global`/`nonlocal`, `del`, `yield`/`await`,
  walrus `:=`, `*` unpacking, `match`

## Semantics that differ from Python

* **JSON equality.** `True != 1` and `False != 0` (floats cannot occur: only `str`, `int`, `bool`, `None` constants).
  A boolean only equals a boolean; compare with `True`/`False` explicitly.
* Membership (`in`) and truthiness use the same JSON rules, computed by the interpreter.
* Inputs are deep copies; changing `tasks` inside the function never changes stored data.
  The lab only commits a result whose sole change is the target task's `completed`
  going from `false` to `true`; anything else (a dropped, added or retitled task) is
  refused as `CANDIDATE_RESULT_REJECTED`, and QA's protected suite reports it.

## Typical validator answers

`FORBIDDEN_SYNTAX` (unsupported construct, with line), `FORBIDDEN_NAME`,
`BAD_SIGNATURE`, `RECURSION_FORBIDDEN`, `NESTED_ITERATION`, `TOO_MANY_NODES`,
`TOO_DEEP`, `CONSTANT_TOO_LARGE`; at run time `OP_LIMIT_EXCEEDED`,
`TIME_LIMIT_EXCEEDED`, `OUTPUT_LIMIT_EXCEEDED`. A rejection means "rewrite within the
grammar" or, if the behaviour cannot be expressed, stop and return needs-human-review.
