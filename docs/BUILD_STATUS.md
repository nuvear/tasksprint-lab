# Build status

**Last updated:** 20 October 2026, about 05:00 UTC (Phase 03, local build).
**Current gate:** GATE 03 evidence produced locally (Compose step BLOCKED: no Docker);
awaiting owner review. GATE 02 was produced earlier the same day.
Phase 01 (model connection, component templates) is not recorded as complete in
this file; Phase 02 is local-only and does not depend on it.
**Live-instance changes made in Phases 00 and 02:** none. No flows, keys, variables,
providers, MCP servers, Railway variables or deployments were created or changed.
Phases 02 and 03 did not touch Langflow, Railway or `nuvear/langflow-railway`.

## Labels

| Label | Meaning |
|---|---|
| OWNER-REPORTED | Stated by Raj; not measured by this build |
| OBSERVED | Seen in the live UI or a read-only HTTP response on 20 Oct 2026 |
| TESTED | An operation was executed and its result verified |
| BLOCKED | A prerequisite is missing; not bypassed |
| NOT RUN / NOT BUILT | Future phase |

Presence of a route, page or component is recorded as OBSERVED, never as an
integration PASS. Nothing in this file is a protocol-execution result.

## Phase 00 results

| Item | Status | Evidence |
|---|---|---|
| Langflow on Railway, project Langflow, Pro plan, Postgres, volume `/app/langflow`, repo `nuvear/langflow-railway` | OWNER-REPORTED | AGENTS.md environment statement |
| Instance reachable | TESTED | `scripts/preflight.py`: `/health_check` 200 JSON, `/openapi.json` 200 JSON (`.local/preflight/report.json`, 2026-10-20T04:03Z) |
| Version 1.12.5 | OBSERVED | Profile menu "Version 1.12.5 (latest)" (`screenshots/00-02-version-menu.png`); `GET /api/v1/version` returned `{"version":"1.12.5","main_version":"1.12.5","package":"Langflow"}`; OpenAPI `info.version` 1.12.5 |
| Admin session in owner's browser | OBSERVED | Owner logged in privately; no credential seen or handled |
| Flows | OBSERVED: none | Welcome screen "Create first flow" (`screenshots/00-01-welcome.png`) |
| Model Providers | OBSERVED: none configured | 9 providers listed (`screenshots/00-04-settings-model-providers.png`) |
| Global Variables | OBSERVED: 4 present (discrepancy) | `ASTRA_TOKEN`, `COMPONENT_ID`, `FIELD_NAME`, `FLOW_ID`, all Credential, values masked (`screenshots/00-05-settings-global-variables.png`). Owner reported "no globals". Not created by this build; origin unconfirmed (likely Langflow defaults/env-sourced). Left untouched. |
| Langflow API Keys | OBSERVED: none | "No Data Available" (`screenshots/00-06-settings-api-keys.png`) |
| MCP Servers (client side) | OBSERVED: none | "No MCP servers added" (`screenshots/00-07-settings-mcp-servers.png`) |
| Langflow MCP Client (`lfx-mcp`) | OBSERVED | Config with placeholder `YOUR_API_KEY` (`screenshots/00-08-settings-mcp-client.png`); not used |
| Server A2A flag | OBSERVED: **disabled** | Authenticated `GET /api/v1/config` returned `"a2a_enabled": false` |
| A2A routes in schema | OBSERVED (presence only) | `/api/v1/a2a/agents`, `/api/v1/a2a/{flow_id}/.well-known/agent-card.json`, `/api/v1/a2a/{flow_id}/jsonrpc`. Card route documented to 404 while the flag is off. |
| MCP server routes in schema | OBSERVED (presence only) | `/api/v1/mcp/project/{project_id}` (+ `/install`, `/composer-url`, `/installed`), `/api/v2/mcp/servers`, `/api/v2/mcp/servers/{server_name}` |
| HITL routes in schema | OBSERVED (presence only) | `/api/v2/workflows/pending` ("List pending human-input requests"), `/api/v2/workflows/{job_id}/resume` (body `request_id`, `decision`), `/api/v2/workflows/stop` |
| Flow import/export routes | OBSERVED (presence only) | `/api/v1/flows/upload/`, `/api/v1/flows/download/`, `/api/v1/projects/upload/`, `/api/v1/projects/download/{project_id}` |
| Run routes | OBSERVED (presence only) | `/api/v1/run/{flow_id_or_name}` (API-key auth), `/api/v1/run/advanced/...`, `/api/v2/workflows`, `/api/v1/responses` (OpenAI Responses format, API-key auth) |
| Variables / API-key / login routes | UNKNOWN | Not in OpenAPI although UI pages exist and the security scheme names `api/v1/login` as tokenUrl; routers likely excluded from the schema. Do not assume payload shapes. |
| Components Agent, MCP Tools, Run Flow, A2A Agent, Human Input | UNKNOWN: verify in Phase 01 | `/api/v1/all` returned 2.78 MB of JSON (too large to inspect reliably in the browser without scripting); verify in the flow editor |
| Local toolchain (owner VM, aarch64) | OBSERVED | Python 3.10.12, git 2.34.1, uv 0.12.13 |
| Docker / local Compose | **BLOCKED** | `docker` not installed on the owner VM; local two-service Compose tests cannot run there |

## Phase 02 results (20 Oct 2026, owner VM, local only)

Repository: `TaskSprint-Langflow/tasksprint-lab/` (separate from the kit and from
`nuvear/langflow-railway`). Branches: `main` (kit import) and `feature/phase-02-lab`.
No remote configured; nothing pushed or deployed. Full detail: `docs/PHASE02_REPORT.md`.

| Item | Status | Evidence |
|---|---|---|
| Python 3.12 toolchain | TESTED | uv-managed CPython 3.12.14 (aarch64); `uv sync --frozen` exit 0 |
| Locked dependencies | TESTED | `uv.lock` committed: fastapi 0.150.0, pydantic 2.14.1, starlette 1.9.0, httpx 0.28.1, uvicorn 0.54.0, pytest 9.1.1 |
| SQLite FTS5 (for Phase 04 retrieval) | TESTED: available | SQLite 3.53.1 in that Python; `CREATE VIRTUAL TABLE ... USING fts5` and a `MATCH`/`bm25()` query succeeded |
| Migrations with explicit versions | TESTED | Migration 1 (A5 tables, checksum-verified, append-only triggers); idempotent re-run and drift refusal tests pass |
| Role auth (hashes, constant time, deny by default) | TESTED (unit/security) | Every business route has an explicit policy; missing/invalid tokens 401 and wrong roles 403 on every route with DB unchanged |
| Role-field escalation | TESTED (unit/security) | `role`, `approved`, `is_admin`, `acting_as` fields rejected (422); role headers ignored |
| Workspace isolation | TESTED (unit/security) | Tasks, candidates, stories, memory, events, runs bound to workspace; body cannot pick workspace |
| Optimistic concurrency | TESTED (unit) | Stale revision -> 409 REVISION_CONFLICT, no change; 6 simultaneous writers -> exactly one succeeds |
| Sprint stage machine | TESTED (unit) | Legal transitions only; scope confirmation, candidate, trusted test-run evidence, one-repair and human-review preconditions |
| Preference memory | TESTED (unit) | Allowlisted enumerated keys only, owner+workspace scope, expiry; inspected separately from state |
| Immutable candidates | TESTED (unit) | SHA-256 IDs, provenance fixed by server, UPDATE/DELETE aborted by triggers, tamper fails closed, reference source never model-readable |
| Starter v0 seed (`demo-001`) | TESTED | Seeded into `.local/tasksprint.sqlite3`: starter `cand_561149e5c98bb5b7e8ab7357`, sha256 `561149e5…fac1e9b` (matches kit SHA256SUMS), tasks T001/T002, release revision 0 |
| `complete` on v0 | TESTED | Returns FEATURE_UNAVAILABLE, zero task changes. Derived from the registered starter-baseline contract; no candidate source executed (runner is Phase 03) |
| add/list persistence | TESTED | Close/reopen unit test; separate real two-process uvicorn restart (integration test and manual check) preserved T001-T003 |
| `local_init.py` | TESTED | New tokens for 9 roles + runner transport token written to `.local/` (0600, dir 0700); names only printed; second run refused (exit 3) |
| Gate command `uv run pytest -q tests/unit tests/security` | TESTED: **112 passed** | 68 unit + 44 security, 2.47 s, run inside the repository folder |
| Integration `uv run pytest -q -m integration tests/integration` | TESTED: **1 passed** | Real process restart (not part of the gate command) |
| No exec/eval of candidate source | TESTED (static scan) | No `exec`/`eval`/`compile`/`importlib`/`pickle`/`subprocess` in `services/` |
| Docker / Compose | BLOCKED (unchanged) | Docker not installed on the owner VM |

Environment notes recorded during Phase 02 (owner VM only):

- The mounted folder forbids file deletion. SQLite therefore runs with
  `journal_mode=TRUNCATE` (DELETE and WAL modes failed with disk I/O errors there).
- Git cannot run inside the mounted folder (it must unlink lock/temp files). The
  repository was committed on the VM's local disk and copied into the folder,
  including `.git`. Git on the owner's Mac works normally.
- The VM's session disk was full; uv's Python, cache and the virtual environment
  were placed under `/tmp` via `UV_PYTHON_INSTALL_DIR`, `UV_CACHE_DIR`,
  `UV_PROJECT_ENVIRONMENT`, and pytest used `TMPDIR=/tmp/ts/tmp`.
- `.local/fsprobe/` holds disposable filesystem-probe files from this phase
  (ignored by git); the owner may delete it.

## Phase 03 results (20 Oct 2026, owner VM, local only)

Branch `feature/phase-03-runner` (from `feature/phase-02-lab` cef6f52). Full detail:
`docs/PHASE03_REPORT.md`. The owner's `.local/` files and demo database were not used
or changed; manual checks used temporary credentials and a temporary database.

| Item | Status | Evidence |
|---|---|---|
| Git inside the mounted folder | TESTED: works | Deletion now permitted; branch, commits and `git status` ran in place |
| Separate runner service (`services/runner/`) | BUILT LOCALLY, TESTED | `/healthz`, `POST /v1/evaluate` with transport-only bearer; 401 without it (unit, security, integration) |
| AST allowlist validator | TESTED (unit/security) | 27 allowed node classes, asserted exactly; 80-row reject matrix; 27 escape attempts over HTTP rejected with zero ops |
| Tree-walking interpreter and limits | TESTED (unit/security) | 4 KiB / 256 nodes / depth 20 / 100 tasks / 32 KiB input / title 120 / 5,000 ops / 2 s / bounded output (cycles, aliasing) |
| Three fixtures' actual behaviour | TESTED | v0 -> FEATURE_UNAVAILABLE, unchanged; faulty -> drops target (and COMPLETED for unknown ID); reference -> completed=true, retains others, TASK_NOT_FOUND |
| v0 `complete` interpreted (Phase 02 shortcut removed) | TESTED | Response carries runner version, ops (8), interpreted hash = active hash |
| Permitted-change commit + snapshot revision check | TESTED (unit) | Only target completed false->true; faulty/tampered results refused; concurrent task or release change -> 409, other write preserved |
| Protected suite TC-01..TC-06 | TESTED | Reference pass (27/27 assertions); faulty fail (TC-01..TC-04, TC-02 retention); v0 fail (does not satisfy story) |
| Immutable reports | TESTED (unit) | `test_runs` append-only; suite hash `051dfb58…a9551` = SHA-256 of `services/lab/testing.py`; runner version; evidence IDs; `error` (never pass) when runner down |
| Test-run routes | TESTED | `POST /v1/test-runs` qa only; `GET /v1/test-runs/{id}` qa, operations, coordinator; extra fields 422 |
| Provenance, base diffs, Developer read rules | TESTED (unit) | Re-hash + origin/author consistency on every load; difflib base diff; reference never a base or readable by developer |
| Runner holds no DB path, role tokens or secrets | TESTED (process level) | Live runner process env = `LANG, PATH, TS_RUNNER_TOKEN`; no DB file open; refuses to start with `TASKSPRINT_DB_PATH` etc.; refuses root |
| Two-service separation | TESTED as two local processes | Separate PIDs/ports/env (integration). Not container isolation: no network isolation, read-only FS or separate user on the VM |
| `scripts/check_stack.py --target local` | TESTED against local processes only | 5 PASS with an unused runner probe; FAIL correctly reported when probed at the live runner port |
| `Dockerfile.lab`, `Dockerfile.runner`, `compose.yaml` | WRITTEN, NOT BUILT | Static checks only (runner image copies only runner code, numeric non-root user; runner service has no ports/volumes/lab env) |
| `docker compose up --build -d` | **BLOCKED** | Docker not installed on the owner VM |
| Gate command `uv run pytest -q tests/unit tests/security tests/integration` | TESTED: **345 passed** | 245 unit + 90 security + 10 integration, 5.90 s, 0 failed, 0 skipped |

## Future phases

| Item | Status | Phase |
|---|---|---|
| Model connection (TS-00) and sanitized component templates | NOT RUN | 01 |
| Lab backend Phase 02 subset | BUILT LOCALLY, TESTED | 02 (see above) |
| Isolated runner, protected app tests | BUILT LOCALLY, TESTED; Compose BLOCKED | 03 (see above) |
| MCP, retrieval, skills | NOT BUILT | 04 |
| Railway services | NOT BUILT | 05 |
| Live MCP / A2A / HITL protocol tests | NOT RUN | 04–09 |
| Validated flow exports | NOT BUILT | 01 onward |
| Application / security / agent evaluations | NOT RUN | 03–11 |
| Two-hour rehearsal | NOT RUN | 12 |

## Stop conditions carried forward

- A2A work (Phase 08) requires the owner to approve enabling the server A2A flag and a
  manual Redeploy. The variable name `LANGFLOW_A2A_ENABLED` comes from public docs
  (SOURCES S6) and is not yet verified against 1.12.5.
- If Human Input or A2A Agent components are absent in Phase 01, stop and report; do
  not substitute Run Flow or an agent-set approval flag.
- Docker must be installed (or another approved runner chosen) before Compose steps.
  Phase 03 separation is proven only between local processes; container isolation
  (internal network, read-only FS, non-root user) is unverified until Compose runs.
- The owner's `.local/` has no `runner.env` yet; create it with
  `scripts/local_init.py --derive-runner-env` before starting the runner or Compose.
- Never convert OWNER-REPORTED or presence observations into integration PASS.
- Phase 02 unit/security results are local backend behaviour only; they are not MCP,
  A2A, Langflow or deployment results.
