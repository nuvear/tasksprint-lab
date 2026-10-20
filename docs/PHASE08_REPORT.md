# Phase 08 report: Production Manager and genuine A2A (INTERIM — stopped for lab redeploy)

**Date:** 20 October 2026, 13:00–13:35 UTC. **Instance:** Langflow 1.12.5
(`https://langflow-railway-production-f493.up.railway.app`), owner's Chrome signed in as admin by the
owner; lab `https://tasksprint-lab-production.up.railway.app` (serves brief 1.1 / skill 1.2.0, lab
code = Phase 07). **Branch:** `feature/phase-08-a2a` from `4c9f9f1` (not pushed).
**Gate:** GATE 08 **NOT YET** — **redeploy needed before live A2A assessment** (see "Stop point").

**Not touched:** Railway (no variable/deploy/service change by this phase; the A2A flag was set by the
orchestrator before it started), Langflow Postgres, `nuvear/langflow-railway`, TS-01/02/03/30, MCP
server registrations, Model Providers, TS-90 (not created). No secret value was printed, typed or shown.

## 1. A2A enabled — proof (before any change)

* `GET /api/v1/config` → `"a2a_enabled": true` (Phase 00: false).
* `GET /api/v1/a2a/agents` (bootstrap key) → `200 []`.
* TS-30's Agent pane shows the **Serve as an A2A agent** toggle with no "A2A is turned off" banner (`08-04`).

## 2. Lab: Operations surface for the assessment (code done; **not yet deployed**)

Lab 0.5.0 (`services/lab/release_plans.py`, `a2a_exchanges.py`, migration 0003):

| Route / tool | Behaviour |
|---|---|
| `GET /v1/readiness` / `get_release_readiness` (operations) | Computed from evidence only: candidate integrity; newest (or named) **passing protected report for the exact hash under the current suite hash**; `differs_from_active`; **agent-system manifest = NOT_QUALIFIED** until Phase 10 (fail closed; `qualified_agent_manifest()` returns None); incident on target; current release revision, baseline, rollback availability. Records `release.readiness` and returns `readiness_event_id`. Deploy `READY`/`BLOCKED` + blocking gates |
| `POST /v1/release-plans` / `create_release_plan` (operations) | Args `action` deploy/rollback, `candidate_id`, optional `app_test_run_id`; server binds environment `demo-production`, target/current hash, expected release revision, evidence IDs (test report, manifest, baseline release id), 15-min expiry, `plan_sha256` over the canonical fields (schema `release-plan.schema.json` 1.0, validated in tests). State PLANNED → AWAITING_APPROVAL in one transaction (two events). **Deduplicated**: an identical live plan is returned with `created: false`. Deploy refused `RELEASE_NOT_READY` + blocking gates (today always `agent_system_manifest`); rollback only to the recorded baseline |
| `GET /v1/release-plans/{id}` / `read_release_plan` (operations; REST also human_approver) | Canonical plan, integrity re-check, state, computed `effective_state` (EXPIRED after expiry), human-review preview. No mutation |
| `execute_approved_plan` | Unchanged: **NOT_IMPLEMENTED until Phase 09**; never executes |
| `POST /v1/a2a-exchanges` (coordinator; no MCP tool) / `GET /v1/a2a-exchanges/{id}` (coordinator, instructor, evaluator) | Append-only redacted exchange record: validates the carried payload against `contracts/handoff-task.schema.json`, derives task/context/artifact/message IDs from the returned Task itself, checks the `tasks/get` read-back, links Operations runs created as children of the coordinator run with their own tool trace, verifies every quoted `plan_/evt_/tr_/cand_` ID (`exists: false` flags an invented one), marks a record made after the parent run's deadline |
| **Commit-time run re-check** (owner-approved Phase 07 finding 4) | `runs.require_live_at_commit` inside the write transaction of story create/transition, memory save, candidate submit, **test run** (the protected-suite module is not edited — its bytes are the suite hash — its write transaction is wrapped), app completion, release plan. A result arriving after deadline/stop/cancel fails with `RUN_EXPIRED`/`RUN_NOT_ACTIVE` "(re-checked at commit; nothing was written)" |

Image: `Dockerfile.lab` now also copies `contracts/handoff-task.schema.json` (`.dockerignore` re-includes it).

Tests: `uv run --frozen pytest -q tests/unit tests/security tests/integration tests/protocol` →
**`496 passed in 21.16s`** (Phase 07: 471; new `test_release_plans.py` 11, `test_a2a_exchanges.py` 8,
`test_commit_recheck.py` 4, static component checks +2; the protocol test for the Operations tools now
expects real readiness/plan results and NOT_IMPLEMENTED only for execution; migration list 1–3).

## 3. TS-20 Production Manager (08.1)

`TS-20 Production Manager` **`489890aa-4bd0-4641-b669-070f10e0922b`**, project TaskSprint, built by
`scripts/phase08_flows.py --apply --only ts20`: Chat Input → **Run Context 1.2.0** (`TS_OPS_TOKEN`) →
Agent (`prompts/operations.md` sha256 `041b0871…`, `claude-sonnet-5-5`, Max Iterations 8, Calculator off,
Current Date off) → Chat Output; **Bounded Toolset 1.1.0** (role `operations`, `TS_OPS_TOKEN`, 90 s,
delegation/peer slots hidden) → Agent Tools (`08-06`). Operations-only tools = the lab's operations
matrix (12). Session namespace: Playground `demo-001:operations:lf-<flow id>`; over A2A
`demo-001:operations:lf-a2a-run_<coordinator run>` (child run) or `lf-<ns uuid>:<contextId>` (root run).

## 4. Publication and Agent Card (08.3) — A2A-01 **PASS**

UI: TS-20 → rail **Agent** → **Serve as an A2A agent** on → **Save** → **Live** (`08-07`, `08-08`); the
save set `flow_type=agent`, `a2a_enabled=true`. Card (`scripts/phase08_checks.py card`, `08-11`), fetched
**without and with** `x-api-key` → both `200`, identical:

| Field | Value |
|---|---|
| `protocolVersion` | **`0.3.0`** (the installed server speaks JSON-RPC 0.3 via the a2a-sdk compat layer; not renamed 1.0) |
| `url` | `http://langflow-railway-production-f493.up.railway.app/api/v1/a2a/489890aa-4bd0-4641-b669-070f10e0922b/jsonrpc` (**http** — see finding 1) |
| `preferredTransport` | `JSONRPC` |
| `securitySchemes` / `security` | `apiKey`: `{"type":"apiKey","in":"header","name":"x-api-key"}` / `[{"apiKey": []}]` |
| skills | one: id = flow id, name `TS-20 Production Manager`, tags `["langflow"]`, in/out `application/json`, inputSchema `input_value`, `session_id` |
| capabilities | `streaming: true`, `pushNotifications: true`; `version` `1.12.5` |

Card URL (pane / `cardUrl`): `<base>/api/v1/a2a/<flow id>/.well-known/agent-card.json`. JSON-RPC methods
served: `message/send`, `message/stream`, `tasks/get`, `tasks/resubscribe` (+ cancel/push config).

## 5. Authenticated execution (08.4) — A2A-03 **PASS**

**Key path taken: script, never on screen.** `scripts/create_a2a_key.py --apply` (bootstrap key, same
route the Settings page loads/creates with: `GET/POST /api/v1/api_key/`): created key
`tasksprint-a2a-runtime` id `450683a7-a6ac-4ca2-a0ea-0c984b3722cc` (expires 2027-01-18), stored as
**Credential global `TS_A2A_API_KEY`** (verified `type=Credential has_value=true`) and in git-ignored
`.local/railway/a2a_runtime.env` (0600). Key list screenshot only, Key column masked (`08-05`).
**Risk (documented):** a Langflow API key inherits its creator's **admin** privileges; the name does not
scope it. It lives only in the fixed connection configuration of the Sprint Room's A2A Audit node
(never in a prompt or tool argument). Revoke with the bootstrap key at handover.

The TaskSprint project is an `apikey`-auth folder, so the server requires an **owner** key on JSON-RPC
(langflow-base 1.12.5 `_enforce_a2a_auth`). `scripts/phase08_checks.py auth` (raw JSON-RPC 0.3, 13:22Z):

| Attempt | Result |
|---|---|
| `message/send`, no key | **HTTP 401** `{"detail":"API key required"}` |
| `message/send`, wrong key | **HTTP 401** `{"detail":"Invalid API key"}` |
| `message/send`, `TS_A2A_API_KEY` (read-only connectivity text) | **HTTP 200**, Task `52540ff5-62c5-441c-a6a8-46780acc5c5e`, context `phase08-auth-ts_a2a_api_key`, state `completed`, artifact `ec2e8808-0691-49ca-be7c-4fd8feeeaa89`; Operations' own trace: run `run_5ccf7f11bc2db90b85d89c877cd974b8` → `get_app_health`, `get_release_status`; no plan, nothing changed |
| `tasks/get` same id, no key / key | 401 / 200, same id, context, state, artifact (durable task store) |
| card without key | 200 (public discovery by design) |

## 6. A2A client in the Sprint Room (08.5) — adapter decision

**Native node not used:** lfx 1.12.5 `A2AAgentComponent` returns only the joined reply text (task,
context, message and artifact IDs are discarded), its *Internal* mode runs the flow in-process (not an
A2A transport), and with this card's `http://` RPC url it would strip `x-api-key` as off-origin.
**Added `components/a2a_audit.py` 1.0.0** (`TaskSprint A2A Audit`, sha256 `733827ff…`): the genuine a2a
SDK client (`create_client`, the compat 0.3 JSON-RPC transport the native node also uses), fixed peer
(card URL and RPC url must name flow `489890aa…`; requests outside the card origin are refused; no
redirects), `x-api-key` from `TS_A2A_API_KEY`; one non-streaming `message/send` with the payload as an
`application/json` **data part** and `contextId` = the coordinator run (lineage), then `tasks/get`; raw
JSON-RPC bodies (no headers) + IDs → `POST /v1/a2a-exchanges` (coordinator token). No task stub.
**Bounded Toolset 1.1.0** (sha256 `a3775f7e…`): coordinator slot **A2A peer: TS-20 Production Manager**
accepts only that adapter tool and exposes **`assess_production_release`** (args `candidate_id`,
`candidate_sha256`, `app_test_run_id`); the toolset builds the payload (`schema_version` 1.1, `intent`
`assess_release`, workspace, the three references, `agent_manifest_id: null`, `deadline_utc` =
now + min(90 s, remaining parent time), `allow_execute: false`), counts it as one delegation action charged
at the lab to the parent run, depth check, **once per turn**, no-progress gate. **Run Context 1.2.0**
(sha256 `00dd89b6…`) turns an A2A session `<ns uuid>:run_<hex>` into a child run (depth 1, shared
24-action tree, deadline capped).
TS-10 (`ec5b5dba…`, same id) updated by `scripts/phase08_flows.py --apply --only ts10` (`08-09`, `08-10`).
Wiring check (API run, session `phase08-wiring-check`, coordinator run `run_7ff21bff…`): the coordinator
lists exactly 11 tools: 7 MCP + `ask_product_owner`, `ask_developer`, `ask_qa`, `assess_production_release`.
No generic A2A tool; TS-90 does not exist.

## 7. Live checks 08.6 — **NOT RUN (need the redeployed lab)**

The adapter persists every exchange through `POST /v1/a2a-exchanges`, and Operations needs the real
`get_release_readiness` / `create_release_plan`; the deployed lab still answers `GET /v1/readiness`
**404** (`phase08_checks.py lab`). Running the assessment now would only produce `AUDIT_NOT_RECORDED`.

## Stop point — redeploy needed before live A2A assessment

**Orchestrator:** merge `feature/phase-08-a2a` → lab repository `main` and push, so Railway rebuilds
`tasksprint-lab` (migration 0003 is applied once at start; the volume is kept). Then confirm
`scripts/phase08_checks.py lab` → `200 (Phase 08 lab deployed)` and MCP `serverInfo.version` 0.5.0.
No Langflow or Railway variable change is needed.

**Remaining after the redeploy (same phase):**
1. Sprint Room Playground: ask for a release assessment of a tested candidate (e.g. `cand_af9914e7…` /
   pass `tr_b2139a09…`) → capture Task/context/artifact IDs, `a2a.exchange` event, exchange record
   (`phase08_checks.py exchange --id …`), Operations child run and its tool trace; expect a **blocked**
   assessment (agent-system manifest NOT_QUALIFIED → `RELEASE_NOT_READY`), no release (screenshots).
2. Duplicate/dedup check (A2A-04): repeat → second `assess_production_release` in the same turn refused
   `DELEGATION_LIMIT`; across turns plan dedup is unit-tested (live only if a plan can be created).
3. Peer disabled: TS-20 pane toggle **off** + Save → Sprint Room gets `PEER_UNAVAILABLE` (card 404),
   exchange recorded with no task, no plan/release; re-enable, retest.
4. Unauthorized retest after re-enable (no/wrong key → 401).
5. Final exports, this report's Gate table, OBSERVED_UI/BUILD_STATUS, reset list, commit.

## Findings and decisions for the owner

1. **Card advertises `http://` behind Railway TLS** (`url`, `cardUrl`). The edge 301-redirects http.
   Handled in the adapter (https upgrade, recorded). Optional owner fix later (Langflow service change,
   not done): make the server trust the proxy's `X-Forwarded-Proto` so the card shows https.
2. **Contract 1.0 → 1.1** (`agent_manifest_id` may be null): no manifest exists before Phase 10, so a 1.0
   payload would need an invented ID. Keep 1.1 or restore a required string in Phase 10.
3. **Tool name `assess_production_release`**, not `assess_release`: the supplied `prompts/coordinator.md`
   names the A2A tool `assess_production_release`; `assess_release` is the payload `intent`.
4. **Deploy plans are always blocked until Phase 10** (fail-closed manifest gate). A live plan reference
   can only be demonstrated for rollback, which needs a non-baseline active release (Phase 09).
5. Specialists TS-01/02/03 keep Bounded Toolset 1.0.0 / Run Context 1.1.0 (no behaviour change needed);
   only TS-10 (toolset 1.1.0) and TS-20 (toolset 1.1.0, Run Context 1.2.0) use the new versions.
6. `TS_A2A_API_KEY` is an admin-equivalent key (see §5).

## Reset list so far (demo-001 / Langflow)

Lab: operations run `run_5ccf7f11bc2db90b85d89c877cd974b8` (+3 events from 13:22:56Z), coordinator run
`run_7ff21bff4270746d6dff94df105e618d` (wiring check). No plans, exchanges, approvals or releases.
Langflow: flow TS-20 (published), TS-10 updated, API key `tasksprint-a2a-runtime`, Credential global
`TS_A2A_API_KEY`; A2A task `52540ff5-62c5-441c-a6a8-46780acc5c5e` (TS-20 task store) and its session;
TS-10 API session `phase08-wiring-check`.

## Screenshots (08-04 … 08-11)

08-04-a2a-pane-enabled-ts30-draft, 08-05-langflow-api-keys-list-a2a-runtime (Key column masked),
08-06-ts20-production-manager-canvas, 08-07-ts20-a2a-toggle-on-draft, 08-08-ts20-a2a-live-published,
08-09-ts10-sprint-room-with-a2a-peer, 08-10-ts10-a2a-audit-wired-to-toolset-slot,
08-11-ts20-agent-card-public-json.

## Manual click path (human equivalent)

1. TS-20: build as in §3 (or New Flow + the same nodes); Ctrl+S.
2. Rail **Agent** → **Serve as an A2A agent** on → scroll → **Save** → chip **Live**; copy the address.
3. Settings → **Langflow API Keys** → **Add New** (owner only, key shown once — never on a shared
   screen) → Settings → **Global Variables** → add Credential `TS_A2A_API_KEY`. (This build used
   `scripts/create_a2a_key.py` instead so the key was never displayed.)
4. TS-10: **New Custom Component** → paste `components/a2a_audit.py`; **Agent card URL (fixed peer)** = the
   https form of the address; **Peer flow ID**; **A2A API key** globe → `TS_A2A_API_KEY`; **Coordinator
   token (audit)** → `TS_COORD_TOKEN`; wire **Toolset** → Bounded Toolset **A2A peer: TS-20 Production
   Manager** (Toolset code replaced with 1.1.0). Never wire it to the Agent directly.
