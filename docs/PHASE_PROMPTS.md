# Coding-agent phase cards

Paste one card at a time after the previous gate has been accepted. The coding tool
must read AGENTS.md and the corresponding guide/architecture sections each time.
Every card includes a manual-equivalent handover. Stop rather than invent a missing
interface, relax a control, or claim a test was executed when it was not.

## Card 00 — Read-only preflight

```text
Execute Phase 00 only. Read AGENTS.md, README.md, BUILD_GUIDE.md, ARCHITECTURE.md
and ACCEPTANCE.md. Preserve the existing Langflow 1.12.5 installation and its
secrets. I will log in privately. Do not request my admin password or
LANGFLOW_SECRET_KEY, create paid resources, deploy, or modify the live instance.
Inventory the installed UI/components and available OpenAPI schema. Distinguish
owner-reported facts from observed/tested capabilities. Inspect authentication,
model configuration, MCP, A2A, Human Input, Run Flow and export/import paths.
Create BUILD_STATUS.md and OBSERVED_UI.md with unknowns and stop conditions.
Report the smallest next human action and stop at Gate 00.
```

## Card 01 — Model connection and actual component templates

```text
Execute Phase 01 only. Guide me through private provider configuration and creation
of a setup-only Langflow API key; do not read or display their values. Build the
minimal TS-00 Connection Check using the actual installed components. Prove one
model response, then export and reimport it without credential literals. Capture
sanitized templates for Agent, MCP Tools, Run Flow, A2A Agent, Human Input, Chat
Input and Chat Output. Record exact handles, fields, observed UI labels, model
references and variable-binding syntax. Derive future flows from these artifacts
and the installed schema, never from invented simplified JSON. Report proof,
manual clicks and blockers; stop at Gate 01.
```

## Card 02 — Persistent backend and starter app

```text
Execute Phase 02 only, locally. Scaffold the separate TaskSprint repository and
feature branch, without modifying nuvear/langflow-railway. Implement the lab
service, migrations, canonical task/sprint/memory stores, immutable candidate and
evidence records, role authentication, redacted audit events, command parser and
starter v0. Follow Architecture A2-A5 and A8. Implement local_init.py, dependency
locking and .env.example. Generate only new demo credentials into ignored protected
files without printing them. Test deny-by-default authorization, workspace isolation,
optimistic concurrency, add/list persistence and honest FEATURE_UNAVAILABLE for
starter completion. Provide actual test commands/results and the manual equivalent.
No remote push or deployment; stop at Gate 02.
```

## Card 03 — Bounded source execution and protected app tests

```text
Execute Phase 03 only, locally. Implement the separate non-root stateless runner
and bounded Python-subset tree-walking interpreter in Architecture A6. Never exec,
eval, import, compile-to-execution, shell out, or invoke Python callables from
candidate syntax. Implement explicit AST allowlisting, bounded JSON values, loop/
step/depth/size/time limits, immutable source hashes and provenance. Build real
protected application tests and write reports from actual assertions. Keep graders
and reference fixtures outside developer-readable capabilities. Create Dockerfiles,
Compose and check_stack.py. Prove v0, labelled faulty and reference source produce
their actual different behavior, forbidden syntax fails, and the runner has no
production credentials/database access. Report tests and manual steps; stop at Gate 03.
```

## Card 04 — Real MCP, approved retrieval and skill loading

```text
Execute Phase 04 only. Implement the catalog in Architecture A8 using a supported
MCP SDK and Streamable HTTP. Prove initialization, tools/list, tools/call, error
semantics and timeout/cleanup with a real client. Filter discovery by authenticated
role and independently authorize direct calls. Index only knowledge/ with approved
status/effective dates/versioned chunk evidence. Implement list_skills and load_skill
with logged version/hash. Do not ingest instructor assets or repository-wide files.
Test archived-document exclusion, grounded current retrieval, unauthorized tool
denial and skill-without-authority. Return evidence and manual equivalents; stop
at Gate 04. No protocol stubs or mock results counted as integration passes.
```

## Card 05 — Owner-approved Railway services

```text
Execute Phase 05 only after I approve the proposed new services, storage and cost.
Prepare a separate TaskSprint repository and the two reviewed non-root service
images with locked dependencies. Guide me through creating tasksprint-runner
(private only) and tasksprint-lab (authenticated HTTPS, new /data volume, one
worker/replica) in the existing Railway environment. Keep existing Langflow,
Postgres, /app/langflow and the old repository unchanged. Configure runner DNS/port,
private transport credential and role-token hashes without displaying secrets.
Verify public liveness, unauthorized business-call rejection, authenticated
connectivity and new-lab persistence across redeploy. Report actual URLs, versions,
health evidence and exact manual steps; stop at Gate 05.
```

## Card 06 — App and independent specialists

```text
Execute Phase 06 only. Guide private creation/binding of the documented Generic
and Credential globals. Implement reviewed fixed-endpoint adapters; no generated
candidate code may execute in Langflow. Build TS-30 To-do App without an LLM and
TS-01 Product Owner, TS-02 Developer and TS-03 QA as separate real Agent flows.
Use the supplied prompts, role-scoped MCP tools, trusted run context and distinct
session namespaces. Use an isolated specialist-test workspace with explicitly human-authorized scope
or a labelled preapproved test-story fixture; do not fake classroom approval.
Verify app commands and each specialist independently:
retrieved citations, on-demand skill load, actual submitted source/hash, and
protected tests for that hash. Confirm forbidden roles/tools remain inaccessible.
Provide valid installed-version exports plus manual wiring/field instructions.
Do not claim untested round trips; stop at Gate 06.
```

## Card 07 — Coordinator, memory, state and enforced harness

```text
Execute Phase 07 only. Build TS-10 Sprint Room with three allowlisted Run Flow
specialist tools and the coordinator's permitted state/memory tools. Implement
trusted bounded wrappers where native runtime limits do not cover tool counts,
parent-child budgets, timeouts, no-progress stopping and depth. Bind run metadata
outside model-editable arguments. Never expose arbitrary-flow invocation. Test
fresh-chat continuity from canonical state, separate selected preference memory,
one repair cycle, missing-tool handling and cancellation blocking late writes.
Capture separate agent loops and actual adaptation to failed tests. Document
observed settings versus custom enforcement and manual equivalents; stop at Gate 07.
```

## Card 08 — Production Manager and genuine A2A

```text
Execute Phase 08 only. Build TS-20 Production Manager with its own Agent context
and Operations token. Prepare the minimal LANGFLOW_A2A_ENABLED change and wait
for my approval/manual redeploy; preserve every existing secret and setting.
Publish the eligible flow through the actual installed Agent UI. Fetch its real
Agent Card, record protocolVersion and use its advertised supported endpoint.
Configure authenticated execution and test denial without a valid key. Add a real
A2A client tool to Sprint Room carrying the typed assess_release task. Capture
actual task/context/artifact IDs; add a thin genuine SDK adapter only when native
output hides required metadata. Operations must fetch its own evidence and return
a validated plan/reference, not deploy. Test peer failure and deduplication.
Report exact manual steps and protocol evidence; stop at Gate 08.
```

## Card 09 — Human approval and replay-safe release controls

```text
Execute Phase 09 only. Build TS-90 Instructor Console as a deterministic protected
flow, never an agent tool or published peer. Wire canonical plan preview to Human
Input and separate Approve/Reject actions; carry the immutable plan snapshot through
the checkpoint. Record human decisions with the separate approver credential.
Implement Architecture A11's transactional execution algorithm, exact candidate/
manifest/environment/revision binding, expiry, kill-switch check, and idempotent
receipt replay. Agents must never mint approvals, invoke resets/drills, or record
evaluation passes. Use isolated control-test fixtures for readiness preconditions, not a fabricated
classroom qualification report. Test raw API denial without approval, forged approved booleans,
wrong hash/environment, stale revision, expiry, rejection and duplicate requests.
Provide observable proofs and manual clicks; stop at Gate 09.
```

## Card 10 — Independent agent evaluations

```text
Execute Phase 10 only. Implement an instructor-owned harness that invokes actual
Langflow flows and grades external state plus tool trajectories for ACCEPTANCE.md's
eight cases, three repetitions initially. Use separate synthetic workspaces and an
exact flow/model/prompt/tool/policy/skill/corpus/suite manifest. Keep grader code,
reference answers and evaluator credentials inaccessible to runtime developer tools.
Implement run_agent_evals.py and the protected live-case launcher in TS-90. Report
per-case denominators, critical failures, latency, available usage and missing
telemetry honestly. Do not confuse unit tests or a model's self-report with agent
evaluations. Gate readiness on critical slices and exact applicable manifests.
Provide results and manual steps; stop at Gate 10.
```

## Card 11 — Full scenario and failure recovery

```text
Execute Phase 11 only with my explicit approvals for synthetic release/drill actions.
Implement safe seed/reset scripts and run the complete approved story. Keep actual
agent-generated candidates separate from visibly labelled faulty/reference fixtures.
Permit one repair, then an explicit labelled fallback or escalation. Verify actual
candidate-specific tests, genuine A2A assessment, denied bypass, exact human approval,
real active-artifact change, retained completed task, candidate-specific completion
incident, diagnosis, separately approved rollback and unchanged task data. Keep
service liveness healthy during the drill. Test lost-response-after-commit replay,
reset twice, sanitized import/export and ID remapping. Report the true final v0
state and its missing completion feature. Stop at Gate 11 with the evidence chain.
```

## Card 12 — Freeze and hand over

```text
Execute Phase 12 only. Time the 120-minute runbook, run the final acceptance and
secret scans, create verified credential-free flow exports, source/dependency locks,
manual observed UI instructions, redacted evidence and safe reset/recovery commands.
Implement doctor.py and export_bundle.py. Distinguish recordings, fixtures and live
outputs. Do not fabricate proof for anything skipped. Guide me to revoke the
setup-only bootstrap key and leave needed runtime credentials intact. Freeze the
qualified manifest; explain what changes invalidate it. Finish with actual tests,
remaining limitations, manual startup steps and the exact pre-class starting state.
```

## Reusable repair instruction

```text
Do not move to the next phase. Diagnose the failed gate using the actual logs,
schema and component exports. State the failing assumption, implement the smallest
fix without weakening permissions or replacing a required real protocol, rerun the
failed test plus relevant regressions, update the manual and BUILD_STATUS.md,
and stop for review. Mark unavailable tests BLOCKED, not PASS.
```
