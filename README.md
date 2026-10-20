# TaskSprint — build handoff kit

**Target:** existing Langflow 1.12.5 on Railway. **Edition:** 20 October 2026.
**Status (Phase 12):** built and frozen as `workshop-v1` (see `docs/FROZEN_VERSION.md`, `docs/BUILD_STATUS.md`).
The original kit text below describes how it was built; the section "Class day" is how to run it.

## Class day (built workshop)

Everything below runs from this repository on the presenter's machine, with the private files in
`.local/railway/` restored from the password manager (`PRIVATE_CONFIGURATION_CHECKLIST.md` in the bundle lists
the names). Always use the locked environment: `uv run --frozen --no-dev python …`.

1. **Doctor** — `scripts/doctor.py`. It checks: lab and Langflow health, the lab -> runner path, v0 with T001/T002,
   nothing pending, the qualified manifest with a fresh attestation, the seven flows, the A2A peer card, and one
   live model turn. Any FAIL: stop and read the line (a live run from < 90 s ago is doctor's own model probe).
2. **Reset** — `scripts/reset_demo.py --workspace demo-001 --dry-run --lab-url https://tasksprint-lab-production.up.railway.app --tokens-file .local/railway/role_tokens.env`,
   then the same command with `--confirm demo-001` in place of `--dry-run`. Or use TS-90: `reset preview`, then
   `reset confirm demo-001`.
3. **Doctor again** — `scripts/doctor.py --no-model-probe`. It must be PASS: v0, two tasks, no pending plan,
   approval, drill or stop.
4. **Three screens** (Langflow, project TaskSprint, each in its Playground):
   * **TS-30 To-do App** — `status`, `list`;
   * **TS-10 Sprint Room** — the class prompts;
   * **TS-20 Production Manager** — release, incident and recovery.
5. **Instructor console** — **TS-90 Instructor Console**, human-only: scope confirmation, fixtures, drills, `review
   <plan>` with **Approve** / **Reject**, `stop`/`resume`, reset. Keep it off the projector when it shows IDs.
6. Follow `docs/SESSION_RUNBOOK.md` (timed 120-minute table and observed prompt wording).

After class: reset again. Do not change models, prompts, skills, tools, flows or policy without rerunning
`scripts/run_agent_evals.py --repeats 3` (the frozen manifest no longer applies otherwise). Other checks:
`scripts/verify_flows.py` (live flows equal `flows/*.json`) and `scripts/export_bundle.py --redacted` (the
sanitized handover bundle).

The kit instructs Claude Code, Codex, or a human developer to implement the approved
five-agent Scrum demonstration. It deliberately does not contain invented flow
exports. The builder must export component templates from the actual installation,
produce valid flows, and prove they import and run.

## Start
Open `TaskSprint_Build_Guide.html` for the indexed, single-page manual. Its source
sections are in `docs/`. Open this folder in your coding tool and paste:

```text
Read AGENTS.md and the referenced build documents. Execute Phase 00 only.
Use my existing Langflow 1.12.5 installation; do not recreate it or change its secrets.
I will handle sign-in and credential entry privately. Do not request my admin
password or LANGFLOW_SECRET_KEY. Inspect the available interfaces, write the
capability report, give me the manual equivalent, and stop at the Phase 00 gate.
```

After each accepted phase, use its next card in `docs/PHASE_PROMPTS.md`.
Do not ask the coding tool to improvise all phases in one unattended run.

## Contents
| Path | Purpose |
|---|---|
| `AGENTS.md`, `CLAUDE.md` | Coding-agent instructions |
| `docs/BUILD_GUIDE.md` | Manual implementation and operator steps |
| `docs/ARCHITECTURE.md` | Services, data, API/tool contracts, security, execution semantics |
| `docs/PHASE_PROMPTS.md` | Thirteen phase-by-phase coding prompts, 00–12 |
| `docs/ACCEPTANCE.md` | Required proofs, evaluation design, and readiness gates |
| `docs/SESSION_RUNBOOK.md` | The 120-minute class prompts and evidence |
| `docs/SOURCES.md` | User facts, project alignment, external documentation, design decisions |
| `prompts/` | Five runtime agent instruction files |
| `skills/` | Two versioned procedural skill packages |
| `knowledge/` | Approved and archived product/release evidence for retrieval |
| `instructor/fixtures/` | Starter, faulty, and reference function sources; not agent-readable |
| `contracts/` | Example application-level task and release-plan schemas |
| `scripts/preflight.py` | Supplied, read-only HTTP/schema probe; not a provisioning script |

## What is supplied versus what must be built
The text, prompts, procedures, fixtures, example contracts, and read-only preflight
helper are supplied. Backend services, flow exports, authentication adapters,
release controls, automated test runners, and deployment scripts are build outputs,
not existing files. Commands prefixed `uv run python scripts/...` in the guide
are interfaces the builder must implement before the relevant gate is complete.

A human developer can implement the same file-level contracts and follow the same
Langflow/Railway steps. A UI-only drag-and-drop build is not sufficient for the
persistent app, isolated execution, or backend approval enforcement in this scenario.

The five runtime agents are distinct from the coding tool used to prepare this kit.
Using Claude Code or Codex to build the environment is not part of the live five-agent
system and must not be presented as a sixth workshop agent.
