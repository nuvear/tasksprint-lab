# Sources, assumptions and verification boundaries

## P1 — Owner-supplied environment

The latest user statement is the basis for the deployed version 1.12.5, empty
instance, admin username, domain, Railway project/workspace/Pro plan, existing
services, volume, port, source repository, redeploy behavior and secret-handling
constraints. This kit has not authenticated to or changed that installation.

The attached *Langflow on Railway Flow Infographics.pdf*, page 1, distinguishes
the disposable container from persistent Postgres and `/app/langflow`, and shows
the GitHub-to-Railway deployment relationship. Its Hobby-plan label differs from
the latest owner statement; use the current Pro statement, not that old label.

## P2 — Project terminology

The attached *9 AI Agent Terms — Student Workbook.pdf*, page 7, defines the nine
responsibilities used here. Pages 8–9 cover the harness and external controls;
pages 12–13 separate memory and state; pages 16–17 ground RAG in current evidence;
pages 20–21 distinguish MCP from authorization; pages 24–25 distinguish skills
from tools; pages 29–30 require enforceable guardrails; pages 34–35 separate agent
evaluations from deterministic tests; pages 39–40 distinguish A2A from MCP and
multi-agent architecture. These are alignment references, not an implementation kit.

The attached *Langflow + Obsidian — Student Handbook, Draft 0.2*, page 31, explicitly
notes that its old flow JSON is a design sketch, its named agents are largely
deterministic tools, and its A2A exercise uses a stub. Do not reuse those limitations
as though they satisfy this new scenario's real-agent/real-protocol requirements.

## Official documentation consulted on 20 October 2026

The retrieved Langflow documentation repeatedly labels itself **1.11.x**; the API
reference surfaced a **1.12.0** schema. Neither is proof of every 1.12.5 component
field on the owner's host. Phase 00/01 must capture the installed schema and actual
exports. Do not silently upgrade the host to match public documentation.

| ID | Official source | Used for |
|---|---|---|
| S1 | Langflow Language Model — `https://docs.langflow.org/components-models` | Global provider setup/model selection |
| S2 | Langflow Global variables — `https://docs.langflow.org/configuration-global-variables` | Generic/Credential distinction and field binding |
| S3 | Langflow API keys and authentication — `https://docs.langflow.org/api-keys-and-authentication` | API key creation and inherited user privileges |
| S4 | Langflow Import and export flows — `https://docs.langflow.org/concepts-flows-import` | Real exports, import paths and credential caveats |
| S5 | Langflow MCP client — `https://docs.langflow.org/mcp-client` | Native MCP client integration |
| S6 | Langflow A2A server — `https://docs.langflow.org/a2a-server` | Feature flag, publication, card/transport and execution authentication |
| S7 | Langflow Agent tools — `https://docs.langflow.org/agents-tools` | Tool Mode, specialist flow tools and native tool approvals |
| S8 | Langflow Custom components — `https://docs.langflow.org/components-custom-components` | Reviewed adapter/control components |
| S9 | Langflow API and trigger reference — `https://docs.langflow.org/api` and `https://docs.langflow.org/api-flows-run` | Installed-schema-oriented provisioning and execution |
| S10 | MCP server development — `https://modelcontextprotocol.io/docs/develop/build-server` | Implement a real supported MCP server, not a REST mock |
| S11 | Agent Skills specification — `https://agentskills.io/specification` | SKILL.md packaging and progressive disclosure |
| S12 | Railway Private Networking — `https://docs.railway.com/networking/private-networking` | Service-to-service networking |
| S13 | Railway Volumes — `https://docs.railway.com/volumes` | New lab volume persistence |
| S14 | Railway Dockerfiles — `https://docs.railway.com/builds/dockerfiles` | Separate service images/build configuration |
| S15 | Langflow HITL — `https://docs.langflow.org/human-in-the-loop` | Human pause/decision/checkpoint behavior |
| S16 | Langflow Human Input — `https://docs.langflow.org/human-input` | Deterministic approval/rejection branching |
| S17 | Langflow A2A Agent component — `https://docs.langflow.org/a2a-agent-component` | Actual peer client configuration |
| S18 | Codex AGENTS.md — `https://developers.openai.com/codex/guides/agents-md` | Repository-level coding instructions |
| S19 | Claude Code memory — `https://code.claude.com/docs/en/memory` | CLAUDE.md project instructions |

## Proposed design, not sourced product claims

The two new services, constrained interpreter, SQLite lab store, field schemas,
role-token design, flow names, command interfaces, candidate/release algorithms,
source corpus, trial counts and time budgets are the proposed TaskSprint
implementation. They are not native features inferred from a Langflow screenshot.
The builder must implement and test them.

The published A2A documentation consulted advertises protocol 0.3.0. The project's
teaching references discuss A2A more broadly. Read the actual deployed Agent Card;
no claim of A2A 1.0 conformance is made here.

No paid service, provider credential, Langflow flow, Railway variable or GitHub
repository has been created by producing this kit. The supplied helper script has
only been syntax/help checked locally; live-host results belong to the build phases.
