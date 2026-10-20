# Phase 03 report: bounded runner, interpreter and protected application tests (local)

**Date:** 20 October 2026. **Scope:** Phase 03 only, built and tested on the owner's
Linux aarch64 VM. **Gate:** GATE 03 evidence below; stop here for owner review.
**Not touched:** the Langflow instance, Railway, Postgres, `nuvear/langflow-railway`,
and the owner's private `.local/` files and demo database (all Phase 03 manual checks
used fresh temporary credentials and a temporary database, since deleted).
No remote was configured, nothing was pushed, nothing was deployed.

## Repository

| Item | Value |
|---|---|
| Path | `TaskSprint-Langflow/tasksprint-lab/` |
| Branch | `feature/phase-03-runner`, created from `feature/phase-02-lab` (cef6f52) |
| Git in the mounted folder | Works now that deletion is permitted (`git status`, `git commit` ran in place) |
| Toolchain | Same arrangement as Phase 02: uv-managed CPython 3.12.14 and venv under `/tmp/ts/` (`UV_PYTHON_INSTALL_DIR`, `UV_CACHE_DIR`, `UV_PROJECT_ENVIRONMENT`, `TMPDIR`) because the VM session disk has about 23 MB free |

## Files created or changed

```text
services/runner/__init__.py        RUNNER_VERSION tasksprint-runner/0.3.0, GRAMMAR_VERSION ts-python-subset/1
services/runner/validator.py       ast.parse + explicit node allowlist, signature rules, static limits
services/runner/interpreter.py     tree-walking evaluator, interpreter-owned get/set/==/in, budgets
services/runner/main.py            FastAPI runner: /healthz, POST /v1/evaluate, env refusal, non-root check
services/lab/runner_client.py      lab -> runner HTTP client; strict envelope and source-hash checks
services/lab/contract.py           result shape check and the single permitted data change
services/lab/testing.py            protected suite TC-01..TC-06 (replaces the Phase 02 placeholder)
services/lab/app_commands.py       complete via runner + snapshot revision check (Phase 02 shortcut removed)
services/lab/candidates.py         provenance consistency, load_verified, difflib base diffs, base read rule
services/lab/{main,auth,schemas,config,instructor,releases,__init__}.py
                                   test-run routes, load_fixture action, runner settings, version 0.3.0
scripts/check_stack.py             --target local stack check (A13)
scripts/local_init.py              also writes .local/runner.env; --derive-runner-env for older set-ups
Dockerfile.runner, Dockerfile.lab, compose.yaml
tests/unit/test_{validator,interpreter,runner_service,protected_suite,app_complete,candidate_provenance}.py
tests/security/test_runner_{escapes,isolation}.py
tests/integration/test_runner_process.py
tests/conftest.py, tests/unit/test_app_commands.py, tests/security/test_deny_by_default.py (updated)
pyproject.toml (0.3.0), uv.lock (project version line only), .env.example, docs/BUILD_STATUS.md, this file
```

## What was built

**Runner (separate service, A2/A6).** `GET /healthz` (public, no data) and
`POST /v1/evaluate` (bearer `TS_RUNNER_TOKEN`, compared by SHA-256 digest in constant
time). Body: exactly `{source, source_sha256, tasks, task_id}`. The runner re-hashes
the source and refuses a mismatch, validates the task copy (≤100 tasks, exactly
`{id, title, completed}`, title ≤120, ≤32 KiB encoded, body ≤48 KiB), validates the
source, interprets it and returns `{status: ok|rejected|error, result, error, ops,
elapsed_ms, runner_version, grammar_version, source_sha256, limits}`. It has no
database, no file access, no role tokens. Its configuration refuses to start if the
environment contains `TASKSPRINT_DB_PATH`, `TASKSPRINT_ENV_FILE`, `TASKSPRINT_API_BASE`,
any other `TS_*` variable (role tokens, hashes, `TS_A2A_API_KEY`), `LANGFLOW_*`,
`*_API_KEY`, `DATABASE_URL`, `PGPASSWORD` or Railway tokens, and refuses to run as root.

**Grammar (ts-python-subset/1).** Exactly one `def complete(tasks, task_id):` (no
defaults, varargs, kwargs, keyword-only/positional-only markers, annotations,
decorators, type parameters). Statements: `for NAME in expr` (no `else`, no nested
iteration), `if/elif/else`, `return expr`, one-target assignment to a name or a
subscript. Expressions: names, `str`/`int`/`bool`/`None` constants, list and dict
literals, subscripts, `==`, `!=`, `in`, `not in`, `not`, `and`, `or`, and one
single-level list comprehension (one `for`, optional `if`s, not inside a loop).
Everything else is rejected before interpretation, including imports, calls,
attribute access, names starting with `_` (so every dunder), string constants
containing `__`, classes, lambdas, while, try/raise/assert, with, walrus, f-strings,
starred, augmented/annotated assignment, global/nonlocal, del, yield/await, slices,
arithmetic and unary minus, `is`, ordering and chained comparisons, conditional
expressions, sets/tuples/generators/dict comprehensions, nested functions, match,
type aliases, and any reference to `complete` (recursion). Limits enforced in code:
source ≤4 KiB, ≤256 AST nodes, depth ≤20, string constant ≤200, |int| ≤10⁹.

**Interpreter.** Explicit local environment (only `tasks`, `task_id` and assigned
names; no builtins). Interpreter-owned subscript get/set, JSON equality (`True != 1`),
membership and truthiness, each charged to the budget, so Python's own recursive
comparison never runs on candidate data. Every step costs one operation; limit
5,000 operations and a 2 s monotonic deadline checked on every operation. Containers
≤200 elements; values walked to depth ≤8; results copied out through a bounded
walker (≤4,000 values, ≤64 KiB), which also stops cycles and exponential aliasing.
Inputs are deep-copied in and results deep-copied out.

**Lab.** `complete <ID>` resolves the active artifact by hash, re-verifies the bytes
and provenance, snapshots task records and revisions, and sends the source and a copy
of the records to the runner with no lock held. The runner's answer is data. The lab
accepts only a well-formed result whose sole change is the target's `completed`
false→true (nothing added, dropped, retitled; `ok` must agree with the data). It
commits only if the active release (hash and revision), any drill, and every task
revision are unchanged since the snapshot; otherwise `409 REVISION_CONFLICT` and
nothing is written. Outcomes: `COMPLETED`, already complete (no change),
`TASK_NOT_FOUND`, `FEATURE_UNAVAILABLE`, `CANDIDATE_REJECTED` (validator),
`CANDIDATE_FAILED` (limit or runtime error), `CANDIDATE_RESULT_INVALID`,
`CANDIDATE_RESULT_REJECTED`, `RUNNER_UNAVAILABLE`. Every response carries the
runner version, op count and the hash actually interpreted. The Phase 02
hash-match shortcut for v0 is gone: v0 now returns FEATURE_UNAVAILABLE because its
source is interpreted and returns that.

**Protected suite** (`services/lab/testing.py`, run only by trusted lab code). QA may
only name a candidate (`POST /v1/test-runs {candidate_id}`); any other field is a 422.
Each case sends a fresh copy of a fixed synthetic list (T001 open, T002 open, T003
done), never canonical tasks:

| Case | Acceptance | Assertions |
|---|---|---|
| TC-01 | APP-01 | complete T001: ok, COMPLETED, T001 present, title unchanged, completed=true |
| TC-02 | APP-02 | complete T002: count unchanged, all IDs retained, T001/T003 identical, T002 completed |
| TC-03 | APP-03 | complete T003 (already done): records identical, ok; re-applying to TC-01 output changes nothing |
| TC-04 | APP-04 | unknown T999: ok=false, TASK_NOT_FOUND, records identical |
| TC-05 | contract | results for T001 and T999 are exactly `{ok, code, tasks[{id, title, completed}]}` |
| TC-06 | contract | the lab-held input copy is unchanged; identical input gives identical result |

The report goes append-only into `test_runs` (UPDATE/DELETE triggers abort) with the
candidate hash, `suite_sha256` = SHA-256 of `testing.py` itself
(`051dfb587a095260d0147f0838f4707bcf81a6244d01198938a8daccf71a9551` at this commit),
runner version, per-evaluation evidence IDs (input/result digests, status, ops),
pass/fail counts and a fixture label when the candidate is a fixture. Outcome `error`
(never `pass`) when the runner is unavailable. `GET /v1/test-runs/{id}`: qa,
operations, coordinator; everyone else 403.

**Candidates.** Every load re-hashes the bytes and checks provenance consistency
(origin vs author role: fixtures by instructor, agent-generated by developer; recorded
size). A base hash must name a candidate the submitting role may read; a reference
fixture or an unselected faulty fixture gets the same `UNKNOWN_BASE` as a missing one
(no existence oracle, no diff leak). Reads add `provenance` and a `difflib` unified
diff against the base, withheld (`BASE_NOT_READABLE`) when the reader may not see the
base. Developer reads of `fixture-reference` stay 403. Identical source returns the
existing record (`created: false`); nothing is ever overwritten.

**Instructor `load_fixture`.** Allowlisted names `faulty_delete` and
`reference_complete` only, registered with fixed provenance (`fixture-faulty`,
`fixture-reference`) and labels beginning `FIXTURE:`; idempotent; instructor only.

## Commands and actual results

Run in the repository folder on the owner VM, 20 Oct 2026 (UTC):

```text
$ git switch -c feature/phase-03-runner                  Switched to a new branch (from cef6f52)
$ uv sync --frozen                                        Checked 22 packages        exit 0
$ uv run pytest -q tests/unit tests/security              (Phase 02 baseline, before changes) 112 passed in 2.28s

$ uv run pytest -q tests/unit tests/security tests/integration     (04:56Z)
345 passed in 5.90s
$ uv run pytest -q tests/unit          245 passed in 2.22s
$ uv run pytest -q tests/security       90 passed in 1.41s
$ uv run pytest -q tests/integration    10 passed in 1.86s   (1 Phase 02 restart + 9 runner-process tests)
0 failed, 0 skipped.
Re-run after the pyproject/lock/docs changes (04:59Z): 345 passed in 5.68s.

$ uv lock --offline                    Updated tasksprint-lab v0.2.0 -> v0.3.0 (no dependency changes)
$ uv lock --check --offline            Resolved 24 packages                       exit 0
```

Manual end-to-end check: two real processes with fresh temporary credentials
(`local_init.py --dir <tmp>/.local`), runner on 127.0.0.1:18001 with only `PATH`,
`LANG`, `TS_RUNNER_TOKEN`; lab on 127.0.0.1:18000 with `TASKSPRINT_RUNNER_URL`:

```text
local_init: Created <tmp>/.local/runner.env (mode 0600): TS_RUNNER_TOKEN only
seed 200
$ check_stack.py --target local --lab-url http://127.0.0.1:18000 --runner-probe 127.0.0.1:18002 -> exit 0
PASS lab liveness: GET /healthz -> 200
PASS runner not exposed to host: 127.0.0.1:18002 refused/unreachable
PASS unauthenticated request refused: -> 401
PASS application status: -> 200, business health healthy
PASS lab -> runner path: -> 200, code FEATURE_UNAVAILABLE, runner tasksprint-runner/0.3.0, ops 8
$ check_stack.py ... --runner-probe 127.0.0.1:18001  (the runner's real local port)          -> exit 1
FAIL runner not exposed to host: 127.0.0.1:18001 accepted a TCP connection
v0 complete T001 -> FEATURE_UNAVAILABLE | evaluated_by tasksprint-runner/0.3.0 ops 8 interpreted 561149e5c98b
loaded faulty_delete      cand_93db211887e2c21a2fd638d4 fixture-faulty    | FIXTURE: known faulty (deletes the completed task)
loaded reference_complete cand_6316e2ce3c940084e43efbe4 fixture-reference | FIXTURE: instructor-only reference
test-run starter_v0:  outcome=fail failed_cases=[TC-01, TC-02, TC-03, TC-04] assertions passed 21 / failed 6
test-run faulty:      outcome=fail failed_cases=[TC-01, TC-02, TC-03, TC-04] assertions passed 18 / failed 6
   TC-02 failing: ('task count unchanged', 3, 2), ('all task ids retained', [T001,T002,T003], [T001,T003])
test-run reference:   outcome=pass failed_cases=[] assertions passed 27 / failed 0
   (all three: runner tasksprint-runner/0.3.0, suite 051dfb587a09…, 10 evidence IDs)
developer GET reference -> 403 SOURCE_NOT_PERMITTED;  developer POST /v1/test-runs -> 403
runner without token -> 401;  runner process env names: ['LANG', 'PATH', 'TS_RUNNER_TOKEN']
```

The first `check_stack` run's "runner not exposed" PASS only shows that nothing listens
on an unused port. It is **not** evidence of Compose isolation; the second run shows the
check does detect a reachable runner. Fixture hashes match the kit `SHA256SUMS.txt`.

## Gate 03 mapping

| Gate 03 requirement | Evidence | Status |
|---|---|---|
| v0, faulty and reference sources produce their actual different behaviour | `test_interpreter.py` fixture tests; `test_protected_suite.py`; manual run above | TESTED |
| Faulty fails retention/unknown-ID; reference passes | TC-02 and TC-04 fail for faulty, all pass for reference (unit, integration, manual) | TESTED |
| Reports from actual assertions; no model PASS, suite edit, overwrite | Only `{candidate_id}` accepted; suite hash = module bytes; `test_runs` append-only; QA/others cannot write | TESTED |
| Forbidden syntax and resource exhaustion rejected | 80-row reject matrix; 27 escape attempts via HTTP; op limit, time limit, output/cycle limits | TESTED |
| Runner cannot modify task data directly | Runner has no DB; a tampered runner answer is refused (`CANDIDATE_RESULT_REJECTED`); faulty result never committed | TESTED |
| Runner has no production credentials/DB access | Env refusal tests; live `/proc/<pid>/environ` and open-file checks on the runner process; image/Compose static checks | TESTED (process level) |
| Developer cannot read reference source | 403 by ID, refused as a diff base, never in reports | TESTED |
| `docker compose up --build -d`, `check_stack.py --target local` against Compose | Docker not installed | **BLOCKED** |

## Deviations and clarifications

1. **Parsing uses `ast.parse`.** CPython implements it via `compile(..., PyCF_ONLY_AST)`,
   which builds a syntax tree only; no code object is produced or run. The repository's
   static scan for `exec`/`eval`/`compile(`/`importlib`/`pickle`/`subprocess` in
   `services/` still passes, including the runner.
2. **Grammar beyond the three fixtures.** `not in` (the negated form of the listed `in`)
   and `elif`/`else` (part of `if`). Nothing else. Consequences worth knowing for the
   Developer skill: negative numbers and `-1` indexing are impossible (unary minus is
   rejected), `pass`/`break`/`continue`/docstrings are rejected, and equality is JSON
   equality (`True != 1`), unlike Python.
3. **The live app never applies a destructive result.** Only target completed false→true
   can be committed. If the faulty fixture were ever active, `complete` returns
   `CANDIDATE_RESULT_REJECTED` and nothing is deleted. The deletion is shown in QA's
   isolated test copies, which is where the story catches it. If the workshop needs the
   live app to visibly lose a task, that is a design change to decide explicitly.
4. **Two processes, not containers.** Without Docker, separation was proven with two OS
   processes: separate PIDs and ports, the runner's environment contains only `PATH`,
   `LANG` and `TS_RUNNER_TOKEN`, it holds no open DB file, and it refuses to start when
   given lab secrets. Missing on this VM: network isolation (the local runner port is
   reachable from the host; egress is not blocked), read-only filesystem, separate OS
   user (both ran as the owner's VM user). The runner's code has no file or DB access,
   but OS-level isolation is exactly what Compose/Railway must add.
5. **Time limit** is a monotonic deadline checked on every interpreted operation inside the
   runner, not process preemption. Single operations are bounded by the data limits.
6. **Images not built.** `Dockerfile.*` use `python:3.12-slim` and
   `ghcr.io/astral-sh/uv:0.12.13`, neither verified nor digest-pinned. Phase 05 must
   build, pin and test them.
7. **Activating non-v0 candidates in tests** uses a trusted test-only pointer change
   (`Lab.activate` in `tests/conftest.py`). No deploy path exists until Phase 09.
8. **`load_fixture`** was added now (A12 lists it for the instructor); drills, stop and the
   confirmed reset remain later phases.
9. **Report contents.** Reports show expected/actual values for failing assertions (defect
   evidence for AE-03) and are readable by qa, operations and coordinator. They never
   contain candidate or grader source.
10. **Runner input IDs** are restricted to `[A-Za-z0-9_-]{1,32}`.
11. **Owner's `.local/` was not changed.** It still has no `runner.env`. Phase 03 manual checks
    used temporary credentials and a temporary database (deleted afterwards), so the
    seeded `demo-001` database from Phase 02 is unchanged.

## BLOCKED and not run

| Item | Reason |
|---|---|
| `docker compose up --build -d` | Docker not installed on the owner VM |
| `check_stack.py --target local` against the Compose stack | Same; run only against two local processes (above) |
| Image build, non-root container user, read-only root FS, internal network | Written in `Dockerfile.*`/`compose.yaml`, statically checked only |

## Manual (human) equivalent

1. `git switch -c feature/phase-03-runner` from the Phase 02 branch.
2. Write `services/runner/validator.py` (parse with `ast.parse`, walk every node, allow only
   the grammar above, enforce the limits), `interpreter.py` (evaluate each allowed node
   with your own get/set/equality/membership and an op counter plus deadline) and
   `main.py` (token check, request validation, env refusal). Never call `exec`/`eval`.
3. Add `services/lab/runner_client.py`, `contract.py` and `testing.py`; change `complete`
   to call the runner and commit only the permitted change with a revision check.
4. `uv sync --frozen`; `uv run pytest -q tests/unit tests/security tests/integration`.
5. For an existing set-up: `uv run python scripts/local_init.py --derive-runner-env`
   (creates `.local/runner.env` with only the transport token; prints no value).
6. Start the runner in its own terminal with a clean environment holding only its token
   (the value is read from the file, never typed or placed on a command line):
   `env -i PATH="$PATH" HOME="$HOME" LANG=C.UTF-8 bash -c 'set -a; . .local/runner.env; set +a; exec uv run uvicorn --factory services.runner.main:create_app --port 8001 --workers 1'`
   The runner refuses to start if lab or platform variables are present.
7. Start the lab: `TASKSPRINT_ENV_FILE=.local/lab.env TASKSPRINT_RUNNER_URL=http://127.0.0.1:8001 uv run uvicorn --factory services.lab.main:create_app --port 8000 --workers 1`.
8. As the application: `complete T001` returns FEATURE_UNAVAILABLE with `evaluation.evaluated_by`.
9. As the instructor: `{"action":"load_fixture","workspace_id":"demo-001","fixture":"faulty_delete"}`
   and `reference_complete`. As QA: `POST /v1/test-runs {"candidate_id": ...}` for each;
   expect faulty `fail` (TC-02 retention), reference `pass`. Read with
   `GET /v1/test-runs/{id}` as operations.
10. `uv run python scripts/check_stack.py --target local --runner-probe 127.0.0.1:<unused>`
    (with Compose, keep the default `127.0.0.1:8001`, which must refuse).
11. On a machine with Docker: `docker compose up --build -d`, then
    `uv run python scripts/check_stack.py --target local`.

## Next action

Owner reviews `git log --oneline feature/phase-02-lab..feature/phase-03-runner` and this
report. To clear the BLOCKED item, on a Docker host (for example the Mac): run
`uv run python scripts/local_init.py --derive-runner-env`, then `docker compose up
--build -d` and `uv run python scripts/check_stack.py --target local`, and record the
result. Then paste **Card 04** (MCP, RAG and on-demand skills). Phase 04's Developer skill
should document the grammar limits in deviation 2.
