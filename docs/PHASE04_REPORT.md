# Phase 04 report: MCP tool catalog, approved retrieval and on-demand skills (local)

**Date:** 20 October 2026. **Scope:** Phase 04 only, built and tested on the owner's
Linux aarch64 VM. **Gate:** GATE 04 evidence below; stop here for owner review.
**Not touched:** the Langflow instance, Railway, Postgres, `nuvear/langflow-railway`,
the owner's `.local/` files and demo database, `skills/*/SKILL.md`, `knowledge/*.md`,
and the Phase 01 agent's files (`langflow/`, `docs/PHASE01_REPORT.md`,
`docs/OBSERVED_UI.md`, `docs/screenshots/01-*`). Nothing pushed or deployed. All manual
checks used fresh temporary credentials and a temporary database, deleted afterwards.

## Repository

| Item | Value |
|---|---|
| Branch | `feature/phase-04-mcp`, created from `feature/phase-03-runner` (01d5ee1) |
| Commits | `6b6f10a` code, `6c177a8` tests and smoke script, then this report and BUILD_STATUS |
| Toolchain | As Phase 02/03: uv-managed CPython 3.12.14 and venv under `/tmp/ts/` (`UV_PYTHON_INSTALL_DIR`, `UV_CACHE_DIR`, `UV_PROJECT_ENVIRONMENT`, `TMPDIR`) |
| New dependency | `mcp>=1.30.0,<2.0.0`, locked at **mcp 1.30.0** (plus its 14 transitive packages). Chosen because `langflow-base 1.12.x` and `lfx 1.12.x` declare `mcp<2.0.0,>=1.30.0` (PyPI metadata read 20 Oct 2026); mcp 2.x exists but is not what Langflow 1.12 ships |
| Server protocol | Negotiated `2025-11-25` with the 1.30.0 client; `2025-06-18` also negotiated by a raw client (supported: 2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25) |

## Files created or changed

```text
services/lab/mcp.py          MCP server: low-level SDK Server + StreamableHTTPSessionManager at /mcp,
                             auth wrapper, role-filtered tools/list, independent tools/call checks,
                             per-call budget, deadline, structured errors, 19-tool catalog
services/lab/operations.py   trusted operations shared by REST routes and MCP tools (moved out of main.py)
services/lab/retrieval.py    knowledge/*.md ingestion, section chunks, FTS5 bm25 search, filter, abstention
services/lab/skills.py       separate append-only skill catalog (list / exact-version load)
services/lab/frontmatter.py  strict reader for the kit's frontmatter subset (no YAML library)
services/lab/{main,auth,config,schemas,store,__init__}.py
                             new routes + policy entries, MCP settings, migration 2 (FTS5), version 0.4.0
tests/protocol/{conftest,test_mcp_protocol,test_mcp_knowledge_skills,test_mcp_smoke_script}.py
tests/unit/{test_retrieval,test_skills,test_mcp_catalog}.py, tests/security/test_deny_by_default.py
scripts/mcp_smoke.py         real-client smoke check for the owner (prints tool names per role, no secrets)
docs/CANDIDATE_GRAMMAR.md    Phase 03 interpreter limits for Developer-facing guidance (proposal below)
Dockerfile.lab               now copies knowledge/ and skills/ (still not built)
.env.example, pyproject.toml (0.4.0, protocol marker), uv.lock, docs/BUILD_STATUS.md, this file
```

## MCP endpoint and the exact scheme Langflow must use

| Item | Value |
|---|---|
| URL | `<lab base URL>/mcp`, e.g. `http://127.0.0.1:8000/mcp` locally; Phase 05: `https://<lab-host>/mcp` (exactly `/mcp`, no trailing slash) |
| Transport | Streamable HTTP, **stateful** sessions (`Mcp-Session-Id`), JSON responses to POST; GET stream and DELETE supported |
| Header 1 (required) | `Authorization: Bearer <role token>` — the same TaskSprint role tokens as REST (`TS_DEV_TOKEN`, …). The token alone determines the role |
| Header 2 (required) | `X-TaskSprint-Workspace: demo-001` |
| Header 3 (optional) | `X-TaskSprint-Run: run_<32 hex>` — a server-issued run from `POST /v1/runs` (Phase 07 adapter) |
| Roles that may connect | coordinator, product_owner, developer, qa, operations, application. instructor, human_approver and evaluator tokens get **403** at `/mcp` |
| Failure answers | no/invalid token 401 (`WWW-Authenticate: Bearer`); missing/invalid workspace 400 `WORKSPACE_REQUIRED`; malformed run header 400; another credential or workspace presenting a session ID 404; Host not in allowlist 421; foreign `Origin` 403 |
| Host allowlist | `TASKSPRINT_MCP_ALLOWED_HOSTS` (default `127.0.0.1:*,localhost:*,[::1]:*`). **Phase 05 must add the lab's public host (and any private Railway hostname Langflow uses), or every MCP request returns 421** |
| Server deadline | `TASKSPRINT_MCP_TOOL_TIMEOUT_S` (default 20 s); session idle timeout 15 min; at most 200 sessions |

In Langflow this means **one MCP server registration per role** (same URL, different
token header), so each agent's MCP Tools component sees only that role's catalog. The
header value must come from the role's Credential variable through whatever binding the
installed **Add MCP Server** dialog actually offers; that binding is **not yet observed**
on 1.12.5 and must be recorded in `OBSERVED_UI.md` in Phase 06 before use. Do not type a
literal token into a header field that is exported with flows.

## Tool visibility matrix (tools/list per role; direct calls checked again)

Roles derive from `auth.PERMISSIONS` for each tool's backing REST route (one table for
REST and MCP). `*` = listed for Operations but answers `NOT_IMPLEMENTED` (Phases 08–09).

| Tool | coord | PO | dev | qa | ops | app |
|---|---|---|---|---|---|---|
| get_sprint_state | ✔ | ✔ | ✔ | ✔ | ✔ | |
| record_story | ✔ | | | | | |
| transition_story | ✔ | | | | | |
| read_preferences | ✔ | | | | | |
| save_preference | ✔ | | | | | |
| search_approved_knowledge | | ✔ | ✔ | | | |
| list_skills | | | ✔ | | ✔ | |
| load_skill | | | ✔ | | ✔ | |
| read_candidate | | | ✔ | ✔ | ✔ | |
| submit_candidate | | | ✔ | | | |
| run_candidate_tests | | | | ✔ | | |
| read_test_report | ✔ | | | ✔ | ✔ | |
| get_release_readiness | | | | | ✔* | |
| create_release_plan | | | | | ✔* | |
| read_release_plan | | | | | ✔* | |
| execute_approved_plan | | | | | ✔* | |
| get_release_status | | | | | ✔ | ✔ |
| get_app_health | | | | | ✔ | ✔ |
| read_recent_events | ✔ | | | ✔ | ✔ | |
| **count** | 7 | 2 | 6 | 5 | 12 | 2 |

No tool takes credentials, URLs, hosts, SQL, paths, environment names, code to execute,
roles, approval flags, run IDs, workspace IDs or budgets (checked in
`test_mcp_catalog.py`); `submit_candidate.source` is candidate text that only the
runner's interpreter ever evaluates. All schemas are closed (`additionalProperties: false`).

**Call pipeline (every `tools/call`).** (1) charge one action: `X-TaskSprint-Run` if
present, otherwise a root run that the server creates for this MCP session on its first
call (8 actions, 24 per tree, 90 s specialist / 180 s coordinator deadline, recorded as
`run.create` with `source: mcp-session`); exhausted/expired/stale/foreign runs are refused
and recorded as `run.action` with the code; (2) role check — a hidden tool and a
non-existent tool both get `TOOL_NOT_AVAILABLE`, recorded as `mcp.tool_denied`;
(3) strict argument validation (input never echoed); (4) the trusted lab operation runs
in-process under the deadline; (5) an `mcp.tool_call` event records tool, outcome, code,
elapsed time and actions used. Success: `{"result": …, "request_id": …, "budget": {…}}`.
Error: `isError: true` with `{"error": {code, message, request_id[, details]}}`.

## Retrieval (A7)

* Corpus: only top-level regular `knowledge/*.md` files (symlinks refused, sub-folders and
  other extensions ignored). A missing folder refuses start-up rather than serving nothing.
* **Status convention (decided after reading the four files):** every kit file has YAML
  frontmatter with `id`, `version`, `status` (`approved`/`archived`), `effective_from`,
  optional `effective_to`, `owner`. Status and dates come only from frontmatter; headings
  are not interpreted. A file without valid frontmatter refuses start-up.
* Chunks: one per `## ` section, plus the text under the `# ` title (the archived note is a
  single chunk). 15 chunks: brief 5, DoD 4, release policy 5, archived note 1. Chunk hash =
  SHA-256 of `section + "\n" + text`; document hash = file SHA-256 (all four match the kit
  `SHA256SUMS.txt`). Corpus manifest SHA-256 at this commit:
  `4c413f850c8e0fb96cd91b8206a68b21545629edea2385e33a7acf2efbed7eae`.
* Documents and chunks are append-only; a changed file **without a new `version`** refuses
  start-up. A file removed from `knowledge/` leaves the current corpus.
* Query: lower-cased `[a-z0-9]+` terms, small stop list, ≤16 terms, FTS5 `porter unicode61`,
  bm25 (section weight 4, text 1). The approved + effective-today + present-in-corpus
  filter is in the same SQL `WHERE` as the `MATCH`, so archived/expired chunks never take
  part in ranking. Top 3 with `citation {doc_id, version, section, owner, hash}`.
* Abstention: `QUERY_EMPTY`, `NO_APPROVED_EVIDENCE`, `CONFLICTING_EVIDENCE` (two approved
  current versions of one document among the hits).
* `POST /v1/knowledge/search` (product_owner, developer) and the MCP tool record a
  `knowledge.search` event with terms, cited refs, short hashes and abstention code.
* Instructor-only `POST /v1/instructor/knowledge/search {query, include_archived}` shows the
  archived note for the metadata-filter demonstration. It is REST-only, not an MCP tool;
  the normal route rejects an `include_archived` field (422).

## Skills (A7)

`skills/<name>/SKILL.md` → separate append-only `skills` table (name must equal folder;
version from `metadata.version`). `GET /v1/skills` / `list_skills`: name, version,
description, owner, body hash only. `GET /v1/skills/{name}/{version}` / `load_skill`:
exact body, `body_sha256`, `package_sha256`, `grants_permissions: false`, and a
`skill_loaded` event `{name, version, body_sha256}`. A changed SKILL.md without a new
version refuses start-up. Hashes at this commit (package hashes match `SHA256SUMS.txt`):

| Skill | Version | body_sha256 | package_sha256 |
|---|---|---|---|
| implement-todo-change | 1.0.0 | `2c5594bca4b0…090dddf` | `a8f532ce4136…b525ee0` |
| release-and-recover | 1.0.0 | `92d996e295f9…bf0c2f` | `ddf70afaaf66…1120fa6` |

## Commands and actual results

Run in the repository folder on the owner VM, 20 Oct 2026 (UTC):

```text
$ git switch -c feature/phase-04-mcp                     (from 01d5ee1)
$ uv run pytest -q tests/unit tests/security tests/integration   (baseline, before changes)
345 passed in 5.60s
$ uv add "mcp>=1.30.0,<2.0.0"                            + mcp==1.30.0 (15 packages installed)

$ uv run pytest -q tests/unit tests/security tests/integration tests/protocol   (05:26Z)
422 passed in 16.29s
$ uv run pytest -q tests/unit           278 passed in 3.17s
$ uv run pytest -q tests/security        91 passed in 1.62s
$ uv run pytest -q tests/integration     10 passed in 2.67s
$ uv run pytest -q tests/protocol        43 passed in 8.92s
$ uv run pytest -q tests/unit tests/security tests/integration   379 passed in 7.30s
0 failed, 0 skipped. tests/protocol also re-run twice more: 43 passed each time.
$ uv lock --check --offline              Resolved 40 packages   exit 0
static scan of services/ for exec( / eval( / compile( / importlib / pickle / subprocess: none
```

The 345 Phase 02–03 tests still pass after moving route bodies into `operations.py`.

**Manual end-to-end (two real processes, fresh temporary credentials, 05:22Z):** runner on
127.0.0.1:18101 (env `PATH`, `LANG`, `TS_RUNNER_TOKEN` only), lab on 127.0.0.1:18100.

```text
$ uv run python scripts/mcp_smoke.py --lab-url http://127.0.0.1:18100 --tokens-file <tmp>/role_tokens.env --call-state
PASS no token -> HTTP 401
PASS human_approver token refused at /mcp -> HTTP 403
PASS instructor token refused at /mcp -> HTTP 403
PASS evaluator token refused at /mcp -> HTTP 403
PASS coordinator protocol 2025-11-25: 7 tools: get_sprint_state, record_story, transition_story, read_preferences, save_preference, read_test_report, read_recent_events [get_sprint_state ok, budget 1/8]
PASS product_owner protocol 2025-11-25: 2 tools: get_sprint_state, search_approved_knowledge [get_sprint_state ok, budget 1/8]
PASS developer protocol 2025-11-25: 6 tools: get_sprint_state, search_approved_knowledge, list_skills, load_skill, read_candidate, submit_candidate [get_sprint_state ok, budget 1/8]
PASS qa protocol 2025-11-25: 5 tools: get_sprint_state, read_candidate, run_candidate_tests, read_test_report, read_recent_events [get_sprint_state ok, budget 1/8]
PASS operations protocol 2025-11-25: 12 tools: ... get_release_readiness, create_release_plan, read_release_plan, execute_approved_plan, get_release_status, get_app_health, read_recent_events [get_sprint_state ok, budget 1/8]
PASS application protocol 2025-11-25: 2 tools: get_release_status, get_app_health [get_release_status ok, budget 1/8]
RESULT PASS

PO search 'delete completed tasks'                  -> ok  brief@1.0#Completion story (daf0f110c703), #Acceptance criteria (c9b07953a004), #Starter (83857dc52112)
PO search 'keep completed task records in the list' -> ok  brief@1.0#Acceptance criteria, #Completion story, #Starter
PO search 'zebra quantum saxophone'                 -> abstain NO_APPROVED_EVIDENCE
INSTRUCTOR include_archived 'remove a task from storage when marked complete'
                                                    -> tasksprint-early-design-note@0.1 (archived), brief@1.0, brief@1.0
DEV load_skill release-and-recover 1.0.0 -> body_sha256 92d996e295f97200…, event evt_a62e3107…
DEV tools after load: get_sprint_state, search_approved_knowledge, list_skills, load_skill, read_candidate, submit_candidate
DEV execute_approved_plan -> isError TOOL_NOT_AVAILABLE ; DEV create_release_plan -> isError TOOL_NOT_AVAILABLE
EVENTS: knowledge.search ok/abstain, run.create, skill_loaded {release-and-recover, 1.0.0}, mcp.tool_call ok,
        mcp.tool_denied denied {execute_approved_plan}, mcp.tool_denied denied {create_release_plan}
lab log: 2 lines, no token or "Bearer" text
```

## Gate 04 mapping

| Gate 04 / card requirement | Evidence | Status |
|---|---|---|
| Real MCP client calls authenticated tools (initialize, tools/list, tools/call) | `test_initialize_negotiates_protocol_over_streamable_http`, `test_tools_list_is_role_scoped[6 roles]`, `test_tools_call_returns_real_persistent_state` (MCP result == REST state), submission and QA test-run through MCP; smoke run | TESTED (MCP-01, MCP-02) |
| Error semantics | validation, backend (`CANDIDATE_NOT_FOUND`, `SKILL_NOT_FOUND`), `NOT_IMPLEMENTED`, all `isError` + structured code; no input echo | TESTED (MCP-03) |
| Timeout behaviour | hung runner: server deadline → `TOOL_TIMEOUT` < 4 s, session survives, operation later recorded honestly as test-run `error` (never pass); client read timeout → `McpError`, new session works | TESTED (MCP-03) |
| Cleanup | session ID answers 404 after the client's DELETE on close; raw DELETE accepted | TESTED (MCP-03) |
| Wrong role rejected; hidden tools denied on direct call | 9 role/tool pairs + unknown tool → `TOOL_NOT_AVAILABLE` + `mcp.tool_denied` event; hidden writes change nothing | TESTED (SEC-02) |
| No/wrong token; non-agent roles | 401 for missing/invalid/Basic/short tokens on POST/GET/DELETE; SDK client with wrong token fails with HTTP 401; instructor/approver/evaluator 403 | TESTED (SEC-01, SEC-16) |
| Session bound to credential | another role or workspace using a live session ID → 404 | TESTED |
| Budget per run, recorded reason | 8 calls OK, 9th `BUDGET_EXHAUSTED` + `run.action` event; header run charged; foreign/unknown run `RUN_NOT_BOUND` | TESTED (A9 subset) |
| Index only `knowledge/` with versioned evidence | exactly 4 documents, hashes = kit checksums, no fixture/source text, symlink/sub-folder/non-md excluded | TESTED |
| Archived "delete completed tasks" guidance excluded | REST and MCP queries never return `tasksprint-early-design-note`; instructor view does | TESTED |
| Current retention passage returned and cited | top hit brief@1.0 Completion story / Acceptance criteria with citation hash = stored chunk hash | TESTED |
| Abstention | nonsense, stopword-only and conflicting-version queries | TESTED |
| On-demand skill loading visible; no new permissions | `skill_loaded` event with version/hash; developer tools/list unchanged; `execute_approved_plan`, `create_release_plan`, `get_release_status` still denied | TESTED |
| Langflow MCP Tools component connected to this server | lab not reachable from the Railway Langflow until Phase 05; header binding unobserved | **BLOCKED** |
| Model actually grounds a story in retrieved passages (RAG demonstration) | needs a Langflow agent (Phase 06) and evaluations (AE-01/AE-02) | NOT RUN |

## Deviations and decisions for the owner

1. **Budget without a run header.** When Langflow sends no `X-TaskSprint-Run`, the server
   creates one bounded run per MCP session. If Langflow keeps one MCP session across agent
   invocations, all invocations share 8 actions and the run expires after 90 s
   (`RUN_EXPIRED`; the client must open a new session). Phase 07 must observe Langflow's
   session reuse and then either inject `X-TaskSprint-Run` from a trusted adapter or rely on
   per-invocation sessions. This is not a silent budget increase: a new session = a new
   recorded root run, as with `POST /v1/runs`.
2. **Every call is charged before authorization**, including hidden, invalid and
   `NOT_IMPLEMENTED` calls, so a model cannot probe forever for free.
3. **`search_approved_knowledge` roles = product_owner and developer.** A4 names the PO;
   the Developer skill (step 2) and prompt require requirement retrieval. Coordinator, QA
   and Operations do not get it.
4. **`read_test_report` excludes the developer**, exactly as A8 (qa, operations,
   coordinator), although `prompts/developer.md` and the skill say the Developer reads the
   immutable report. Either the Coordinator relays the report (current behaviour) or the
   owner approves adding developer to `GET /v1/test-runs/{id}`. Decision needed before Phase 06.
5. **Server-side timeout does not cancel the operation.** The worker thread is abandoned;
   the operation can still finish and commit (append-only evidence). The result says so and
   points to `read_recent_events`/the report. "Stop/cancel must prevent late commits" (SEC-13)
   remains Phase 07.
6. **JSON responses, stateful sessions.** Both are standard Streamable HTTP; Langflow's
   client (same SDK line) should accept them, but this is unverified against Langflow.
7. **Planned tools' schemas are provisional** (`create_release_plan {action, candidate_id}`,
   `read_release_plan`/`execute_approved_plan {plan_id}`); Phases 08–09 may change them,
   which changes the tool manifest.
8. **DNS-rebinding protection is on** (Host allowlist, foreign `Origin` refused). It needs
   the Phase 05 host names (see the endpoint table).
9. **The FTS5 table cannot carry the append-only triggers** (virtual table); only ingestion
   writes to it, and `documents`/`chunks` stay append-only.
10. **Kit edits now need a version bump.** Editing a knowledge file or SKILL.md without
    changing its version makes the lab refuse to start. This is deliberate (versioned
    evidence) and matters for the SKILL.md proposal below.
11. **Refactor.** REST route bodies moved into `services/lab/operations.py` so REST and MCP
    run identical checks; REST behaviour unchanged (345 earlier tests pass).
12. The SDK logs `Tool '<name>' not listed, no validation will be performed` for hidden or
    unknown tool calls (server log; tool name only; no request data).
13. `Dockerfile.lab` now copies `knowledge/` and `skills/`; images are still not built.

## Proposed `implement-todo-change` v-next (not applied — owner approval needed)

`docs/CANDIDATE_GRAMMAR.md` documents the Phase 03 limits (verified against the validator
on this branch: unary minus/`-1` index, `pass`, `break`, calls, chained assignment,
docstrings, floats, `<` rejected; comprehension inside a loop `NESTED_ITERATION`; comments
accepted; `True == 1` evaluates to `False`). It contains no complete solution. Proposed
change, as a new skill version so the load event records a new hash:

* `metadata.version: "1.1.0"` (required, or the lab refuses to start).
* Add under **Procedure** step 4: "Allowed: one `for` loop (no nesting, no comprehension
  inside it), `if/elif/else`, `return value`, single-target assignment to a name or
  `x[key]`, str/int/bool/None constants, list and dict literals, subscripts, `==`, `!=`,
  `in`, `not in`, `and`, `or`, `not`, one single-level list comprehension. Not allowed:
  any call (including `len`, `range`, `.append`), attributes, arithmetic or unary minus
  (no `-1` index), `pass`/`break`/`continue`/docstrings, `is`, `<`/`>`. Equality is JSON
  equality: `True != 1`. Limits: 4 KiB source, 256 syntax nodes, 5,000 operations, 2 s."
* Add to **Stop and escalate**: "a validator rejection you cannot fix within this grammar".

## BLOCKED and not run

| Item | Reason |
|---|---|
| Langflow MCP Tools ↔ this server | Lab not deployed (Phase 05); Langflow on Railway cannot reach the VM; Add MCP Server header/Credential binding not yet observed on 1.12.5 |
| Agent grounding with retrieved passages (AE-01/AE-02) | Needs Langflow agents (Phase 06) and the evaluation harness (Phase 10) |
| Readiness, plans, execution | Phases 08–09 (tools answer `NOT_IMPLEMENTED`) |
| `docker compose up --build -d` | Docker not installed (carried from Phase 03) |

## Manual (human) equivalent

1. `git switch -c feature/phase-04-mcp` from the Phase 03 branch; `uv add "mcp>=1.30.0,<2.0.0"`.
2. Add `retrieval.py` (parse frontmatter, chunk by `##`, insert documents/chunks/FTS rows,
   search with the approved/effective filter inside the `MATCH` query, top 3, abstain),
   `skills.py` (load each `skills/<name>/SKILL.md`, list metadata, load exact version and
   record `skill_loaded`), and `mcp.py` (SDK `Server` + `StreamableHTTPSessionManager`;
   authenticate each request; list/call from `auth.PERMISSIONS`; charge a run per call).
3. `uv run pytest -q tests/unit tests/security tests/integration tests/protocol`.
4. Start runner and lab as in Phase 03 (step 6–7 of `PHASE03_REPORT.md`), seed `demo-001`.
5. `uv run python scripts/mcp_smoke.py --lab-url http://127.0.0.1:8000 --call-state`
   (reads `.local/role_tokens.env`, prints no values). Expect `RESULT PASS`.
6. With any MCP client (for example the MCP Inspector) connect to `http://127.0.0.1:8000/mcp`
   with the two headers above; as Product Owner call `search_approved_knowledge` with
   "delete completed tasks" (no archived note) and "keep completed task records" (brief
   citations); as Developer call `load_skill release-and-recover 1.0.0`, then try
   `execute_approved_plan` (`TOOL_NOT_AVAILABLE`). As instructor, `POST
   /v1/instructor/knowledge/search` shows the archived note.

## Next action

Owner reviews `git log --oneline feature/phase-03-runner..feature/phase-04-mcp` and this
report, then decides: (a) approve or edit the `implement-todo-change` 1.1.0 text above;
(b) developer access to `read_test_report` (deviation 4). Then paste **Card 05** (Railway
services, owner approval required). Phase 05 must set `TASKSPRINT_MCP_ALLOWED_HOSTS` to the
lab's real host names; Phase 06 registers one MCP server per role in Langflow and records
the observed header/Credential-variable binding in `OBSERVED_UI.md`.
