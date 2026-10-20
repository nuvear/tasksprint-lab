# TaskSprint build instructions

Read `README.md`, `docs/BUILD_GUIDE.md`, `docs/ARCHITECTURE.md`,
`docs/ACCEPTANCE.md`, and the current card in `docs/PHASE_PROMPTS.md` before working.
`docs/SOURCES.md` distinguishes user-supplied facts, documentation, and design decisions.

## Mission
Implement the approved TaskSprint workshop: five real Langflow agents develop,
test, release, and recover a small to-do application. All classroom interaction
must be available in Langflow. Preparation is outside the 120-minute class.
The nine terms are Harness; Memory and State; RAG; MCP; Agent Skills;
Guardrails; Agent Evaluations; A2A; and Multi-Agent Systems.

## Existing environment — preserve it
Langflow 1.12.5 is reported live at
https://langflow-railway-production-f493.up.railway.app ; login is /login,
username admin. Railway project Langflow, workspace nuvear's Projects, Pro plan.
Existing services: langflow-railway and Postgres. Existing volume: /app/langflow.
Existing source: github.com/nuvear/langflow-railway, Dockerfile + railway.json;
a push to main redeploys it. The instance starts with no flows, globals, or API keys.
These are owner-supplied facts, not measurements made by this instruction kit.

Never request, read, print, overwrite, or rotate the existing admin password or
LANGFLOW_SECRET_KEY. Never reset the database to fix authentication. The owner
logs in and enters credentials privately. Do not touch the existing database,
volume, port 7860, or repository main branch. Variable changes need an explicit
manual Redeploy in this installation. Stop before production infrastructure changes.

## Work rules
- Work in a separate TaskSprint repository, on a feature branch. Do not assume
  a proposed remote repository already exists. Obtain approval before paid services,
  pushes, deployments, destructive resets, or changing the existing service.
- Complete one phase at a time. A phase ends with tests, redacted evidence,
  changes made, the human-equivalent steps, and the next action. Stop at the gate.
- Read the installed instance's schema and export real sample components first.
  Public docs currently surfaced as 1.11.x are guidance, not proof of 1.12.5 fields.
- No invented Langflow JSON exports, field names, IDs, API routes, or successful
  tests. A design sketch is not an importable flow. Validate import/run/export
  against 1.12.5. Discover IDs and remap helper-flow references after import.
- Use native Langflow Agent, MCP, A2A, and Human Input components where verified.
  Custom components are small, reviewed adapters/control code, not fake agents.
- A2A must exchange real protocol tasks and artifacts. Read the actual Agent Card
  protocolVersion; do not force the newest specification onto an older implementation.
- Five distinct model-driven loops must run. Do not replace specialists with
  deterministic scripts or one model acting out several personas.
- Keep model credentials, Langflow API keys, and TaskSprint role tokens distinct.
  Secrets stay in private input, Credential variables, or ignored local secret files.
  Never dump environment variables or export literal credentials. Do not read
  `.local/` secret contents into the coding conversation. Scripts may consume them
  without printing them after the owner authorizes the operation.
- Langflow API keys inherit their creator's permissions. A descriptive key name
  does not make an admin key narrowly scoped. Keep bootstrap keys out of model
  inputs and revoke the bootstrap key after setup.
- The backend enforces role authorization, input validation, approvals, immutable
  artifacts, optimistic concurrency, replay protection, and limits. Prompts do not.
- Never execute generated Python with exec, eval, compile-to-execution, importlib,
  pickle, shell, or unrestricted subprocesses. Implement the specified bounded
  Python-subset interpreter in the separate runner. Do not call an AST filter alone
  a sandbox. Never run candidate code in Langflow's server process.
- Actual release selects a tested immutable function artifact in the demo app.
  It does not change Railway deployments, the Langflow image, or infrastructure.
- A trusted human-only control flow records approvals. No model can create an
  approval or access instructor/evaluator credentials. A chat statement is not approval.
- Keep application tests separate from repeated end-to-end agent evaluations.
  Verify external state and tool trajectories; never accept an agent's PASS claim.
- Do not expose instructor fixtures, reference answers, grader source, or grading
  credentials through developer tools, RAG, skill retrieval, or candidate workspaces.
- Mark fixtures and recordings honestly. A reference fallback is not live coding.
- No secret-bearing screenshots, chain-of-thought collection, or private reasoning
  logging. Capture tool actions, evidence IDs, observable decisions, and outcomes.

## Delivery
Produce the Python backend, restricted runner, locked dependencies, tests,
Dockerfiles, local Compose setup, validated Langflow exports, custom components,
configuration templates, idempotent setup/check/reset scripts, a 120-minute runbook,
and a manual with the actual observed UI labels. Keep `docs/BUILD_STATUS.md` current.

Implement every command contract in ARCHITECTURE.md before documenting it as usable.
Use fake credentials in unit tests. Networked tests require owner-provided private
configuration and approval. Never mark a skipped test PASS.

## First action
Execute Phase 00 only. Report feasibility, verified/missing capabilities, and the
smallest next human action. Do not deploy anything in Phase 00.
