# Implementation architecture and contracts

## A1. Fixed scope and deliberate implementation choices

Preserve the approved story: an existing add/list starter gains task completion;
a known faulty candidate deletes the completed task; QA detects this; the Developer
repairs it; Operations assesses a release through A2A; a human approves; the app
activates the candidate; a candidate-specific incident leads to approved rollback.
The classroom is 120 minutes. Preparation has no two-hour constraint.

The following are proposed implementation choices, not claims about features
already installed in Langflow:

| Decision | Implementation |
|---|---|
| App interface | Deterministic commands in Langflow Playground; no separate front end |
| Application release | Atomic selection of an immutable, tested completion-function artifact |
| Candidate language | Small, documented Python subset interpreted by a bounded evaluator |
| Execution isolation | Separate stateless runner service; never Python execution inside Langflow |
| Knowledge retrieval | Metadata-filtered lexical retrieval over a tiny approved corpus; no embedding account needed |
| Persistent lab data | SQLite on a new `/data` volume, one backend worker/replica, transactional writes |
| Native protocols | Real MCP tools and real Langflow A2A exchange, using the installed protocol versions |
| Approval | Human Input in a protected deterministic flow plus backend approval records |
| Production scope | A synthetic `demo-production` environment; no live customer or infrastructure operations |

The Python-subset decision is important: the Developer writes actual source text,
and the runner interprets that source to determine behavior. This is neither
unrestricted Python development nor a hard-coded switch between GOOD and BAD.
Release is an application-level artifact activation, not a Railway container rollout.
Explain both limits to participants.

## A2. Services and repositories

Keep `nuvear/langflow-railway` unchanged unless an explicitly approved compatibility
fix is genuinely required. Use a separate proposed repository `nuvear/tasksprint-lab`.
Do not assume it exists or create/push it without the owner approving the action.

| Service | Role | Persistence | Exposure |
|---|---|---|---|
| Existing `langflow-railway` | Five model-driven agents, UI, native protocols, checkpoints | Existing Postgres and `/app/langflow` | Existing authenticated HTTPS domain |
| Existing `Postgres` | Langflow-owned data | Existing volume | Leave unchanged |
| New `tasksprint-lab` | Trusted app service, MCP, corpus, state, tests, release policy | New volume `/data` | Authenticated HTTPS; only minimal `/healthz` public |
| New `tasksprint-runner` | Bounded AST interpreter for candidate functions | None | Private service networking only |

The lab uses its own data store, not the existing Langflow database. The runner
receives only candidate source and a bounded copy of synthetic task records. It
receives no database password, model key, Railway token, Langflow key, production
role token, or filesystem mount. A transport-only runner token is permissible;
it authorizes evaluation requests, not access to any other system.

Use Python 3.12 for new services unless dependency resolution demonstrates a
specific incompatibility. Use FastAPI, a supported MCP Python SDK, Pydantic,
SQLite, an HTTP client, and pytest. Resolve and lock exact compatible versions.
Do not change the Python inside the existing Langflow image. Do not assume Docker
or a Docker socket is available inside Railway containers.

Suggested repository build outputs:

```text
services/lab/{main,auth,store,state,memory,retrieval,skills,candidates,testing,releases,mcp,app_commands,audit}.py
services/runner/{main,validator,interpreter}.py
components/{run_context,bounded_toolset,app_console,instructor_control,a2a_audit}.py
flows/{01_product_owner,02_developer,03_qa,10_sprint_room,20_operations,30_todo_app,90_instructor}.json
scripts/{local_init,check_stack,import_flows,verify_flows,seed_demo,reset_demo,run_agent_evals,export_bundle}.py
scripts/doctor.py
schemas/
tests/{unit,integration,protocol,security,agent_cases}/
Dockerfile.lab
Dockerfile.runner
compose.yaml
pyproject.toml
uv.lock
.env.example
docs/BUILD_STATUS.md
docs/OBSERVED_UI.md
reports/redacted/
```

These paths are targets for implementation, not claims that this instruction kit
already contains the corresponding application files.

## A3. Flows and real agents

Three principal classroom screens remain: Sprint Room, Production Manager, and
To-do App. Three specialist subflows make the agents easier to test independently.
One human-only control flow supports approval, drills, and resets. A disposable
connection-check flow may also be created during setup.

| Flow name | Core wiring | Identity and tools |
|---|---|---|
| `TS-01 Product Owner` | Chat Input → trusted Run Context → Agent → Chat Output | Product-owner credential; evidence and story proposals |
| `TS-02 Developer` | Same agent skeleton | Developer credential; skill, evidence, source reads, candidate submission |
| `TS-03 QA` | Same agent skeleton | QA credential; protected test invocation, evidence reads |
| `TS-10 Sprint Room` | Same skeleton, with three Run Flow tools and A2A delegation | Coordinator credential; controlled sprint writes and specialist routing |
| `TS-20 Production Manager` | Same skeleton; publish as A2A agent | Operations credential; health, plan, approved execution, rollback |
| `TS-30 To-do App` | Chat Input → deterministic App Console → Chat Output | Application credential; only add/list/complete/status |
| `TS-90 Instructor Console` | Typed command parser → immutable preview → Human Input → approved branch action → Chat Output | Human-only approver/instructor/evaluator clients; no Agent component |

Run Flow tools must point only at the three specialist subflows. The Operations
handoff must use an actual A2A transport, not Run Flow renamed “A2A”. Never expose
TS-90 through MCP, A2A, the coordinator's tools, or an arbitrary-flow execution tool.
The protected flow is an application design boundary, not separate enterprise IAM:
a Langflow administrator can edit flows and remains a trusted operator. Do not
share that admin login with participants. The backend remains the final action gate.

Role-specific instruction files are in `prompts/`. All agents may share one selected
model, but they must have separate execution contexts and tool privileges. Use
server-created session namespaces such as `workspace:role:conversation`, never a
single memory session shared by all roles. Retain authoritative state outside chat.

## A4. Roles, secrets, and configuration

Use random, independent role tokens. Store only token hashes in the lab service
where practical. Token lookup determines identity; an input field named `role`,
`approved`, `is_admin`, or `acting_as` cannot grant authority. Constant-time token
comparison, deny-by-default checks, request-size limits, redacted logs, and
request IDs are required.

| Langflow Credential variable | Backend identity | Allowed purpose |
|---|---|---|
| `TS_COORD_TOKEN` | coordinator | Read state, selected memory, story recording, permitted state transitions |
| `TS_PO_TOKEN` | product_owner | Search approved knowledge, read story/state, propose criteria |
| `TS_DEV_TOKEN` | developer | Read approved source/skills/evidence, submit new candidate |
| `TS_QA_TOKEN` | qa | Run protected application tests and read immutable results |
| `TS_OPS_TOKEN` | operations | Read readiness, health, logs; create plans; execute approved plans |
| `TS_APP_TOKEN` | application | Operate the synthetic to-do app only |
| `TS_APPROVER_TOKEN` | human_approver | Record a decision against an exact pending plan |
| `TS_INSTRUCTOR_TOKEN` | instructor | Seed/reset designated demo workspace, load labelled fixtures, control drill/stop |
| `TS_EVALUATOR_TOKEN` | evaluator | Record independently computed agent-evaluation reports |
| `TS_A2A_API_KEY` | Langflow API caller | Authenticate the fixed Operations A2A endpoint; never model-visible |

`TASKSPRINT_API_BASE` is a Generic global containing the lab's authenticated HTTPS
base URL. Model credentials belong in the installed Model Providers configuration
or the credential field that the installed component actually uses. They are not
Langflow API keys. No tool schema includes credentials, configurable arbitrary
URLs, SQL strings, filesystem paths, Python execution commands, or environment reads.

Langflow API keys inherit the creator's privileges [S3]. A named “A2A-only” key is
not automatically endpoint-scoped. Prefer a tested non-admin service account when
the installed ownership model supports it; otherwise document the admin-key risk,
keep it in fixed trusted connection configuration, and expose no generic HTTP tool.
The separate bootstrap key is local-only and revoked at handover.

New lab environment configuration: `TASKSPRINT_DB_PATH=/data/tasksprint.sqlite3`,
role-token hashes, `TASKSPRINT_RUNNER_URL`, transport-only runner credential,
`TASKSPRINT_DEMO_ENABLED=true`, one worker, one replica. The runner gets only its
transport token and resource limits. Add `LANGFLOW_A2A_ENABLED=true` to the existing
Langflow service only after approval and a capability check. Preserve all existing
variables. The owner performs the necessary Redeploy.

## A5. Data model and transaction rules

Use migrations and explicit versions. Do not mix the following records merely
because they all persist in the same store.

| Record | Required contents / authority |
|---|---|
| `workspaces` | Synthetic namespace, active flag, allowed environment, reset generation |
| `tasks` | workspace, task ID, title, completed, row revision; canonical app data |
| `sprints` / `stories` | Goal, approved criteria/version, stage, candidate reference, repair count, revision |
| `memories` | owner, workspace, preference key/value, source, created/expiry time; not approval |
| `documents` / `chunks` | stable ID, version, status, effective dates, owner, chunk text, content hash |
| `skills` | name, version, metadata, approved body and hash; no credentials |
| `candidates` | immutable source bytes, SHA-256, base hash, author role, origin, creation time |
| `test_runs` | candidate hash, protected suite hash, cases/results, runner version, evidence IDs |
| `agent_eval_reports` | flow/model/prompt/tool/policy/data versions, cases, repetitions, outcomes and trajectories |
| `release_plans` | immutable action/environment/target hash, baseline hash, release revision, evidence IDs, plan hash |
| `approvals` | exact plan hash, human identity, decision, expiry, consumed status; protected writer |
| `releases` | active and previous artifact hash, release revision, execution receipt, plan/action ID |
| `runs` / `events` | server-created lineage, budgets, tool events, terminal state, redacted observable evidence |
| `drills` | instructor-authorized fault type, candidate hash, expiry, enabled flag |

Use one controlled writer for sprint transitions, transactions and optimistic
revision checks. Test results are written by trusted testing code, not QA's prose.
Release readiness is computed from evidence; the coordinator cannot set it to true.

Allowed sprint stages: `PLANNED`, `IN_DEVELOPMENT`, `IN_QA`, `CHANGES_REQUESTED`,
`APP_VERIFIED`, `READY_FOR_REVIEW`, `CLOSED`. Release states are separate:
`PLANNED`, `AWAITING_APPROVAL`, `APPROVED`, `EXECUTED`, `REJECTED`, `EXPIRED`,
`ROLLED_BACK`. Do not collapse “story accepted”, “tests passed”, and “deployed”.
One automatic repair is allowed for the demonstration story. After that, escalate.

Generate IDs and action keys outside the model. A repeat execution with the same
plan/action ID returns the existing receipt. A changed payload with that ID is a
conflict. A client timeout does not establish failure; query status before retrying.
The demo reset changes a workspace generation and cancels old runs/plans so an old
approval cannot act on a newly seeded session.

## A6. Candidate source and bounded execution

Function contract:

```python
def complete(tasks, task_id):
    # tasks: bounded list of JSON dictionaries {id, title, completed}
    # Return {ok: bool, code: str, tasks: list}; do not read or write external state.
    ...
```

Developer source reads are limited to starter/agent-generated candidates and the
explicitly selected faulty fixture needed for repair. Reject Developer source reads
of `fixture-reference` candidates, even when their IDs are known. The trusted test
service may execute the reference artifact after a labelled instructor fallback;
that does not make its source a Developer retrieval result.

The runner returns a result computed by interpreting this actual source. The lab
service validates that result, then commits permissible state changes. The runner
never writes the database. The active candidate is resolved by content hash for
every command; “deploy” cannot be only a UI label.

Implement a small tree-walking interpreter, not `exec` with a reduced builtins dict.
Allow only the grammar needed by the supplied examples: a single function with two
arguments; bounded `for` loops over supplied lists; `if`; return; simple assignment;
JSON dictionaries/lists/scalars; subscripts; equality/inequality; and a single-level
list comprehension. Explicitly reject every unsupported AST node before execution.
Use an explicit local-value environment, deep copies at the input/output boundary,
and interpreter-owned get/set operations. Never resolve Python attributes or invoke
Python callables from candidate syntax. Do not use evaluation of f-strings.

Reject imports, calls, attribute access, dunder names, classes, lambdas, decorators,
recursion, generators, while loops, exception machinery, with blocks, named
expressions, arbitrary operators, and dynamic code. Function arguments must be
exactly `tasks, task_id`, with no defaults, varargs, kwargs, or annotations.

Initial limits: source ≤4 KiB; ≤256 AST nodes; depth ≤20; input ≤32 KiB; ≤100 tasks;
title ≤120 characters; ≤5,000 interpreted operations; ≤2 seconds per evaluation;
no unbounded comprehensions or nested iteration. Enforce limits in code, including
list creation/output size. A process/request timeout alone is not the boundary.
Run as a non-root service. Do not claim Railway blocks all network egress unless
that control has actually been configured and tested. The candidate grammar itself
must have no networking or filesystem operations.

The trusted runner service may use ordinary Python to implement the interpreter.
Candidate source must never become executable Python bytecode or an imported module.
This is a constrained training runtime, not a general hostile-code sandbox.

Task operations are idempotent at the app layer. `complete` on an already completed
task leaves its data unchanged. Unknown task IDs return `TASK_NOT_FOUND` and no
mutation. `add`/`list` remain trusted server operations and are regression-tested.
Use snapshot revision checks when committing a runner response so concurrent writes
cannot be silently lost. Serialization is acceptable for this single-presenter lab.

## A7. Retrieval and skills

Ingest only `knowledge/` into the product corpus. Load the skills into a separate
approved catalog. Never ingest the repository root, instructor material, source
answers, test code, `.local/`, logs, or credentials.

Implement real query-time retrieval, such as SQLite FTS5 with ranking. Verify FTS5
availability during the local build; a deterministic lexical index is an acceptable
alternative when documented and tested. Enforce approved status and effective-date
filters outside the model. Return top three relevant chunks with document ID,
version, section, owner, and hash. Empty/conflicting results trigger abstention.
The archived note stays available to the instructor to demonstrate why a metadata
filter matters; it must not appear in the normal current-evidence tool.

The RAG demonstration is complete only when the model receives retrieved passages
and grounds its story/criteria in them. A document pasted permanently into a system
prompt is not this retrieval demonstration. Semantic embeddings are optional, not
necessary for the tiny corpus.

`list_skills` returns names, descriptions, versions. `load_skill(name, version)`
returns the approved body on demand and records the load event. The two supplied
SKILL.md packages are procedure, not extra authority. The allowed tool list remains
controlled by the backend identity.

## A8. HTTP operations and MCP tool catalog

These are TaskSprint routes to implement, not existing Langflow endpoints. All
business routes require authorization. Use typed schemas with unknown fields
rejected. Resolve workspace permissions from the credential and trusted run context.

| REST operation | MCP tool / caller | Contract |
|---|---|---|
| `GET /healthz` | none | Minimal service liveness; no business data |
| `POST /v1/runs` | trusted runtime adapter | Issue bounded run context; reject client-selected authority or unlimited budgets |
| `GET /v1/state` | `get_sprint_state` / approved agents | Return canonical story/status/revision/evidence references |
| `POST /v1/stories` | `record_story` / coordinator | Save proposed story; human confirms scope separately |
| `POST /v1/state/transitions` | `transition_story` / coordinator | Validate legal transition, revision and evidence preconditions |
| `GET, POST /v1/memory` | `read_preferences`, `save_preference` / coordinator | Allowlisted presentation preferences only; scoped owner and expiry |
| `POST /v1/knowledge/search` | `search_approved_knowledge` / authorized roles | Approved/current relevant chunks; bounded query/results |
| `GET /v1/skills` | `list_skills` / developer, operations | Metadata only |
| `GET /v1/skills/{name}/{version}` | `load_skill` / developer, operations | Pinned approved procedure; log version/hash |
| `GET /v1/candidates/{id}` | `read_candidate` / developer, qa, operations | Public candidate source and provenance; no grader or reference solution |
| `POST /v1/candidates` | `submit_candidate` / developer | Immutable new source, server-generated ID/hash; no overwrite |
| `POST /v1/test-runs` | `run_candidate_tests` / qa | Run a protected suite against a copy, not production data |
| `GET /v1/test-runs/{id}` | `read_test_report` / qa, operations, coordinator | Immutable externally computed report |
| `GET /v1/readiness` | `get_release_readiness` / operations | Compute current candidate and agent-baseline gates from evidence |
| `POST /v1/release-plans` | `create_release_plan` / operations | Bind deploy/rollback target, evidence, current release revision |
| `GET /v1/release-plans/{id}` | `read_release_plan` / operations, human | Exact canonical preview; no mutation |
| `POST /v1/approvals` | NO model tool / human approver | Record approve/reject for exact plan hash and expiry |
| `POST /v1/release-executions` | `execute_approved_plan` / operations | Validate and consume approval atomically; replay-safe receipt |
| `GET /v1/releases` | `get_release_status` / operations, application | Actual active source hash/revision/history |
| `GET /v1/app-health` | `get_app_health` / operations, application | Business health of active version, distinct from liveness |
| `GET /v1/events` | `read_recent_events` / scoped roles | Redacted bounded events, not secrets or arbitrary logs |
| `POST /v1/app/commands` | NO reasoning required / application | Parse add/list/complete/status; call active function for completion |
| `POST /v1/instructor/actions` | NO model tool / instructor | Allowlisted seed, fixture, fault, stop, reset and scope-confirm actions |
| `POST /v1/agent-evaluations` | NO model tool / evaluator | Store report and manifest from trusted independent evaluation harness |

Use an official MCP SDK over Streamable HTTP. Implement actual initialization,
`tools/list`, `tools/call`, schema descriptions, error semantics and cleanup; do not
just name a REST endpoint `/mcp`. The authenticated role determines which tools
are discoverable and callable. Hidden tools must also be rejected on direct calls.
Per-role server mounts are acceptable when the SDK makes role-aware listing awkward;
each mount must still authenticate its own permitted role. Use transport names and
versions actually supported by the installed Langflow MCP client.

Expose only the small relevant subset to each agent. Use the native MCP connection
UI's tested Credential-variable/header mechanism; never guess an interpolation
syntax. Record that syntax or UI binding in OBSERVED_UI.md. With a public lab URL,
require TLS and token validation. With a private URL, use a verified narrow host
allowlist if needed; never disable SSRF defenses globally as a shortcut.

## A9. Harness and adapter obligations

Use native Agent iteration/time settings where present, but do not equate an
iteration with one tool call. Add a small trusted bounded-tool wrapper where needed.
The runtime generates a run ID, binds role/session/workspace, and injects metadata
outside model-editable arguments. The backend validates mutations independently.
A model cannot reset budgets by inventing a new run ID or creating arbitrary runs.

Initial configurable budgets: eight tool actions per agent invocation; twenty-four
across the parent turn and its descendants; delegation depth at most two; one repair
cycle per story; one retry for a transient read; no blind write retries. A specialist
turn has a proposed 90-second deadline; a parent turn has 180 seconds. Record the
actual rehearsed values. Operations requiring longer need an explicit new bounded
human-started task, not an invisible increase.

Count native helper-flow/A2A delegations as actions and propagate the parent lineage.
Do not double-count the internal HTTP steps of one tool as extra model actions.
Timeouts, per-call schema checks, no-progress detection, cancelled-run rejection and
an instructor kill switch are required. After stop/cancel/expiry, in-flight results
must not commit. Check authorization and the active run again immediately before a
transaction. Preserve a terminal state and evidence of the stop.

Native traces plus the lab event log must show retrieval, skill load, candidate
submission, tests, delegation, approval receipt, release and recovery. Record token
usage where provided; use `null` and a reason where unavailable. Cost estimates
require an explicit dated price table and are labelled estimates. Never invent
latency/token/cost data or record a model's private reasoning.

## A10. A2A handoff

First test native publishing on the installed 1.12.5 instance. Documentation [S6]
describes enabling A2A, saving an eligible chat-input/chat-output flow as agent type,
and publishing it. Use the actual card URL and endpoint returned by that instance.
The card may advertise 0.3.0; do not rename it 1.0. Use the supported SDK/transport.

The application task is a typed `assess_release` request, carried inside an A2A text
or data part supported by the installed implementation. See `contracts/` for the
application contract. Do not insert invented fields into the A2A protocol envelope.
Only references to candidate/test evidence and a deadline cross the boundary;
Operations fetches its own authorized evidence. No credentials or full chat dump.

The recipient is a real Langflow Agent with its own context and tools. It returns
an actual A2A Task and artifact containing a validated assessment or plan reference.
Capture protocol task/context/message/artifact IDs as returned. Application plan IDs
are distinct from protocol IDs. Persist the raw redacted exchange and parent lineage.
If the native component hides these IDs, add a thin audited adapter around a genuine
A2A client, not a task stub. Save that implementation choice in the capability report.

Task success means assessment completed, not deployment completed. Do not rely on
an A2A retry guaranteeing exactly-once execution. Deduplicate the bounded assessment
at the application boundary. On unreachable peer, expire/escalate with no release.
A direct request to Operations can later execute a separately approved plan.

## A11. Approval, execution, and rollback algorithm

The human-only TS-90 flow accepts `review PLAN_ID`, fetches the canonical preview,
then pauses at Human Input with Approve/Reject branches. A trusted adapter carries
an immutable plan reference across the pause. Approve records a decision through
`TS_APPROVER_TOKEN`; Reject records rejection and never executes anything. Typed
chat such as “approved”, a model flag, an Agent Card, or a QA summary is not consent.

The preview shows operation, environment, candidate ID/hash, current and previous
hash, application-test evidence, agent-baseline manifest, expected release revision,
expiry, and rollback target. A plan hashes all consequential fields and references.

The execution endpoint, in a transaction, must:

1. Authenticate Operations and check workspace, run status and stop flag.
2. Check whether this action already has a receipt; return it on an identical replay.
3. Load the immutable plan and its current, unexpired, unused human approval.
4. Validate the plan hash, target source hash, environment and release revision.
5. For deployment, require the exact candidate's protected tests and the approved
   agent-system manifest. Recompute or verify the evidence, never trust client booleans.
6. For rollback, require a previously recorded healthy baseline/release and its
   baseline smoke suite. Do not demand the new feature's tests of the old starter.
7. Atomically update the active artifact pointer, increment release revision, consume
   the approval and write the receipt/event. Preserve task records unchanged.
8. Run post-activation checks separately and record their actual result. A failed
   post-check is an incident; it is not proof that the transaction never happened.

Use a fifteen-minute approval expiry for the rehearsal unless timings require an
explicitly documented change. Changes to source, policy/evidence manifest, plan,
environment or active release invalidate the corresponding authorization. Ordinary
new task records need not invalidate a release plan; use release revision, not every
application-row update, as the release concurrency token.

## A12. Incident, reset, and evaluator separation

The instructor can enable `completion_unavailable` only for a specified active
candidate in a designated synthetic workspace, with a short expiry. Completion
requests then return a real controlled error; app-health reports degraded. Keep
`/healthz` healthy so Railway does not restart the hosting services as the drill.
Operations reads the evidence and requests rollback. Recovery changes the active
hash to v0; it does not restore a previous database snapshot or erase completed flags.
No continuous monitoring is promised; the instructor triggers one monitoring cycle.

Reset is explicit and limited to the designated workspace. Preview counts, export
that workspace's evidence, require confirmation, clear drill/stop flags, cancel
pending work, seed the two known tasks, restore v0, and advance workspace generation.
Never drop the existing Langflow database, delete all Langflow flows, or reset all
workspaces. Repeated resets should produce the same canonical starting state.

The evaluation harness is trusted instructor code, not another agent scoring itself.
It invokes actual Langflow flows and checks external state plus event trajectories.
Keep grader files and evaluator credentials outside the developer's tool reach.
Report unit, integration, protocol and agent-evaluation results separately. A tiny
three-repeat case set is workshop evidence, not production certification or proof
that five agents outperform one.

## A13. Required command interfaces

The builder implements these before handing over. Each supports `--help`, validates
configuration, has bounded timeouts, produces redacted output, and returns nonzero
on failure. Destructive actions require explicit workspace targeting and confirmation.

```bash
uv sync --frozen
uv run python scripts/local_init.py
uv run pytest -q tests/unit tests/security
docker compose up --build -d
uv run python scripts/check_stack.py --target local
uv run python scripts/import_flows.py --dry-run
uv run python scripts/import_flows.py --apply
uv run python scripts/verify_flows.py
uv run python scripts/seed_demo.py --workspace demo-001 --dry-run
uv run python scripts/seed_demo.py --workspace demo-001 --apply
uv run python scripts/run_agent_evals.py --repeats 3
uv run python scripts/reset_demo.py --workspace demo-001 --dry-run
uv run python scripts/reset_demo.py --workspace demo-001 --confirm demo-001
uv run python scripts/export_bundle.py --redacted
uv run python scripts/doctor.py
```

`local_init.py` creates only new TaskSprint credentials/configuration in ignored files,
with restrictive filesystem permissions; it must never print values. Existing files
are not overwritten automatically. `import_flows.py` discovers actual IDs, limits
writes to the TaskSprint project, preserves unrelated flows, patches helper
references after import, binds existing secret variable names without values, and
round-trip verifies exports. A second run must not create duplicates.
