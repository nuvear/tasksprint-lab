# Build status

**Last updated:** 20 October 2026 (Phase 00, read-only preflight).
**Current gate:** GATE 00 reached. Phase 01 not started.
**Live-instance changes made in Phase 00:** none. No flows, keys, variables,
providers, MCP servers, Railway variables or deployments were created or changed.

## Labels

| Label | Meaning |
|---|---|
| OWNER-REPORTED | Stated by Raj; not measured by this build |
| OBSERVED | Seen in the live UI or a read-only HTTP response on 20 Oct 2026 |
| TESTED | An operation was executed and its result verified |
| BLOCKED | A prerequisite is missing; not bypassed |
| NOT RUN / NOT BUILT | Future phase |

Presence of a route, page or component is recorded as OBSERVED, never as an
integration PASS. Nothing in this file is a protocol-execution result.

## Phase 00 results

| Item | Status | Evidence |
|---|---|---|
| Langflow on Railway, project Langflow, Pro plan, Postgres, volume `/app/langflow`, repo `nuvear/langflow-railway` | OWNER-REPORTED | AGENTS.md environment statement |
| Instance reachable | TESTED | `scripts/preflight.py`: `/health_check` 200 JSON, `/openapi.json` 200 JSON (`.local/preflight/report.json`, 2026-10-20T04:03Z) |
| Version 1.12.5 | OBSERVED | Profile menu "Version 1.12.5 (latest)" (`screenshots/00-02-version-menu.png`); `GET /api/v1/version` returned `{"version":"1.12.5","main_version":"1.12.5","package":"Langflow"}`; OpenAPI `info.version` 1.12.5 |
| Admin session in owner's browser | OBSERVED | Owner logged in privately; no credential seen or handled |
| Flows | OBSERVED: none | Welcome screen "Create first flow" (`screenshots/00-01-welcome.png`) |
| Model Providers | OBSERVED: none configured | 9 providers listed (`screenshots/00-04-settings-model-providers.png`) |
| Global Variables | OBSERVED: 4 present (discrepancy) | `ASTRA_TOKEN`, `COMPONENT_ID`, `FIELD_NAME`, `FLOW_ID`, all Credential, values masked (`screenshots/00-05-settings-global-variables.png`). Owner reported "no globals". Not created by this build; origin unconfirmed (likely Langflow defaults/env-sourced). Left untouched. |
| Langflow API Keys | OBSERVED: none | "No Data Available" (`screenshots/00-06-settings-api-keys.png`) |
| MCP Servers (client side) | OBSERVED: none | "No MCP servers added" (`screenshots/00-07-settings-mcp-servers.png`) |
| Langflow MCP Client (`lfx-mcp`) | OBSERVED | Config with placeholder `YOUR_API_KEY` (`screenshots/00-08-settings-mcp-client.png`); not used |
| Server A2A flag | OBSERVED: **disabled** | Authenticated `GET /api/v1/config` returned `"a2a_enabled": false` |
| A2A routes in schema | OBSERVED (presence only) | `/api/v1/a2a/agents`, `/api/v1/a2a/{flow_id}/.well-known/agent-card.json`, `/api/v1/a2a/{flow_id}/jsonrpc`. Card route documented to 404 while the flag is off. |
| MCP server routes in schema | OBSERVED (presence only) | `/api/v1/mcp/project/{project_id}` (+ `/install`, `/composer-url`, `/installed`), `/api/v2/mcp/servers`, `/api/v2/mcp/servers/{server_name}` |
| HITL routes in schema | OBSERVED (presence only) | `/api/v2/workflows/pending` ("List pending human-input requests"), `/api/v2/workflows/{job_id}/resume` (body `request_id`, `decision`), `/api/v2/workflows/stop` |
| Flow import/export routes | OBSERVED (presence only) | `/api/v1/flows/upload/`, `/api/v1/flows/download/`, `/api/v1/projects/upload/`, `/api/v1/projects/download/{project_id}` |
| Run routes | OBSERVED (presence only) | `/api/v1/run/{flow_id_or_name}` (API-key auth), `/api/v1/run/advanced/...`, `/api/v2/workflows`, `/api/v1/responses` (OpenAI Responses format, API-key auth) |
| Variables / API-key / login routes | UNKNOWN | Not in OpenAPI although UI pages exist and the security scheme names `api/v1/login` as tokenUrl; routers likely excluded from the schema. Do not assume payload shapes. |
| Components Agent, MCP Tools, Run Flow, A2A Agent, Human Input | UNKNOWN: verify in Phase 01 | `/api/v1/all` returned 2.78 MB of JSON (too large to inspect reliably in the browser without scripting); verify in the flow editor |
| Local toolchain (owner VM, aarch64) | OBSERVED | Python 3.10.12, git 2.34.1, uv 0.12.13 |
| Docker / local Compose | **BLOCKED** | `docker` not installed on the owner VM; local two-service Compose tests cannot run there |

## Future phases

| Item | Status | Phase |
|---|---|---|
| Model connection (TS-00) and sanitized component templates | NOT RUN | 01 |
| Backend and isolated runner | NOT BUILT | 02–05 |
| Live MCP / A2A / HITL protocol tests | NOT RUN | 04–09 |
| Validated flow exports | NOT BUILT | 01 onward |
| Application / security / agent evaluations | NOT RUN | 03–11 |
| Two-hour rehearsal | NOT RUN | 12 |

## Stop conditions carried forward

- A2A work (Phase 08) requires the owner to approve enabling the server A2A flag and a
  manual Redeploy. The variable name `LANGFLOW_A2A_ENABLED` comes from public docs
  (SOURCES S6) and is not yet verified against 1.12.5.
- If Human Input or A2A Agent components are absent in Phase 01, stop and report; do
  not substitute Run Flow or an agent-set approval flag.
- Docker must be installed (or another approved runner chosen) before Compose steps.
- Never convert OWNER-REPORTED or presence observations into integration PASS.
