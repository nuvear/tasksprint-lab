---
name: implement-todo-change
description: Implement or repair one TaskSprint completion-function candidate against an approved story using the bounded Python-subset contract. Use for completion code changes, not release, infrastructure, or test-suite changes.
metadata:
  version: "1.1.0"
  owner: "TaskSprint workshop maintainer"
---
# Implement one to-do change

## Prerequisites
A human-approved story and acceptance criteria; a current base candidate reference;
a permitted developer identity; the published restricted-language contract.
Missing prerequisites cause a needs-human-review result.

## Procedure
1. Read the canonical story and current base source. Record their identifiers.
2. Retrieve the current approved requirement passages relevant to the change.
3. Describe the smallest behavior change. Completion retains the target record;
   it does not delete it or silently modify unrelated task records.
4. Write one `complete(tasks, task_id)` function within the allowed grammar.
   Return JSON-shaped `{ok, code, tasks}`. Do not import, call a function, access
   attributes, execute a shell, or read files, environment variables or a network.
   Allowed: one `for` loop (no nesting, no comprehension inside it), `if/elif/else`,
   `return value`, single-target assignment to a name or `x[key]`, str/int/bool/None
   constants, list and dict literals, subscripts, `==`, `!=`, `in`, `not in`, `and`,
   `or`, `not`, one single-level list comprehension. Not allowed: any call (including
   `len`, `range`, `.append`), attributes, arithmetic or unary minus (no `-1` index),
   `pass`/`break`/`continue`/docstrings, `is`, `<`/`>`. Equality is JSON equality:
   `True != 1`. Limits: 4 KiB source, 256 syntax nodes, 5,000 operations, 2 s.
5. Submit the source with the actual base hash. Record the service-returned candidate
   ID/hash. A new revision creates a new candidate; never overwrite approved bytes.
6. Hand the reference to QA. Do not certify your own candidate as passing.
7. When an immutable QA report identifies a defect, inspect the failed assertion
   and observed data. Make one repair under the harness budget, then return to QA.
8. Return a concise change summary with actual evidence and this skill version.

## Stop and escalate
Stop for absent/conflicting requirements, stale base source, unsupported necessary
syntax, a validator rejection you cannot fix within this grammar, inaccessible tools,
exhausted repair budget, or requests to alter protected tests/approvals/production.
Do not work around a denied capability.

## Verification
A real candidate exists with matching source/hash; requirement citations resolve;
the protected suite evaluates that candidate. Submission alone is not test success.
This procedure grants no additional permissions.
