# TaskSprint — build handoff kit

**Target:** existing Langflow 1.12.5 on Railway. **Edition:** 20 October 2026.
**Status:** implementation instructions and seed assets; not an installed application.
No changes have been made to the owner's Railway, GitHub, or Langflow instance.

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
