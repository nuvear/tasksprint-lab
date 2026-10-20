# Phase 07 report: Sprint Room, bounded toolset and harness proofs

**Date:** 20 October 2026, 12:15–12:50 UTC. **Instance:** Langflow 1.12.5
(`https://langflow-railway-production-f493.up.railway.app`), owner's Chrome signed in as admin by
the owner; lab `https://tasksprint-lab-production.up.railway.app` (GATE 05, unchanged).
**Branch:** `feature/phase-07-sprint-room` from `74744f2` (not pushed). **Gate:** GATE 07 evidence
below. Stop here.

**Not touched:** Railway (no variable, deploy or service change), Langflow Postgres, the A2A flag,
`nuvear/langflow-railway`, TS-00 / TS-00T / TS-30, globals, MCP server registrations, Model
Providers, API keys. No TS-20, no TS-90. No secret value was printed, typed or shown on screen.

## Owner decisions applied

* **Deviation 1 → option (a):** a trusted **bounded toolset** component replaces the native MCP
  Tools node. The lab's per-run budget policy is unchanged.
* **Deviation 2 → document the return-code contract:** product brief **1.1** and skill
  `implement-todo-change` **1.2.0** (see "Content change"). **The live lab still serves brief 1.0
  and skill 1.1.0 until it is redeployed** (all live checks below ran against those versions).

## Component approach

`components/bounded_toolset.py` (`TaskSprintBoundedToolset`, `bounded_toolset/1.0.0`, sha256
`05242b55…`) and `components/run_context.py` **1.1.0** (sha256 `eb1aeda8…`), installed through the
compile route `POST /api/v1/custom_component` like Phase 06.

* **Run:** the Run Context still does exactly one `POST /v1/runs` per flow invocation with the role
  token. New in 1.1.0: a third output **Run** (Data: run id, role, depth, budgets, deadline) and
  lineage — when the flow's session id is itself a server-issued run id (`^run_[0-9a-f]{32}$`), the
  run is created as that parent's child (`parent_run_id`). All three outputs use `group_outputs`
  (otherwise the editor shows one output and hides the other edges).
* **Toolset:** input **Run** ← Run Context **Run**; **Role** (dropdown fixes the allowlist);
  **Role token** = the same Credential global; output **Toolset** (`component_as_tool`, type
  `Tool`, `cache=False`) → Agent **Tools**. At build time it lists the role's tools over MCP and
  exposes only the intersection with a fixed per-role allowlist (= the lab's Phase 04 visibility
  matrix, pinned by `tests/unit/test_components_static.py`).
* **MCP client:** the official `mcp` SDK that ships with Langflow 1.12 (`mcp>=1.17,<2`), imported
  inside the component: `streamable_http_client` + `create_mcp_http_client` when present, else
  `streamablehttp_client`. **No hand-written JSON-RPC client was needed.** One fresh Streamable-HTTP
  session per tool call (initialize → `tools/call` → close/DELETE), every request carrying
  `Authorization`, `X-TaskSprint-Workspace` and `X-TaskSprint-Run` = the invocation's run. The lab
  therefore charges the invocation's own run and never creates a pooled per-session run.
* **Harness (counted outside the model, limits are inputs, never tool arguments):** actions =
  tool calls + delegations (not model iterations) ≤ **Max tool actions** (default 8, clamped 1–8);
  deadline = min(invocation start + **Invocation deadline** (90 s specialist / 180 s coordinator),
  the lab run's `deadline_at`); per-call timeout 30 s; one retry for a transient *read* transport
  failure, none for writes; the same call with the same arguments a third time → `NO_PROGRESS`;
  after a terminal condition (budget, deadline, timeout, lab `BUDGET_EXHAUSTED` / `RUN_EXPIRED` /
  `RUN_NOT_ACTIVE` …) every later call is refused with `HARNESS_STOPPED` — this is the
  "cancelled" state: nothing more is sent under that invocation. All refusals and lab errors are
  returned as structured JSON (`{"error": {code, message, source}}` + a `harness` snapshot), never
  raised.
* **Delegations (coordinator only):** three HandleInputs accept exactly one Run Flow tool each and
  re-expose it under a fixed name and purpose: `ask_product_owner` (TS-01), `ask_developer`
  (TS-02), `ask_qa` (TS-03). The build fails closed if a slot carries any other flow's tool
  (name/description check), or if a non-coordinator toolset has a delegation wired. Each
  delegation: counts one action, is **charged at the lab** first as one action of the parent run
  (`GET /v1/state` with `X-TaskSprint-Run` = parent, which spends one action of the run and its
  tree; refused calls are recorded by the lab as `run.action` denials), checks depth
  (`depth + 1 ≤ 2`), the repair limit (`ask_developer` / `ask_qa` ≤ 1 + 1 repair per coordinator
  turn), `ask_product_owner` ≤ 2, and runs under min(90 s, remaining parent time).
* **Lineage:** Run Context **Run ID** → each Run Flow's **Session ID** (not a tool argument). The
  child flow runs in session `run_<parent>`, so its Run Context creates a child run: depth 1,
  shared 24-action tree, deadline capped at the parent's. Evidence: every delegation below has a
  child `run.create` with `parent_run_id` = the coordinator run.
* **Session namespaces:** Playground **Default Session** id = the flow id, so the coordinator
  namespace is `demo-001:coordinator:lf-ec5b5dba-d7d2-4aeb-899c-016a3f66b4eb`; a new Playground
  conversation "New Session 0" → `demo-001:coordinator:lf-New-Session-0`; an API `session_id`
  `x` → `lf-x`; a delegated specialist → `demo-001:<role>:lf-run_<parent run id>` (visible as
  sessions named `run_…` in TS-01/TS-03 Playgrounds). Preference memory is keyed by the
  coordinator credential's principal, not by the session, which is why a new conversation sees it.

## Flows (project `TaskSprint` `9c4defb4-3457-4e34-9668-b940fadb030f`)

| Flow | ID | Wiring |
|---|---|---|
| `TS-01 Product Owner` | `da674f03-2861-4b3f-9f25-129bb86a588f` (kept) | Chat Input → Run Context 1.1.0 (`TS_PO_TOKEN`) → Agent → Chat Output; Run → Bounded Toolset (product_owner, `TS_PO_TOKEN`, 90 s) → Agent Tools. MCP Tools node removed |
| `TS-02 Developer` | `9610ee79-66ce-4f92-b304-44d9e5c8be38` (kept) | same, developer / `TS_DEV_TOKEN` |
| `TS-03 QA` | `8906e4df-4fe3-489f-b30b-d5e57230459c` (kept) | same, qa / `TS_QA_TOKEN` |
| **`TS-10 Sprint Room`** | **`ec5b5dba-d7d2-4aeb-899c-016a3f66b4eb`** (new) | Chat Input → Run Context (`TS_COORD_TOKEN`) → Agent (`prompts/coordinator.md` sha256 `63af5d81…`, `claude-sonnet-5-5`, Max Iterations 8, Calculator off, Current Date off) → Chat Output; Bounded Toolset (coordinator, 180 s) → Agent Tools; three **Run Flow** (Beta) nodes in Tool Mode, Flow Name `TS-01 Product Owner` / `TS-02 Developer` / `TS-03 QA` (ids above), Session ID ← Run ID, Toolset → the matching toolset slot. No Run Flow is wired to the Agent directly |

Built by `scripts/phase07_flows.py --apply` (Run Flow nodes selected and switched to Tool Mode through
`POST /api/v1/custom_component/update`, the editor's own refresh route; templates from the instance).
The Coordinator has 7 MCP tools + 3 delegations = 10 tools; it has no tool that can select a flow,
and TS-90/TS-20 do not exist. Exports: `flows/10_sprint_room.json` (new), `flows/0{1,2,3}_*.json`
(updated), Phase 06 versions kept as `flows/0{1,2,3}_*.phase06.json`. `import_flows.py --export`
scan clean; `--dry-run` → keep ×5; `phase07_flows.py --dry-run` → keep ×4. On re-import into
another instance `import_flows.py` now remaps each Run Flow's `flow_id_selected` by name and
refuses any target other than TS-01/02/03 (fresh-instance import NOT RUN).

## Live checks (workspace `demo-001`, current lab = brief 1.0 / skill 1.1.0)

| # | Check | Result | Evidence |
|---|---|---|---|
| T1 | Specialist re-checks with the bounded toolset (Card 06 prompts, API runs) | **PASS** | QA `tr_411ce3d84698a8976ccc799a` (pass, `cand_af9914e7…`) run `run_3b53406e…`; PO 3× `knowledge.search` run `run_1fd7c9fe…` with brief v1.0 citations; Dev `skill_loaded` `evt_45591aae…` (1.1.0), `candidate.submit` **duplicate** `evt_9fb3165e…` (same bytes as `cand_1c9e49bc…`, code `OK` again — see "Content change") |
| T2 | Second prompt ≥ 2 min later in the same session: no `RUN_EXPIRED`, new run per invocation | **PASS** | session `phase07-specialist-qa`: 12:44:03 run `run_3b53406ea0bb228a1b413308a4f95b4d`, 12:46:23 run `run_d956c6f63c9c49d5388763cc7d3c9c29`, tests `tr_c48a817ea9766cc038a7e3a6` (fail) + `tr_b6dbd8129eb6e986d395b7ee` (pass); 0 `RUN_EXPIRED` events; tool calls `source: header` (`07-12`, `07-13`) |
| T3 | Tool calls charged to the Run Context run (no pooled-session run) | **PASS** | first probe: `run.create` `evt_b9f270f9…`, then `read_test_report` actions_used 1, `get_sprint_state` 2 under the same `run_7c571311…` |
| 07.3a | Ask the team to propose the story; scope stays pending | **PASS** | coordinator `run_d6b7d44e8a8d79b7cd258f0e209a3a6b`: `read_preferences`, `get_sprint_state`, `ask_product_owner` → PO child `run_2f7dfdaf…` (depth 1, parent = coordinator) 3× `knowledge.search` with v1.0 citations; `record_story` rejected once (`VALIDATION_ERROR`, evidence-ref pattern, `evt_f2833fe0…`), then **ST-001** `story.create` `evt_2bc91b77e347e66431543c2d`: PLANNED, `scope_confirmed: false`, revision 1. No confirmation attempted (`07-04`, `07-05`) |
| 07.3b | Save "concise release notes" as a selected presentation preference | **PASS** | `memory.save` `evt_c106f6336f356e8de3c6c71c` `release_notes_style = concise`, expires 2026-10-27T12:29:09Z, source `save_preference:coordinator:req_50ad9d1c…` (`07-06`) |
| 07.3c | New Playground conversation: sprint status and note-format preference match `GET /v1/state` and `GET /v1/memory` | **PASS** | "New Session 0", run `run_f8e8702037dbc7cdc818d30028f93fac`: `get_sprint_state` + `read_preferences` only; answer = SPRINT-1 rev 1, ST-001 PLANNED rev 1 unconfirmed, candidate null, repair_count 0, active release `cand_561149e5…` rev 0, `release_notes_style` concise exp. 2026-10-27 — identical to `scripts/phase07_checks.py state` / `memory` (`07-07`) |
| 07.4a | Failing read changes the next action and is recorded | **PASS** | `read_test_report tr_000000000000000000000000` → `TEST_RUN_NOT_FOUND`, event `evt_885f2e7a70d28555f340ee8b` (outcome error); the coordinator did **not** delegate the repair (no child run), stopped and named the missing evidence (`07-08`, `07-09`) |
| 07.4b | Insufficient budget terminates/escalates with a recorded reason | **PASS** | test setting: API tweak `max_actions = 2` on the toolset (saved flow stays 8). Session `phase07-test-budget-2c`, run `run_cdb21d9408ce17db1b1593c67a2b783a`: actions 1–2 at the lab, 3rd (`ask_qa`) refused `BUDGET_EXHAUSTED` source harness, no child run; recorded in Langflow message `5818078c-f577-482d-8591-f619a5bcc4a6` (tool output) and the lab shows exactly 2 actions; the agent escalated. Earlier variant `-2b` (parallel calls) also allowed exactly 2 (delegation + `read_preferences`) and refused the 3rd |
| 07.4b′ | Parent-turn tree budget (24) stops descendants, recorded by the lab | **PASS (natural)** | repair run below: QA child `run.action` **BUDGET_EXHAUSTED** `evt_e87df79eee194c99bd3caafb`, coordinator `run.action` **BUDGET_EXHAUSTED** `evt_b82a9ea6ba09d5d65f4b07ac`; tree = coordinator 7 (incl. 4 delegation charges) + dev 6 + QA 3 + dev 6 + QA 2 = 24 |
| 07.4c | Timed-out work cannot commit later — harness | **PASS** | test setting: tweak `invocation_timeout_s = 5` on TS-02. Run `run_b731a2c8efea8bf360f35bf6b304249e`: reads ran, `submit_candidate` refused `INVOCATION_DEADLINE_PASSED` (Langflow message `cc227974-0c2b-4f74-9fe0-37438157fdb2`); no `candidate.submit` event exists for that run although its lab deadline (12:37:02Z) had not passed |
| 07.4c′ | Expired run cannot commit later — lab | **PASS** | `scripts/phase07_checks.py late-write --run-id run_85a3c3e963e30f3607814d345bdc3978` (expired coordinator run) → `save_preference` `isError` **RUN_EXPIRED**, request `req_917c1dc4101ad2ce4c35d1a7`, memory unchanged |
| 07.4d | One repair cycle, then stop (no unbounded Dev/QA loop) | **PASS** | "New Session 2", coordinator `run_a1b79b91af531e1925f516d073c279e0`: `ask_developer` → dev `run_c1782139…` `skill_loaded`, `candidate.submit` **`cand_7a978f5b7823d838045cbf8e`** (`evt_b92613bc…`); `ask_qa` → QA `run_64311671…` **`tr_35be6859e441b41be9468b03` fail** TC-01 (expected `COMPLETED`, actual `OK`); coordinator `read_test_report` (`evt_08a42e1c…`) and relayed the assertion → dev `run_2fd81518…` **`cand_af9914e75be0ca672c26ce3f`** (base = `cand_7a978f5b…`, `evt_7b26a9f0…`); `ask_qa` → QA `run_32132b45…` **`tr_b2139a09ad81f4d67b6ef3a1` pass** (27/27; report re-read by API, hashes match). Then the tree budget stopped the turn (07.4b′); the coordinator reported it could not verify the pass itself (`07-10`, `07-11`) |
| 07.4d′ | A further developer delegation in the same turn is refused | **PASS** | session `phase07-test-repair-limit-2`, run `run_a881cd87410f2f14712f1402fa40a467`: `ask_developer` A and B ran (child runs `run_edb4a3de…`, `run_a41c02c4…`), C refused **REPAIR_BUDGET_EXHAUSTED**; the agent escalated |
| 07.4e | No-progress stop | **PASS** | session `phase07-test-repair-limit`, run `run_ad0b522d…`: the identical `ask_developer` request a third time → **NO_PROGRESS**, never reached the Developer |

Command lines (repository root, `source /tmp/ts/env.sh`):

```text
uv run --frozen --no-dev python scripts/phase07_flows.py --dry-run | --apply [--force] [--only ...]
uv run --frozen --no-dev python scripts/import_flows.py --export | --dry-run
uv run --frozen --no-dev python scripts/phase07_checks.py events --since <ISO> | state | memory | runs
uv run --frozen --no-dev python scripts/phase07_checks.py late-write --run-id <expired coordinator run>
uv run --frozen pytest -q tests/unit tests/security tests/integration tests/protocol
```

API runs used `POST /api/v1/run/{flow_id}` with the bootstrap key (owner-approved in Phase 06) and
`tweaks` for the two test settings; Playground checks were typed in the owner's Chrome.

## Budgets as rehearsed

| Budget | Value | Enforced by |
|---|---|---|
| Tool actions per agent invocation | 8 (test setting 2) | toolset (local, before sending) and lab run (`max_actions` 8) |
| Actions per parent turn incl. descendants | 24 | lab run tree (child runs share the root); delegations charged to the parent |
| Delegation depth | ≤ 2 (observed 1) | toolset check + lab `DELEGATION_DEPTH_EXCEEDED` on child creation |
| Specialist / parent deadline | 90 s / 180 s (test setting 5 s) | toolset deadline = min(local, lab `deadline_at`); lab rejects after deadline |
| Per tool call | 30 s (lab's own tool timeout: default 20 s) | toolset; `TOOL_TIMEOUT` stops the invocation |
| Repair cycles | 1 per coordinator turn (`ask_developer`, `ask_qa` ≤ 2 each) | toolset; across turns: the lab story `repair_count` (MAX_REPAIRS 1) once scope is confirmed (Phase 09) |
| Read retry / write retry | 1 / 0 | toolset |
| No progress | 3rd identical call stops | toolset |
| Agent Max Iterations | 8 (native) | Langflow Agent — model iterations, separate from actions |

Observed durations: repair turn 12:37:41–12:39:18 (≈ 97 s, under 180 s); specialist delegations
about 2–25 s. Token usage: Playground header shows e.g. 6.9K tokens / 7.1 s for the resume turn; not
collected per run (`null`, not exported by the run API used).

## Content change (owner decision 2) — **lab redeploy required**

* `knowledge/01_product_brief.md` **1.0 → 1.1** (effective 2026-10-20, file sha256 `3267021c…`): new
  section **Completion result contract** (`{ok, code, tasks}`; known incomplete → `COMPLETED`;
  already completed → `COMPLETED`, records unchanged, idempotent; unknown → `TASK_NOT_FOUND`,
  records unchanged; chunk sha256 `ea64b260…`). Edited in place with a version bump, the lab's
  convention: the lab volume keeps the 1.0 rows (append-only) and only the current file version is
  searched, so there is no conflicting-evidence abstention (new test).
* `skills/implement-todo-change/SKILL.md` **1.1.0 → 1.2.0** (body sha256 `894af05f…`): step 4
  states the same return-code contract and references brief 1.1. No solution text.
* Tests updated: retrieval/protocol citation version 1.1; skill VERSIONS 1.2.0, old 1.0.0/1.1.0
  not served; bump test keeps old rows; new tests for the contract in brief and skill and for the
  1.0 → 1.1 append.
* **The lab must be redeployed for these versions to be served:** merge this branch to the lab
  repository's main → Railway rebuilds `tasksprint-lab`. Until then the live lab serves brief 1.0
  and skill 1.1.0 — T1 shows the Developer still choosing `OK`. After the redeploy, re-run T1 (Dev
  + QA) and expect `load_skill` 1.2.0 (hash `894af05f…`) and brief 1.1 citations. The orchestrator
  does the merge/push; nothing was pushed here.

## Tests

`uv run --frozen pytest -q tests/unit tests/security tests/integration tests/protocol`:
**`471 passed in 19.55s`** (Phase 06: 463; +5 component static checks, +2 brief, +1 skill).

## Deviations, findings and decisions for the owner

1. **Delegated specialist output also appears in the Sprint Room Playground.** Langflow shows the
   child flow's Chat Output message in the parent session (e.g. the PO's proposal), before the
   coordinator's own answer; the API run output concatenates them. It is display only (the child's
   messages are stored under its own `run_…` session in the child flow). Classroom note.
2. **The coordinator ran parallel tool calls** in one step (07.4b variant). Counting is correct
   (single event loop, counter incremented before any await), but results can return out of order;
   the harness block is a snapshot and is labelled as such since this phase.
3. **Repair limit is per coordinator turn.** A new turn could request another repair; the durable
   cross-turn limit is the lab story `repair_count` (MAX_REPAIRS 1), which only applies once the
   story is in the stage machine — that needs human scope confirmation (Phase 09). The repair
   rehearsal therefore ran in a test setting with ST-001 still PLANNED; the candidates are not
   linked to the story.
4. **Lab-side "late commit" window.** The lab checks the run when an action is admitted, not again
   at the end of a long operation (e.g. a test run already admitted completes even if the deadline
   passes meanwhile). A9 asks for a re-check "immediately before a transaction". Recommend (needs
   approval, lab change + redeploy): re-check `_require_live` inside the write transaction of
   `story.create`, `story.transition`, `memory.save`, `candidate.submit` and `test_run.create`.
5. **Agents distrust their own earlier reports** (Phase 06 finding 3 again): in T2 the QA agent
   disowned the valid `tr_411ce3d8…` because chat history has no tool results, and re-ran the
   suite (`tr_b6dbd812…`). Suggest a QA/coordinator prompt line in a later phase: "verify earlier
   evidence with read_test_report / read_recent_events, do not discard it".
6. **Delegation charge has no lab event of its own** (a successful REST read with a run header is
   not logged); it is visible as the `actions_used` gap and in the tree total. A dedicated lab
   `delegation` event would need a lab change.
7. **Developer works without confirmed scope.** Its prompt/skill say missing prerequisites cause
   needs-human-review, but it submitted candidates with ST-001 unconfirmed (T1, 07.4d). The lab
   does not block submission (only transitions). Owner decision for Phase 09: accept (candidates
   are not stage changes) or add a lab precondition.
8. `TS-10` tweak node ids change when `phase07_flows.py --force` rebuilds the flow; the final ids are
   `TaskSprintBoundedToolset-YSLSR` (TS-10), `-Quw6x` (TS-02), `-UUfE5` (TS-03).
9. "Leave site?" after Playground runs (Phase 06 item 6) recurs; I discarded the editor's local
   state each time (the server copy is authoritative and matches the exports).

## Reset list (artifacts created in `demo-001` in Phase 07, for Phase 11)

Stories: **ST-001** (PLANNED, unconfirmed, created by coordinator). Memory: coordinator
`release_notes_style = concise` (expires 2026-10-27). Candidates: `cand_7a978f5b7823d838045cbf8e`,
`cand_af9914e75be0ca672c26ce3f` (agent-generated; `cand_1c9e49bc…` re-submitted as duplicate).
Test runs: `tr_35be6859e441b41be9468b03` (fail), `tr_b2139a09ad81f4d67b6ef3a1` (pass),
`tr_411ce3d84698a8976ccc799a` (pass), `tr_c48a817ea9766cc038a7e3a6` (fail),
`tr_b6dbd8129eb6e986d395b7ee` (pass). Runs: coordinator `run_084cb429…`, `run_d6b7d44e…`,
`run_85a3c3e9…`, `run_f8e87020…`, `run_88f3cc42…`, `run_cc52aa33…`, `run_3de69e21…`,
`run_cdb21d94…`, `run_a1b79b91…`, `run_ad0b522d…`, `run_a881cd87…`; children/specialists
`run_7c571311…`, `run_2d27bf52…`, `run_2f7dfdaf…`, `run_71653c1c…`, `run_b731a2c8…`, `run_c1782139…`,
`run_64311671…`, `run_2fd81518…`, `run_32132b45…`, `run_82fdc640…`, `run_35725c1c…`, `run_edb4a3de…`,
`run_a41c02c4…`, `run_3b53406e…`, `run_1fd7c9fe…`, `run_0a4b9a58…`, `run_d956c6f6…`. Events: all
`demo-001` events from 12:22Z on. Not created: approvals, plans, releases, drills, scope
confirmations, transitions. Langflow: TS-10 sessions Default Session, New Session 0/1/2,
`phase07-lineage-probe-1`, `phase07-test-budget-2`, `-2b`, `-2c`, `phase07-test-repair-limit`,
`-repair-limit-2`; child sessions `run_…` in TS-01/02/03; API sessions `phase07-qa-probe-1`,
`phase07-specialist-{qa,po,dev}`, `phase07-test-timeout-dev`.

## Screenshots (`docs/screenshots/`, also in `TaskSprint_Build_Kit/docs/screenshots/`)

07-01-ts03-bounded-toolset-wired, 07-02-ts03-wiring-overview, 07-03-ts10-sprint-room-canvas,
07-04-ts10-po-cited-proposal, 07-05-ts10-story-recorded-scope-pending, 07-06-ts10-preference-saved,
07-07-ts10-new-session-resumes-from-state, 07-08-failing-read-changes-next-action,
07-09-failing-read-structured-error, 07-10-repair-cycle-evidence,
07-11-repair-cycle-pass-and-tree-budget-stop, 07-12-ts03-first-prompt-own-run,
07-13-ts03-second-prompt-no-run-expired. Only variable-name chips appear; no token on screen.

## Manual click path (human equivalent)

1. Specialist flow (e.g. TS-03): select the **MCP Tools** node → Delete. Open the Run Context
   node's code (**Code**) and replace it with `components/run_context.py` 1.1.0 (check & save);
   the node now shows three outputs **Message**, **Run ID**, **Run**.
2. Sidebar footer **New Custom Component** → **Code** → paste `components/bounded_toolset.py` → save.
   Set **Role** (`qa`), **Role token** with the globe → `TS_QA_TOKEN`. Leave the three **Run Flow:**
   inputs empty (they are hidden by the setup script on specialists).
3. Wire Run Context **Run** → Toolset **Run**; Toolset **Toolset** → Agent **Tools**. Ctrl+S.
4. TS-10: **New Flow** `TS-10 Sprint Room`: Chat Input → Run Context (`TS_COORD_TOKEN`) **Message** →
   Agent **Input**; Agent **Response** → Chat Output. Agent: model `claude-sonnet-5-5`,
   **Agent Instructions** = `prompts/coordinator.md`, **Parameters**: Max Iterations 8, Calculator
   off, Current Date off.
5. Add a Bounded Toolset: **Role** `coordinator`, **Role token** `TS_COORD_TOKEN`; in the node's advanced settings
   (label not verified in this phase) set **Invocation deadline (s)** 180. Run Context **Run** → Toolset **Run**; Toolset → Agent **Tools**.
6. Search **Run Flow** (Beta) → drag three onto the canvas. For each: **Flow Name** → select
   `TS-01 Product Owner` (then `TS-02 Developer`, `TS-03 QA`); hover toolbar → **Tool Mode** on
   (node shows **Actions** `TS-01-PRODUCT-OWNER_TOOL` and output **Toolset**); in the advanced settings show
   **Session ID** (the setup script makes it visible); wire Run Context **Run ID** → **Session ID**; wire **Toolset** → the toolset input
   **Run Flow: TS-01 Product Owner** (resp. TS-02, TS-03). Do not wire a Run Flow to the Agent. Ctrl+S.
7. **Playground**: ask for the story; save a preference; **+** for a new session and ask for status.

## Next action

Owner: review; approve or decline finding 4 (lab re-check before commit) and finding 7. The
orchestrator merges `feature/phase-07-sprint-room` to the lab repository's main so Railway rebuilds
the lab with brief 1.1 / skill 1.2.0, then re-runs T1. Then Card 08.
