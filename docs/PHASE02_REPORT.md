# Phase 02 report: persistent lab backend and starter to-do app (local)

**Date:** 20 October 2026. **Scope:** Phase 02 only, built and tested on the owner's
Linux aarch64 VM. **Gate:** GATE 02 evidence below; stop here for owner review.
**Not touched:** the Langflow instance, Railway, Postgres, `nuvear/langflow-railway`.
No remote was configured, nothing was pushed, nothing was deployed.

## Repository

| Item | Value |
|---|---|
| Path | `TaskSprint-Langflow/tasksprint-lab/` (sibling of `TaskSprint_Build_Kit/`) |
| Branches | `main`: kit import, unchanged. `feature/phase-02-lab`: Phase 02 work |
| Kit files | All copied unchanged except `.env.example` (extended), `.gitignore` (Phase 02 rules appended) and `docs/BUILD_STATUS.md` (results). `.DS_Store` and the kit's private `.local/` were not copied |
| Private files | `.local/role_tokens.env`, `.local/lab.env`, `.local/tasksprint.sqlite3` (all ignored, 0600) |

## Files created

```text
pyproject.toml, uv.lock, .python-version          Python 3.12 project, locked deps
services/__init__.py
services/lab/__init__.py                          service version
services/lab/config.py                            settings, role->hash variables, fixed run budgets
services/lab/clock.py                             single UTC time source (test-controllable)
services/lab/auth.py                              token hashing, constant-time auth, PERMISSIONS table
services/lab/audit.py                             redaction, request IDs, append-only events
services/lab/store.py                             migrations (v1), A5 tables, triggers, single writer
services/lab/state.py                             sprint stage machine, StateWriter, revisions
services/lab/memory.py                            allowlisted, scoped, expiring preferences
services/lab/candidates.py                        immutable SHA-256 artifacts, provenance, read policy
services/lab/releases.py                          seed release, active-artifact resolution, app health
services/lab/runs.py                              server-issued run contexts and budgets
services/lab/instructor.py                        seed and reset_preview
services/lab/app_commands.py                      add/list/complete/status grammar and execution
services/lab/schemas.py                           typed request models, unknown fields rejected
services/lab/main.py                              FastAPI app factory, middleware, routes
services/lab/{retrieval,skills,testing,mcp}.py    placeholders naming their phase (03/04)
scripts/local_init.py                             new private credentials, names-only output
scripts/seed_demo.py                              --dry-run (preview) / --apply (seed) demo workspace
tests/conftest.py                                 fake credentials and fixtures
tests/unit/test_{app_commands,candidates,memory,persistence,runs,state_machine}.py
tests/security/test_{deny_by_default,workspace_isolation,role_escalation,redaction_and_limits}.py
tests/integration/test_process_restart.py         real two-process restart (marker: integration)
docs/PHASE02_REPORT.md                            this file
```

## Implemented routes (Phase 02 subset of A8)

All routes except `/healthz` need `Authorization: Bearer <role token>`. Business
routes take the workspace from the `X-TaskSprint-Workspace` header and optionally a
server-issued run from `X-TaskSprint-Run`. A route with no `PERMISSIONS` entry is denied.

| Route | Roles allowed |
|---|---|
| `GET /healthz` | public; returns `{"status":"ok","service":"tasksprint-lab"}` only |
| `POST /v1/runs` | coordinator, product_owner, developer, qa, operations, application |
| `GET /v1/state` | coordinator, product_owner, developer, qa, operations |
| `POST /v1/stories`, `POST /v1/state/transitions` | coordinator |
| `GET`, `POST /v1/memory` | coordinator |
| `GET /v1/candidates/{id}` | developer, qa, operations (reference source never; faulty fixture to developer only once selected) |
| `POST /v1/candidates` | developer (origin always `agent-generated`) |
| `GET /v1/releases`, `GET /v1/app-health` | operations, application |
| `GET /v1/events` | coordinator, qa, operations, instructor, evaluator |
| `POST /v1/app/commands` | application |
| `POST /v1/instructor/actions` (`seed`, `reset_preview`) | instructor |

Sprint stages and legal moves: `PLANNED→IN_DEVELOPMENT` (needs human scope
confirmation) `→IN_QA` (needs an existing candidate) `→CHANGES_REQUESTED | APP_VERIFIED`
(each needs a trusted `test_runs` record with outcome fail/pass for that exact
candidate hash), `CHANGES_REQUESTED→IN_DEVELOPMENT` (one repair, then
REPAIR_BUDGET_EXHAUSTED), `APP_VERIFIED→READY_FOR_REVIEW→CLOSED` (CLOSED needs a
recorded human review, so it is refused until Phase 09).

## Test commands and actual results

Run inside the repository folder on 20 Oct 2026, 04:29-04:31 UTC.

```text
$ uv sync --frozen
 ... + uvicorn==0.54.0                                      exit 0

$ uv run python scripts/local_init.py
Created .../tasksprint-lab/.local/role_tokens.env (mode 0600): TS_COORD_TOKEN, TS_PO_TOKEN,
  TS_DEV_TOKEN, TS_QA_TOKEN, TS_OPS_TOKEN, TS_APP_TOKEN, TS_APPROVER_TOKEN,
  TS_INSTRUCTOR_TOKEN, TS_EVALUATOR_TOKEN
Created .../tasksprint-lab/.local/lab.env (mode 0600): TASKSPRINT_DB_PATH,
  TASKSPRINT_DEMO_ENABLED, TASKSPRINT_ALLOWED_WORKSPACES, TS_RUNNER_TOKEN,
  TS_COORD_TOKEN_HASH ... TS_EVALUATOR_TOKEN_HASH
No secret values were printed. Not generated here: TS_A2A_API_KEY (issued by Langflow in Phase 08).
                                                            exit 0
$ uv run python scripts/local_init.py        # second run
REFUSED: role_tokens.env, lab.env already exist in .../.local; nothing was changed.
                                                            exit 3

$ uv run pytest -q tests/unit tests/security
112 passed in 2.47s                                         (68 unit, 44 security; 0 failed, 0 skipped)

$ uv run pytest -q -m integration tests/integration
1 passed in 1.45s                                           (real uvicorn stop/start on one DB)

$ uv run python scripts/seed_demo.py --workspace demo-001 --dry-run
HTTP 200  {"action": "reset_preview", "exists": false, "mutation": "none"}
$ uv run python scripts/seed_demo.py --workspace demo-001 --apply
HTTP 200  starter cand_561149e5c98bb5b7e8ab7357
          sha256 561149e5c98bb5b7e8ab73579dee2bbd8f680010173ad5d8d4f5dcf89fac1e9b (origin fixture)
          tasks T001, T002; release revision 0
```

The starter hash equals the kit's `SHA256SUMS.txt` entry for `instructor/fixtures/starter_v0.py`.

Manual restart check against the seeded `.local` database, using the generated
tokens read by a script (values not displayed):

```text
process 1 healthz {'status': 'ok', 'service': 'tasksprint-lab'}
no token -> 401          app token on /v1/state -> 403
add -> Added T003: Prepare sprint review
complete T001 -> FEATURE_UNAVAILABLE
memory save -> 201
list (process 1): T001 [ ] Draft workshop agenda / T002 [ ] Book the sprint review room / T003 [ ] Prepare sprint review
process 1 stopped (SIGTERM, exit -15); process 2 started with a new PID
list (process 2): identical -> True
status -> Active artifact cand_561149e5c98bb5b7e8ab7357 sha256=561149e5…fac1e9b | Release revision 0; business health: healthy
state record_type: canonical_sprint_state, stories: 0, release_revision: 0
memory record_type: preference_memory [('release_notes_style', 'concise')]
```

So the demo database now holds T001-T003 and one remembered preference. Leave it
like that, or seed afresh once the confirmed reset exists (later phase).

### Gate 02 mapping

| Gate 02 requirement | Evidence |
|---|---|
| Unauthorized writes fail | `test_deny_by_default.py`: 401 on every business route for missing/invalid/malformed tokens; 403 for every disallowed role on every route; full DB snapshot unchanged |
| add/list persist across restart | `test_persistence.py` (close/reopen) and `test_process_restart.py` plus the manual check (real process restart). APP-08 distinguishes the two; both pass |
| Completion honestly unavailable in starter | `test_complete_on_v0_is_feature_unavailable_and_changes_nothing`; manual check |
| State and memory inspectable separately | `GET /v1/state` (`canonical_sprint_state`) vs `GET /v1/memory` (`preference_memory`); `test_state_and_memory_are_separate_records` |
| Workspace isolation | `test_workspace_isolation.py` (8 tests) |
| Optimistic concurrency | `test_stale_revision_is_a_conflict_and_changes_nothing`, `test_simultaneous_writers_one_wins_no_silent_loss` |
| Role field cannot escalate | `test_role_escalation.py` (13 tests) |

## Manual (human) equivalent

A developer without a coding agent does the same in this order:

1. `git init -b main` a new folder beside the kit; copy the kit files listed above;
   commit; `git switch -c feature/phase-02-lab`.
2. `uv python install 3.12`; write `pyproject.toml` (Python `>=3.12,<3.13`; fastapi,
   pydantic, httpx, uvicorn; pytest dev); `uv lock`; commit `uv.lock`.
3. Write the `services/lab/` modules following Architecture A2–A5 and A8 (see the
   files list), starting with `auth.py` and the deny-by-default policy table.
4. `uv sync --frozen`, then `uv run python scripts/local_init.py`. Open
   `.local/role_tokens.env` only in a private editor when entering values into
   Langflow Credential variables (Phase 06). Never paste them into chat.
5. `uv run python scripts/seed_demo.py --workspace demo-001 --dry-run`, then `--apply`.
6. Start the lab:
   `TASKSPRINT_ENV_FILE=.local/lab.env uv run uvicorn --factory services.lab.main:create_app --port 8000 --workers 1`
7. In another terminal, with the application token in a shell variable you typed
   privately (`read -s TS_APP_TOKEN`), send commands:
   `curl -s -X POST localhost:8000/v1/app/commands -H "Authorization: Bearer $TS_APP_TOKEN" -H "X-TaskSprint-Workspace: demo-001" -H "Content-Type: application/json" -d '{"command":"list"}'`
   Try `add Prepare sprint review`, `complete T001` (expect FEATURE_UNAVAILABLE), `status`.
8. Stop the server (Ctrl-C), start it again, run `list`: records are unchanged.
9. `uv run pytest -q tests/unit tests/security` and `uv run pytest -q -m integration tests/integration`.

## Deviations from the architecture, and clarifications

1. **Extra modules.** `config.py`, `clock.py`, `schemas.py`, `runs.py` and
   `instructor.py` were added beside the A2 module list; `retrieval`, `skills`,
   `testing` and `mcp` exist as placeholders that name their phase.
2. **v0 `complete` without the runner.** No interpreter exists until Phase 03, so
   the backend returns FEATURE_UNAVAILABLE when the active artifact's hash equals the
   workspace's registered starter baseline. That mirrors what `starter_v0.py` returns,
   but it is not yet an interpretation of the source. Any other active artifact gets
   RUNNER_UNAVAILABLE with no mutation. Phase 03 must replace this with the runner's
   computed result.
3. **"10 roles".** A4 lists nine backend identities plus `TS_A2A_API_KEY`. That key is
   issued by Langflow (Phase 08), so `local_init.py` does not generate it. It generates
   nine role tokens plus the transport-only `TS_RUNNER_TOKEN`: ten secrets in total.
4. **Role tokens are lab-wide per role, not per workspace.** Isolation comes from the
   trusted workspace header and run binding: every record is keyed by workspace, a
   run is bound to one role, workspace and generation, and bodies cannot choose a
   workspace. Per-workspace credentials would be a later hardening step.
5. **Scope confirmation and story acceptance** have no route yet. The trusted
   `StateWriter.confirm_scope` exists; the human control (TS-90) wires it later. As a
   result, a story cannot leave PLANNED through the API in Phase 02, and CLOSED is
   always refused (HUMAN_REVIEW_REQUIRED).
6. **Run budgets.** Each authenticated call that carries `X-TaskSprint-Run` counts as
   one action against the fixed budgets (8 per run, 24 per tree, depth 2, 90/180 s).
   Stop flags, no-progress detection and re-checking the run inside the committing
   transaction are Phase 07.
7. **SQLite journal mode** defaults to TRUNCATE (configurable), because the owner's
   mounted folder forbids unlink. Deployment on `/data` may use WAL after testing.
8. **Denial auditing.** Authenticated denials and rejections are written as events in
   their own transaction. Unauthenticated requests are only logged (redacted), so
   anonymous traffic cannot grow the database.
9. **OpenAPI/docs endpoints are disabled.** If Phase 04/06 tooling needs a schema, add
   an authenticated route for it.
10. **Responses are plain JSON objects.** Requests are typed Pydantic models; response
   models can be added when the MCP tool schemas are defined (Phase 04).

## Blockers and environment issues (owner VM)

| Issue | Effect | Handling |
|---|---|---|
| Mounted folder forbids deletion | git cannot commit there (lock/temp files cannot be unlinked); SQLite DELETE/WAL journals fail | Git history built on the VM's local disk and copied in with `.git`. Use git from the Mac, or approve deletion for this folder, before the VM runs git there again. SQLite uses TRUNCATE |
| VM session disk full (23 MB free) | `uv python install` and pytest temp dirs failed under `$HOME` | Used `/tmp` for uv Python/cache/venv (`UV_PYTHON_INSTALL_DIR`, `UV_CACHE_DIR`, `UV_PROJECT_ENVIRONMENT`) and `TMPDIR` for pytest; no `.venv` inside the repo folder |
| Docker not installed | Compose steps (Phase 03/05) cannot run on the VM | Unchanged from Phase 00 |
| `.local/fsprobe/` | Disposable probe files from checking the mount's behaviour (including a scratch git repo with stale locks) | Ignored by git; safe for the owner to delete |
| Starlette 1.9 deprecation notice for `httpx` in TestClient | Cosmetic only | Filtered in pytest config and `seed_demo.py` |

No functional blocker remains for Phase 02.

## Next action

The owner reviews this report and the branch. On a Mac, check with
`git log --oneline main..feature/phase-02-lab`, then `uv sync --frozen` and
`uv run pytest -q tests/unit tests/security`. If accepted, paste **Card 03**
(bounded runner, interpreter and protected application tests). Phase 03 replaces
the starter-baseline shortcut in `complete` with real interpreted results, and it
needs a decision on where to run the separate runner while Docker is unavailable.
