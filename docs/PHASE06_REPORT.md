# Phase 06 report: To-do App and three independent specialists in Langflow

**Date:** 20 October 2026, 11:36–12:05 UTC. **Instance:** Langflow 1.12.5
(`https://langflow-railway-production-f493.up.railway.app`), owner's Chrome signed in as admin by
the owner; lab `https://tasksprint-lab-production.up.railway.app` (GATE 05). **Branch:**
`feature/phase-06-langflow` from `89fdf72`. **Gate:** GATE 06 evidence below, with two open
items for the owner (deviations 1 and 2). Stop here.

**Not touched:** Railway (no variable, deploy or service change), Langflow Postgres,
`nuvear/langflow-railway`, TS-00 / TS-00T / Starter Project flows, the four pre-existing
Credential globals, Model Providers, Langflow API keys, the A2A flag. No TS-10/TS-20/TS-90.
No secret value was printed, put on a command line, typed into a field or captured on screen.

## What was built (live instance)

| Item | ID / value | How |
|---|---|---|
| Project (folder) `TaskSprint` | `9c4defb4-3457-4e34-9668-b940fadb030f` | `scripts/import_flows.py` (`POST /api/v1/projects/`) |
| `TS-30 To-do App` | `1613b28e-6e07-4056-a832-b9abeceb607e` | Chat Input → **TaskSprint App Console** → Chat Output; no model |
| `TS-01 Product Owner` | `da674f03-2861-4b3f-9f25-129bb86a588f` | Chat Input → **TaskSprint Run Context** → Agent (+ MCP Tools `tasksprint-product-owner`, Tool Mode → Agent **Tools**) → Chat Output |
| `TS-02 Developer` | `9610ee79-66ce-4f92-b304-44d9e5c8be38` | same skeleton, MCP Tools `tasksprint-developer` |
| `TS-03 QA` | `8906e4df-4fe3-489f-b30b-d5e57230459c` | same skeleton, MCP Tools `tasksprint-qa` |
| Generic global | `TASKSPRINT_API_BASE` = lab origin | `scripts/import_globals.py --apply` (bootstrap key, approved by Raj) |
| Credential globals | `TS_COORD_TOKEN`, `TS_PO_TOKEN`, `TS_DEV_TOKEN`, `TS_QA_TOKEN`, `TS_OPS_TOKEN`, `TS_APP_TOKEN` | same; approver/instructor/evaluator deliberately not created (Phase 09) |
| MCP servers | `tasksprint-product-owner` (2 tools), `tasksprint-developer` (6), `tasksprint-qa` (5), `tasksprint-application` (2), `tasksprint-coordinator` (7), `tasksprint-operations` (12) | first one in the **Add MCP Server** dialog by hand, the rest by `scripts/import_mcp_servers.py` (`POST /api/v2/mcp/servers/{name}`); counts = Phase 04 matrix |
| Auto-created by Langflow | `MCP_TASKSPRINT_{PRODUCT_OWNER,DEVELOPER,QA}_{AUTHORIZATION,X_TASKSPRINT_WORKSPACE}_<hash>` (6 Credential globals); project MCP server `lf-tasksprint` (0 tools, API-key auth) | side effects of saving a flow with an MCP Tools node / creating a project (see OBSERVED_UI) |

Agent settings in all three specialists (verified in the exports): Language Model
`claude-sonnet-5-5` (Anthropic), Agent Instructions = `prompts/<role>.md` byte-for-byte
(sha256 PO `82537ee3…`, Dev `d03bd9f2…`, QA `e2393167…`), **Max Iterations 8**, **Calculator
off**, **Current Date off**, API Key empty, Number of Chat History Messages 100 (default).
MCP Tools: Tool Mode on, all role tools selected, Tool Execution Timeout 0 (= system default),
Use Cached Server off. Flows created through the API have `mcp_enabled: false` (not listed on
the project MCP server); left as is.

## Credential binding mechanisms (TESTED)

* **Header values of an MCP server** (Settings → MCP Servers → Add MCP Server → **Streamable
  HTTP/SSE**): the value field's globe icon inserts a *whole-value* variable chip only (e.g.
  `TS_PO_TOKEN`), which cannot express `Bearer <token>`. Langflow 1.12.5 also resolves a
  `{{NAME}}` placeholder inside a header value (lfx 1.12.5 `base/mcp/util.py`
  `_substitute_global_variables`; docs.langflow.org mcp-client: "You can use global variables in
  header values"). Used: `Authorization: Bearer {{TS_PO_TOKEN}}`, `X-TaskSprint-Workspace:
  demo-001`. Evidence it resolves: the server list shows **2 tools** for the PO server (the lab
  lists exactly 2 tools only for the product_owner token; a wrong/unresolved token gets 401), and
  all six servers report their role's exact count. Raj typed nothing; no literal token anywhere.
* **When a flow containing MCP Tools is saved**, Langflow 1.12.5 moves every non-allowlisted header
  value out of `flow.data` into new Credential globals `MCP_<SERVER>_<HEADER>_<hash>` and stores
  only those names in the flow (`langflow/api/utils/mcp/flow_secrets.py`). At run time the
  server-table config (with the `{{…}}` placeholder) is preferred. Exports therefore carry
  variable names only.
* **Custom-component fields:** `SecretStrInput`/text inputs with `load_from_db: true` and
  `value` = the variable NAME (`TS_APP_TOKEN`, `TS_PO_TOKEN`, …, `TASKSPRINT_API_BASE`); shown in
  the node as a green chip (`06-13`). Serialized: `{"load_from_db": true, "value": "TS_PO_TOKEN",
  "password": true}`. This closes the Phase 01 UNKNOWN "binding syntax in exported JSON".

## Reviewed adapters (06.2) — `components/`

| File | Version / sha256 | Does | Does not |
|---|---|---|---|
| `app_console.py` (`TaskSprintAppConsole`) | 1.0.1 / `4df2640c…` | one fixed `POST {TASKSPRINT_API_BASE}/v1/app/commands`; local verb check (add/list/complete/status, ≤200 chars, one line); https-origin check; 30 s timeout; returns `message [CODE | artifact | request]` | no model, no code execution, no other URL, never echoes the token |
| `run_context.py` (`TaskSprintRunContext`) | 1.0.0 / `1ba2ef5e…` | one `POST /v1/runs` per flow invocation with the role token; `conversation_id = lf-<Playground session id>` so the server namespace is `demo-001:<role>:lf-<session>`; passes the message through unchanged; second output **Run ID** | does not reach MCP Tools (see deviation 1) |

Installed through `POST /api/v1/custom_component` (the compile route behind the editor's
custom-component code editor), which compiled both and returned the node templates placed into
the flows. The editor's own save/check button label was **not observed** in this phase. Static scan of `components/`: no exec/eval/compile-to-execution/importlib/
pickle/subprocess/env reads (the only `compile(` hits are `re.compile`). No candidate code
runs in Langflow: candidates go only to the lab, which sends them to the private runner.

## Checks (06.5) — Playground, workspace `demo-001`

No second workspace exists (`TASKSPRINT_ALLOWED_WORKSPACES` = `demo-001`); Railway is out of
scope, so the checks ran in `demo-001`. No story was recorded or approved; no approval of any
kind was created. Every artifact created is listed under "Reset list" for Phase 11.

| # | Check | Result | Evidence |
|---|---|---|---|
| A1 | TS-30 `add Prepare sprint review` | **PASS** | `Added T003: Prepare sprint review [ADDED …]`; event `evt_8702d63870ae971dba7baad1` actor `application` (`06-11`) |
| A2 | TS-30 `list` | **PASS** | T001, T002, T003, all `[ ]` (`06-12`, `06-28`) |
| A3 | TS-30 `status` | **PASS** | active `cand_561149e5c98bb5b7e8ab7357` sha256 `561149e5…fac1e9b`, revision 0, healthy |
| A4 | TS-30 `complete T001` → FEATURE_UNAVAILABLE | **PASS** | event `evt_01edc15dda115f337b7f01fa` `app.complete FEATURE_UNAVAILABLE`, runner `tasksprint-runner/0.3.0`, 8 ops, tasks_changed 0 |
| P1 | PO: `Prepare the completion story using the current approved product brief.` | **PASS** | tool calls get_sprint_state + 3× search_approved_knowledge (`06-17`); events `evt_626bcfcc041612b1a1088099`, `evt_a9ef31450938f19977843cab`, `evt_db33f67a88dbeadaf4ce4cf4` (`knowledge.search`, actor `product_owner`); story_proposal cites `tasksprint-product-brief` v1.0 §Completion story `daf0f110…`, §Acceptance criteria `c9b07953…`, §Starter `83857dc5…` = the retrieved chunk hashes (`06-18`). Proposal only; unresolved questions listed |
| D1 | Dev: `Load the implementation skill. Read the starter and propose the completion change.` | **PASS** | tools get_sprint_state, list_skills, load_skill, read_candidate, search_approved_knowledge, submit_candidate (`06-20`); `skill_loaded` `evt_a08469ed50b98d89c8f17493` (implement-todo-change **1.1.0**, body `2e86560f…9895a`); `candidate.submit` `evt_bfd4498c6669376d22917bf1` → **`cand_1c9e49bc8de73e1ba06ab786`**, sha256 **`1c9e49bc8de73e1ba06ab78679370f9d0f01bc33944c81b060bf80b08d44689e`**, origin agent-generated, author developer, base = starter (`06-21`). Agent states QA has not verified it (`06-22`) |
| Q1 | QA: `Run the protected application suite for candidate cand_1c9e49bc8de73e1ba06ab786.` | **PASS** (check) — candidate **FAILS** the suite | tools get_sprint_state, read_candidate, run_candidate_tests (`06-24`); event `evt_f51731603db63f92fec0e3c5` `test_run.create fail` actor `qa`; report **`tr_38d1e08a937945f3346b977b`**: candidate sha256 = submitted hash, suite `tasksprint-app-suite/1` `051dfb58…71a9551`, `tasksprint-runner/0.3.0`, 6 cases, failed **TC-01** (`code is COMPLETED`: expected `COMPLETED`, actual `OK`); retention, idempotency, unknown-ID, shape and non-mutation passed. QA report matches the stored report and routes back for one repair (`06-25`, `06-26`) |
| G1 | Each role's calls recorded under its own identity | **PASS** | `scripts/phase06_checks.py` (21 pass, 0 fail): knowledge.search → product_owner/developer; skill_loaded, candidate.submit, load_skill, submit_candidate → developer; run_candidate_tests → qa; app.* → application |
| G2 | No impersonation by changing a field | **PASS** | same script with `--probes` (real MCP SDK + REST): developer → run_candidate_tests / read_test_report `TOOL_NOT_AVAILABLE` (not listed); PO and QA → submit_candidate `TOOL_NOT_AVAILABLE`; developer `read_candidate {acting_as: qa}` and `submit_candidate {role: qa}` → `VALIDATION_ERROR`; REST developer GET `/v1/test-runs/{id}` 403 (`authz.denied` `evt_4df2a8bb1ad8d6cb768f7fc0`), POST `/v1/test-runs` with `X-TaskSprint-Role: qa` 403, with body `role=qa` 403 |
| G3 | Developer sees no instructor fixtures / grader | **PASS (scope-limited)** | developer tools/list = 6 tools, none for tests/reports/fixtures; no fixture is loaded in demo-001; the Developer's reads were the starter only. A fixture-present probe is Phase 09/10 |
| R1 | Export → re-import round trip (REC-04 subset) | **PASS on the same instance** | `--export` → `flows/*.json`; credential scan clean (only `Bearer {token}` in component source); `--dry-run` = keep ×4 (idempotent, no duplicates); `--apply --force` rewrote TS-30 and TS-01 from the exports, read back identical bindings, then ran via `POST /api/v1/run/{id}`: TS-30 `status`/`list` correct; TS-01 retrieved and cited (`evt_911b00cf9b02ae4f889bd732`). Import into a *fresh* instance: NOT RUN |

Command lines (repository root, `source /tmp/ts/env.sh`):

```text
uv run --frozen --no-dev python scripts/import_globals.py --dry-run | --apply        (7 created, 2nd run: keep ×7)
uv run --frozen --no-dev python scripts/import_mcp_servers.py --dry-run | --apply    (PASS ×6 tool counts)
uv run --frozen --no-dev python scripts/import_flows.py --apply --source skeleton     (4 flows, PASS round-trip ×4)
uv run --frozen --no-dev python scripts/import_flows.py --export                      (4 sanitized exports)
uv run --frozen --no-dev python scripts/import_flows.py --dry-run                     (keep ×4)
uv run --frozen --no-dev python scripts/phase06_checks.py --candidate-id cand_1c9e49bc8de73e1ba06ab786 \
    --test-run-id tr_38d1e08a937945f3346b977b --since 2026-10-20T11:40:00Z --probes  (SUMMARY 21 pass, 0 fail)
```

## Gate 06 mapping

| Gate 06 statement | Status |
|---|---|
| Three independent model-driven loops call different permitted tools | **MET** — three Agent flows, three role credentials, three MCP sessions/runs (`run_f267f4cf…` PO, `run_505f6a21…` dev, `run_2c99e58d…` QA); tool sets differ and match the matrix |
| The deterministic app is real | **MET** — TS-30 has no model; commands change/read backend records (events above) |
| No role can impersonate another by changing a field | **MET** — G2 |
| The Developer does not see instructor fixtures or grader files | **MET within current data** — G3 |
| RAG citations, on-demand skill load, actual source/hash, protected tests for that hash | **MET** — P1, D1, Q1 |

## Deviations, findings and decisions for the owner

1. **Per-run budget header cannot reach MCP Tools (BLOCKER for Phase 07).** The MCP Tools
   **Headers** field is a table without an input handle, so the Run Context's run ID cannot be
   wired into `X-TaskSprint-Run`. Langflow pools one MCP session per server URL+headers and keeps
   it for `mcp_session_idle_timeout` = 400 s; the lab binds one server-created run (8 actions,
   90 s) to each MCP session. Consequence observed: a second QA prompt 2 min after the first
   got **`RUN_EXPIRED`** on every call (events `evt_a7892fd8…`, `evt_8969bfa8…`, three attempts —
   Langflow's parse-error retry), and the agent correctly reported BLOCKED (`06-27`). Until the
   pooled session idles out, that role's tools are unusable. Phase 07 must pick one: (a) a trusted
   bounded-toolset component that opens its own MCP session per invocation with the
   `X-TaskSprint-Run` header (A9 `components/bounded_toolset.py`); (b) a lab change: on an expired
   session run, issue a new root run for that session (recorded) — a budget policy change, needs
   approval; or (c) `{{TS_RUN_ID}}` request-variable injection (fragile; not recommended). The
   Run Context runs (`run_b4bdfd51…`, `run_30218c83…`, `run_9b860b3a…`) are recorded but tool
   calls are charged to the per-session run, exactly as PHASE04 deviation 1 described.
2. **Success code `COMPLETED` is not discoverable by the Developer.** The protected suite asserts
   `code == "COMPLETED"` (TC-01), but no knowledge document, skill (1.1.0), grammar note or prompt
   names it; the Developer chose `OK` and said so. With the current kit every first candidate
   fails TC-01 and the repair depends on the relayed report. Owner decision: keep as a teaching
   defect, or state the codes (`COMPLETED`, `TASK_NOT_FOUND`) in a new skill version or brief
   version (either needs a version bump).
3. **Chat history does not contain tool results.** In the follow-up turn the QA agent said it
   could not find its earlier tool calls in the conversation history and withdrew trust in its own
   earlier report. Canonical state must come from tools (Memory & State lesson); note for Phase 07.
4. **Project MCP server `lf-tasksprint`** was created automatically with the project (auth
   type API key, 0 tools because API-created flows have `mcp_enabled: false`). Keep TS-90 off it
   in Phase 09; consider leaving all TaskSprint flows off it.
5. **Auto-created `MCP_*` Credential globals** (six). They hold the header values Langflow scrubbed
   out of flow data. Re-importing an export into a fresh instance needs the MCP servers registered
   first (`import_mcp_servers.py`) and then a save of each flow; verify in Phase 11.
6. **Editor "unsaved changes" after each Playground run** blocked navigation; saved with Ctrl+S.
   The importer's identity check ignores layout and run outputs, so these saves do not cause
   false "differs" results.
7. `import_flows.py --source skeleton` builds everything except the MCP Tools node (its tool list
   is server-refreshed); the MCP nodes were added in the editor and are carried by the exports.
8. App Console 1.0.1 adds Markdown line breaks (the Playground otherwise joins list lines).
9. Developer's `read_test_report` remains excluded (owner decision); QA's tool list includes it.
10. Components have no unit tests in this repo (lfx is not a project dependency); they were
    compiled by the instance and exercised end to end.

## Reset list (artifacts created in `demo-001`, for Phase 11)

Tasks: **T003** "Prepare sprint review". Candidates: **`cand_1c9e49bc8de73e1ba06ab786`**
(agent-generated). Test runs: **`tr_38d1e08a937945f3346b977b`** (fail). Runs: Run Context
`run_b4bdfd512063aab9d68e8cf4829c6444`, `run_30218c83ddf110eb09408b77f86ee7da`,
`run_9b860b3a8228350f0ee7229dd87e5e24`, `run_155316c77a1c7494d87358360921159d`,
`run_8befc109fcf8afec55615337998908db`; MCP-session runs `run_f267f4cf…`, `run_505f6a21…`,
`run_2c99e58d…`, `run_8280a090…` and six probe runs (11:58Z). Events: all `demo-001` events
from 11:46Z on (app, knowledge.search, skill_loaded, candidate.submit, test_run.create,
mcp.tool_call/denied, authz.denied, run.*). Not created: stories, memories, approvals, plans,
releases, drills. Langflow: Playground sessions "Default Session" in four flows plus
`phase06-reimport-check` / `phase06-reimport-check-po` (API runs).

## Screenshots (`docs/screenshots/`, also in `TaskSprint_Build_Kit/docs/screenshots/`)

06-01-global-variables-created, 06-02-add-mcp-server-json-tab, 06-03-add-mcp-server-http-tab,
06-04-header-value-variable-picker, 06-05-header-value-variable-chip, 06-06-header-bearer-placeholder,
06-07-product-owner-server-filled, 06-08-product-owner-server-2-tools, 06-09-six-mcp-servers-registered,
06-10-ts30-canvas, 06-11-ts30-add, 06-12-ts30-list-status-complete, 06-13-ts01-skeleton-role-token-chip,
06-14-editor-mcp-sidebar, 06-15-mcp-tools-node-dropped, 06-16-ts01-wired-toolset, 06-17-ts01-po-tool-calls,
06-18-ts01-po-citations, 06-19-ts02-wired-toolset, 06-20-ts02-dev-tool-calls,
06-21-ts02-dev-candidate-submission, 06-22-ts02-dev-not-verified, 06-23-ts03-wired-toolset,
06-24-ts03-qa-tool-calls-report, 06-25-ts03-qa-failed-criterion, 06-26-ts03-qa-next-step,
06-27-ts03-run-expired-pooled-session, 06-28-ts30-list-after-reimport. Global Variables values are
masked; no token appears in any screenshot.

## Manual click path (human equivalent)

1. Profile → **Settings** → **Global Variables** → **Add New**: `TASKSPRINT_API_BASE`, type
   **Generic**, value = lab origin; then each `TS_*_TOKEN` as **Credential** (paste privately).
2. **Settings** → **MCP Servers** → **Add MCP Server** → tab **Streamable HTTP/SSE** →
   **Name** `tasksprint-product-owner`, **Streamable HTTP/SSE URL** `<lab>/mcp`, **Headers**
   `Authorization` = `Bearer {{TS_PO_TOKEN}}` (type it; do not use the globe chip), **+**,
   `X-TaskSprint-Workspace` = `demo-001` → **Add Server**. Expect "2 tools". Repeat per role.
3. Create a project `TaskSprint` and a flow `TS-01 Product Owner` (done by API in this phase; the
   project-creation clicks were not observed) and rename the flow by clicking its name (Phase 01).
4. Sidebar footer **New Custom Component** → open its code (hover toolbar **Code**) → replace with
   `components/run_context.py` → save (button label not observed in Phase 06); set **Role token**
   with the globe → `TS_PO_TOKEN`.
5. Add **Chat Input**, **Agent**, **Chat Output**. Wire Chat Input → Run Context **Message**;
   Run Context **Message** → Agent **Input**; Agent **Response** → Chat Output.
6. Agent: **Language Model** Anthropic `claude-sonnet-5-5`; **Agent Instructions** = paste
   `prompts/product_owner.md`; **Parameters**: Max Iterations 8, Calculator off, Current Date off.
7. Left rail **MCP** → drag `tasksprint-product-owner` onto the canvas (creates **MCP Tools** with
   the server selected) → hover → **Tool Mode** on → drag **Toolset** to Agent **Tools**. Ctrl+S.
8. **Playground** → send the check prompt. Repeat 3–8 for Developer (`TS_DEV_TOKEN`,
   `prompts/developer.md`) and QA (`TS_QA_TOKEN`, `prompts/qa.md`).
9. TS-30: New Flow `TS-30 To-do App`; custom component `components/app_console.py` (token field
   is pre-bound to `TS_APP_TOKEN`, base to `TASKSPRINT_API_BASE`); Chat Input → App Console
   **Command**; **Result** → Chat Output; Playground: `add …`, `list`, `status`, `complete T001`.

## Next action

Owner: review this report and decide deviation 1 (option a recommended) and deviation 2. Then
Card 07. The orchestrator pushes `feature/phase-06-langflow`.
