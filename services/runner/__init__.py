"""TaskSprint bounded candidate runner (Architecture A2, A6).

A separate, stateless service. It receives candidate source text plus a bounded
copy of synthetic task records, validates the source against an explicit AST
allowlist and interprets it with a small tree-walking evaluator. It has no
database, no filesystem state, no role tokens and no model or platform keys.
"""

RUNNER_VERSION = "tasksprint-runner/0.3.0"
GRAMMAR_VERSION = "ts-python-subset/1"
