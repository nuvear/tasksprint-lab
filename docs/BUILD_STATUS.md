# Build status

**Last updated:** 20 October 2026, about 13:45 UTC (Phase 08 executed).
**Current gate:** **GATE 08 PASS** (`docs/PHASE08_REPORT.md`) on branch `feature/phase-08-a2a` (not
pushed; lab redeployed by the orchestrator from `main` = `ea746f1`, lab 0.5.0). Genuine A2A JSON-RPC 0.3
exchange Sprint Room → TS-20 captured with Task/context/artifact IDs, lab exchange records and
Operations' own child-run trace; card `protocolVersion` 0.3.0; unauthorized execution 401; peer-off
bounded failure; no plan, approval or release created (deploy blocked by the Phase 10 manifest gate).
Open owner decisions: http:// card URL behind Railway TLS, handoff contract 1.1, tool name
`assess_production_release`, Operations' 8-action budget pressure. GATE 07 evidence `docs/PHASE07_REPORT.md`.
**Live-instance changes in Phase 08:** new flow `TS-20 Production Manager`
`489890aa-4bd0-4641-b669-070f10e0922b` (`flow_type=agent`, `a2a_enabled=true`, published in the
Agent pane); TS-10 updated in place (Bounded Toolset 1.1.0 + TaskSprint A2A Audit node); API key
`tasksprint-a2a-runtime` (`450683a7-…`, expires 2027-01-18) and Credential global `TS_A2A_API_KEY`.
The orchestrator set `LANGFLOW_A2A_ENABLED=true` and redeployed Langflow before the phase; no other
Railway change.
**Live-instance changes in Phase 07:** TS-01/02/03 rewired (MCP Tools → TaskSprint Bounded Toolset,
Run Context 1.1.0; ids kept); new flow `TS-10 Sprint Room` `ec5b5dba-d7d2-4aeb-899c-016a3f66b4eb`.
**Live-instance changes in Phase 06:** project `TaskSprint`; flows TS-30, TS-01, TS-02, TS-03;
7 globals (`TASKSPRINT_API_BASE`, six role tokens); 6 MCP servers; Langflow auto-created 6
`MCP_*` Credential globals and the project MCP server `lf-tasksprint`. Railway untouched.

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

## Phase 04 results (20 Oct 2026, owner VM, local only)

Full detail: `docs/PHASE04_REPORT.md`. Branch `feature/phase-04-mcp` (from 01d5ee1).
Nothing in Langflow, Railway or `nuvear/langflow-railway` was touched.

| Item | Status | Evidence |
|---|---|---|
| MCP server, Streamable HTTP, `/mcp` | BUILT LOCALLY, TESTED (real SDK client) | mcp 1.30.0 (Langflow 1.12 pins `mcp>=1.30,<2`); negotiated 2025-11-25; stateful sessions, JSON responses |
| MCP auth scheme | TESTED | `Authorization: Bearer <role token>` + `X-TaskSprint-Workspace`; optional `X-TaskSprint-Run`; 401/403/404/421 cases tested |
| Role-filtered tools/list (19 tools; coord 7, PO 2, dev 6, qa 5, ops 12, app 2) | TESTED | `test_tools_list_is_role_scoped`, smoke script; derived from `auth.PERMISSIONS` |
| Hidden tool direct call denied (SEC-02) | TESTED | `TOOL_NOT_AVAILABLE` + `mcp.tool_denied` event; no state change |
| tools/call, errors, timeout, cleanup (MCP-01..03) | TESTED locally | persistent results; structured `isError`; server deadline and client timeout against a hung runner; DELETE → 404 |
| Per-call run budget (A9 subset) | TESTED | 8 per run; `BUDGET_EXHAUSTED` recorded; header run or server-created per-session run |
| Readiness / plans / execution tools | LISTED for operations, `NOT_IMPLEMENTED` | Phases 08–09; no stubbed success |
| Retrieval over `knowledge/` only (FTS5 bm25, approved+effective filter, top 3, citations, abstention) | TESTED | 4 documents / 15 chunks, hashes = kit checksums; archived note excluded; retention passage cited; instructor-only archived view |
| Skill catalog, `skill_loaded` events, no added authority | TESTED | developer loads release-and-recover yet plan/execute stay denied |
| `docs/CANDIDATE_GRAMMAR.md` + proposed `implement-todo-change` 1.1.0 | WRITTEN; SKILL.md NOT CHANGED | owner approval needed (report) |
| Langflow MCP Tools component ↔ lab | **BLOCKED** | lab not deployed (Phase 05); header/Credential binding not yet observed |
| Gate command `uv run pytest -q tests/unit tests/security tests/integration tests/protocol` | TESTED: **422 passed** | 278 unit + 91 security + 10 integration + 43 protocol, 16.29 s, 0 failed, 0 skipped |

## Phase 05 results — build side only (20 Oct 2026, owner VM, no Docker)

Full detail: `docs/PHASE05_PREP_REPORT.md`; owner steps: `docs/RAILWAY_SETUP.md`.
`main` fast-forwarded to `feature/phase-04-mcp` so Railway can deploy from `main`. Nothing
in Langflow, Railway, Postgres or `nuvear/langflow-railway` was touched; nothing pushed.

| Item | Status | Evidence |
|---|---|---|
| Owner decision: `implement-todo-change` 1.1.0 (grammar limits) | APPLIED, TESTED | lab appends 1.1.0 next to a recorded 1.0.0 (`test_version_bump_appends…`, real start against such a DB) |
| Owner decision: `read_test_report` stays qa/ops/coordinator | APPLIED | `prompts/developer.md` reworded (Coordinator relays); coordinator.md unchanged |
| `Dockerfile.lab`, `Dockerfile.runner`, `.dockerignore` | WRITTEN, STATIC CHECKS TESTED; **NOT BUILT** | `tests/unit/test_deploy_files.py` (tag pins, lock-only install, non-root USER, PORT, `/healthz`, COPY allowlists, context exclusions, no VOLUME) |
| Base-image digest pinning | TODO | needs a Docker host (`docker buildx imagetools inspect`) |
| Entrypoints `services/{lab,runner}/serve.py` ($PORT, one worker, lab 0.0.0.0, runner dual-stack ::) | TESTED as processes | `tests/integration/test_serve_railway_mode.py`, `tests/unit/test_serve.py` |
| Volume ownership on Railway (`RAILWAY_RUN_UID=0` → chown `/data` → drop to 10002) | UNIT-TESTED with a fake OS; real root path **NOT RUN** | cannot run as root on the VM; verify in the first Railway deploy log |
| Migrations once under a lock; nothing seeded at start | TESTED | 6 concurrent starters apply once; failed migration applies nothing; fresh start has 0 workspaces |
| `TASKSPRINT_MCP_ALLOWED_HOSTS` from env (public host accepted, others 421) | TESTED (process, Host header) | real Railway domain pending |
| Redacted logs | TESTED | token-shaped path and bearer strings masked; no token value in lab/runner/script output |
| `check_stack.py --target railway` (+ `--snapshot save/verify`), `seed_demo.py --lab-url` | TESTED against local processes (http loopback test mode) | save → restart → verify PASS |
| Railway services, domain, volume, private DNS | **BLOCKED (owner)** | `docs/RAILWAY_SETUP.md` steps 1–2 |
| Post-deploy checks 05.5 (HTTPS, 401, persistence after lab redeploy) | **NOT RUN** | `docs/RAILWAY_SETUP.md` step 4 |
| Gate command `uv run pytest -q tests/unit tests/security tests/integration tests/protocol` | TESTED: **463 passed** | 315 unit + 92 security + 13 integration + 43 protocol, 0 failed, 0 skipped |

## Phase 07 results (20 Oct 2026, live Langflow + deployed lab, owner's Chrome)

Full detail: `docs/PHASE07_REPORT.md`; UI labels: `docs/OBSERVED_UI.md` (Phase 07 section).

| Item | Status | Evidence |
|---|---|---|
| `components/bounded_toolset.py` 1.0.0 (official `mcp` SDK in Langflow; fresh session per call; `X-TaskSprint-Run`) | **TESTED end to end**; static checks in `tests/unit/test_components_static.py` | tool calls charged to the Run Context run (`run_7c571311…`); no pooled-session run |
| `components/run_context.py` 1.1.0 (Run output, child runs from delegated sessions) | **TESTED** | child `run.create` with `parent_run_id`, depth 1, for every delegation |
| TS-01/02/03 switched from MCP Tools to the toolset (ids kept; Phase 06 exports kept as `*.phase06.json`) | **TESTED** | Card 06 prompts re-run; 2nd QA prompt 2+ min later: new run, no `RUN_EXPIRED` |
| TS-10 Sprint Room `ec5b5dba-d7d2-4aeb-899c-016a3f66b4eb` (3 Run Flow tools → TS-01/02/03 only, coordinator MCP tools) | **TESTED** | `07-03`; exports `flows/10_sprint_room.json` |
| 07.3 story proposal (scope pending), preference, fresh-chat resume = backend | **TESTED** | ST-001 `evt_2bc91b77…`; `memory.save` `evt_c106f633…`; New Session 0 answer = `/v1/state` + `/v1/memory` |
| 07.4 failing read / budget 2 / tree 24 / timeout / expired-run write / one repair / repair limit / no progress | **TESTED** | `evt_885f2e7a…`; message `5818078c…`; `evt_e87df79e…`, `evt_b82a9ea6…`; message `cc227974…`; `req_917c1dc4…`; `tr_35be6859…` fail → `tr_b2139a09…` pass; REPAIR_BUDGET_EXHAUSTED; NO_PROGRESS |
| Brief 1.1 + skill 1.2.0 (return-code contract) | **TESTED in unit/protocol tests; NOT SERVED** until the lab is redeployed (merge to main → Railway rebuild) | `knowledge/01_product_brief.md`, `skills/implement-todo-change/SKILL.md` |
| Cross-turn repair limit | **DEFERRED** | lab `repair_count` applies after human scope confirmation (Phase 09) |
| Lab re-check of the run inside write transactions | **PROPOSED** (owner decision) | PHASE07 finding 4 |
| Gate command `uv run pytest -q tests/unit tests/security tests/integration tests/protocol` | TESTED: **471 passed** | 0 failed, 0 skipped |

## Phase 06 results (20 Oct 2026, live Langflow + deployed lab, owner's Chrome)

Full detail: `docs/PHASE06_REPORT.md`; UI labels: `docs/OBSERVED_UI.md` (Phase 06 section).

| Item | Status | Evidence |
|---|---|---|
| Globals 06.1 (Generic + 6 Credential) | **TESTED** | `scripts/import_globals.py --apply` PASS ×7, rerun keep ×7; `06-01` (masked) |
| MCP header ↔ Credential binding | **TESTED** | `Authorization: Bearer {{TS_<ROLE>_TOKEN}}` resolved (tool counts 2/6/5/2/7/12); globe chip is whole-value only (`06-04`…`06-09`) |
| Adapters `components/app_console.py` 1.0.1, `run_context.py` 1.0.0 | **TESTED end to end** (compiled by the instance; no unit tests) | TS-30 commands; Run Context `run.create` per invocation |
| TS-30 To-do App (no LLM): add/list/status/complete→FEATURE_UNAVAILABLE | **TESTED** | events `evt_8702d638…`, `evt_01edc15d…` (actor application) |
| TS-01 PO retrieval + citations | **TESTED** | `knowledge.search` `evt_626bcfcc…`, `evt_a9ef3145…`, `evt_db33f67a…`; brief v1.0 citations |
| TS-02 Dev skill load + new candidate | **TESTED** | `skill_loaded` `evt_a08469ed…` (1.1.0); `cand_1c9e49bc8de73e1ba06ab786` sha256 `1c9e49bc…44689e` |
| TS-03 QA protected suite for that hash | **TESTED** (candidate fails TC-01) | `tr_38d1e08a937945f3346b977b`, runner 0.3.0, suite `051dfb58…` |
| Identity / impersonation (SEC-02 via Langflow + probes) | **TESTED** | `scripts/phase06_checks.py --probes`: 21 pass, 0 fail |
| Sanitized exports `flows/{01,02,03,30}_*.json` | **TESTED** (scan clean) | `import_flows.py --export`; re-import onto same instance + run PASS; fresh-instance import NOT RUN |
| Per-run budget header to MCP Tools | **RESOLVED in Phase 07** | was BLOCKED (`06-27`); replaced by the bounded toolset |
| Isolated `test-specialists` workspace | **NOT AVAILABLE** | allowed workspaces = demo-001 only; checks ran in demo-001; reset list in report |

## Phase 01 results (20 Oct 2026, live instance, owner's Chrome)

Full detail: `docs/PHASE01_REPORT.md`. Map: `langflow/COMPONENT_MAP.md`.

| Item | Status | Evidence |
|---|---|---|
| Model Providers (Anthropic, OpenAI) | OWNER-REPORTED configured; OBSERVED in Agent dropdown | `screenshots/01-05-model-dropdown.png` |
| Bootstrap Langflow API key `tasksprint-bootstrap` | OWNER-REPORTED | Value never seen |
| Plain model response via Agent | **TESTED** | `TS-00 Connection Check` (3f476c53-e39f-4157-8f73-5e488a0a43e9), model `claude-sonnet-5-5` (Anthropic). Reply `TaskSprint model connection is working.`, 594 tokens, 2.0 s (`01-09`, trace `01-20`) |
| Tool calling | NOT RUN | Phase 04/06 |
| Component catalog | OBSERVED | Agent, A2A Agent, Human Input, Run Flow (Beta), Chat I/O, Prompt Template present; **MCP Tools absent** until an MCP server is registered |
| Template flow `TS-00T Templates` | OBSERVED (built, not run) | 0685ac65-234e-4752-bf76-ba45860e74be |
| Sanitized templates | PARTIAL | `langflow/templates/*.partial.json`: structural captures from `GET /api/v1/flows/{id}`; component source replaced by module + code_hash; not importable |
| UI export | OBSERVED (dialog only) | Not downloaded; needs owner |
| Export → re-import round trip | **NOT TESTED** | Proxy: UI **Duplicate** ran OK (`01-31`); duplicate `ed883180-37ff-47ff-be69-49d7e9cebaaa` left for owner to delete |
| Credential scan of captures | **TESTED: none found** | Secret fields `api_key` all empty |
| A2A server publishing UI | OBSERVED, disabled | Banner names `LANGFLOW_A2A_ENABLED=true` (now verified on 1.12.5) |
| A2A readiness | NOT CLAIMED | Phase 08 |

## Future phases

| Item | Status | Phase |
|---|---|---|
| Model connection (TS-00) and sanitized component templates | TESTED (model); PARTIAL (templates); round trip pending owner export | 01 (see above) |
| Lab backend Phase 02 subset | BUILT LOCALLY, TESTED | 02 (see above) |
| Isolated runner, protected app tests | BUILT LOCALLY, TESTED; Compose BLOCKED | 03 (see above) |
| MCP, retrieval, skills | TESTED through Langflow (Phase 06) | 04, 06 |
| Railway services | DEPLOYED, GATE 05 PASSED | 05 |
| Live MCP / A2A / HITL protocol tests | MCP: TESTED through Langflow (native client Phase 06, SDK in the bounded toolset Phase 07); A2A/HITL NOT RUN | 04–09 |
| Validated flow exports | TS-01/02/03/10/30 exported; same-instance dry-run keep ×5; fresh instance NOT RUN | 06, 07, 11 |
| Application / security / agent evaluations | NOT RUN | 03–11 |
| Two-hour rehearsal | NOT RUN | 12 |

## Stop conditions carried forward

- Redeploy the lab (merge to main → Railway rebuild) before relying on brief 1.1 / skill 1.2.0;
  then re-run the Developer and QA specialist checks (PHASE07 T1).
- Cross-turn repair limit depends on the story stage machine (human scope confirmation, Phase 09).
- Keep TS-90 off the project MCP server `lf-tasksprint` (Phase 09).

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
- Phase 05 must set `TASKSPRINT_MCP_ALLOWED_HOSTS` to the lab's real host names, or every
  MCP request is refused with 421. Editing `knowledge/*.md` or `SKILL.md` requires a new
  version, or the lab refuses to start (Phase 04).
- Phase 05 Railway: the lab needs `RAILWAY_RUN_UID=0` (root-owned volume; the entrypoint drops
  to uid 10002) or it refuses to start; the runner must receive only `PORT`, `TS_RUNNER_TOKEN`
  and `RAILWAY_DOCKERFILE_PATH`. Pin image digests on a Docker host before relying on builds.
  Do not mark GATE 05 until the post-deploy checks in `docs/RAILWAY_SETUP.md` pass.
- Never convert OWNER-REPORTED or presence observations into integration PASS.
- Phase 02 unit/security results are local backend behaviour only; they are not MCP,
  A2A, Langflow or deployment results.


## Phase 08 results (20 Oct 2026, 13:00–13:45 UTC)

| Item | Status | Evidence |
|---|---|---|
| Server A2A flag | TESTED: enabled | `GET /api/v1/config` `a2a_enabled: true`; `GET /api/v1/a2a/agents` 200; pane without the "turned off" banner (`08-04`) |
| Lab 0.5.0 (readiness, plans, exchanges, commit-time run re-check) | TESTED + DEPLOYED | 496 tests pass; live `GET /v1/readiness` 200 after the redeploy from `ea746f1` |
| TS-20 Production Manager | TESTED | `489890aa-4bd0-4641-b669-070f10e0922b`, `flow_type=agent`, `a2a_enabled=true` (Live) |
| A2A-01 card discovery | PASS | `protocolVersion` 0.3.0, JSONRPC, apiKey `x-api-key`; public card; `url` advertises http:// (finding 1) |
| A2A-02 authenticated assessment | PASS | Task `2be4fd39-edf9-4c4b-971f-aaa8278acba0`, artifact `cd23cee4-…`, exchange `a2ax_fd510b2e…`, Operations child run `run_17ec87dd…`; blocked (manifest NOT_QUALIFIED), no plan |
| A2A-03 unauthorized execution | PASS | `message/send` no key / wrong key 401 (13:22Z, 13:42Z); `tasks/get` no key 401 |
| A2A-04 unreachable peer / duplicate | PASS | peer off → `PEER_UNAVAILABLE`, exchange `a2ax_06d6a76d…` without task, no artifact/release; same-turn duplicate → `DELEGATION_LIMIT`; plan dedup unit-tested |
| No release | PASS | active `cand_561149e5…` revision 0, history 1 |
| Exports | DONE | `flows/20_operations.json` (sha256 `c1919eaa…`), `flows/10_sprint_room.json` (`c49e26cf…`); `import_flows.py --dry-run` keep ×6 |
