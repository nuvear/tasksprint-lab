# Phase 00 report — read-only preflight

**Date:** 20 October 2026
**Instance:** https://langflow-railway-production-f493.up.railway.app
**Scope:** inventory only. No deployment, no key creation, no flow creation, no
change to Railway, Postgres, the volume, the repository or Langflow settings.
**Evidence:** `.local/preflight/report.json`, `.local/preflight/langflow-openapi.json`
(ignored, local), `docs/screenshots/00-01` to `00-08`, `docs/BUILD_STATUS.md`,
`docs/OBSERVED_UI.md`.

## Verdict

**Feasible to proceed to Phase 01, with two known blockers for later phases.**

The installed Langflow is 1.12.5, reachable, and its API schema exposes the surfaces
TaskSprint depends on: flow import/export, API-key-authenticated run, MCP project
serving and client registration, A2A agent-card and JSON-RPC routes, and a
human-in-the-loop pending/resume surface. None of these has been executed yet, so
this is a presence finding, not proof that the integrations work.

Known blockers:
1. **A2A is switched off at server level** (`a2a_enabled: false` in `/api/v1/config`).
   Phase 08 needs your approval to enable it and a manual Redeploy. This is
   expected by the kit (BUILD_GUIDE 08.2), not a defect.
2. **Docker is not installed** on the VM shell used here, so local Compose tests are
   BLOCKED until Docker is installed or another runner is approved.

## Capabilities

| Capability | Status | Evidence / note |
|---|---|---|
| Version 1.12.5 | OBSERVED | Profile menu; `/api/v1/version`; OpenAPI info |
| Health and schema endpoints | TESTED | `/health_check` 200, `/openapi.json` 200 (85 paths) |
| Authentication schemes | OBSERVED | OAuth2 password (cookie), `x-api-key` header, `x-api-key` query |
| Model Providers page (9 providers) | OBSERVED | None configured |
| Langflow API Keys page | OBSERVED | Empty |
| Global Variables page | OBSERVED | 4 unexpected Credential variables (see risks) |
| MCP Servers (client registration) | OBSERVED | Empty; REST `/api/v2/mcp/servers*` present |
| Langflow as MCP server (per project) | OBSERVED (route) | `/api/v1/mcp/project/{project_id}`; not executed |
| A2A server | OBSERVED (route), **flag OFF** | Card/JSON-RPC routes present; card 404s while off |
| Human-in-the-loop | OBSERVED (route) | `/api/v2/workflows/pending`, `/{job_id}/resume` with `request_id` + `decision` |
| Flow import/export | OBSERVED (route) | `/api/v1/flows/upload/`, `/download/`; project upload/download |
| Run via API | OBSERVED (route) | `/api/v1/run/{flow_id_or_name}`, `/api/v2/workflows`, `/api/v1/responses` |
| Custom components | OBSERVED (config) | `allow_custom_components: true` |
| Components Agent, MCP Tools, Run Flow, A2A Agent, Human Input | UNKNOWN | Verify in the flow editor in Phase 01 |
| Python / git / uv on owner VM | OBSERVED | 3.10.12 / 2.34.1 / 0.12.13 |
| Docker | BLOCKED | Not installed |

## Missing or unknown

- Component field names, handles, and global-variable binding syntax (need real
  Phase 01 exports).
- Variables, API-key and login REST routes are not in the OpenAPI document, although
  the UI pages exist. Do not script against guessed shapes.
- The exact environment-variable name to enable A2A on 1.12.5 (kit uses
  `LANGFLOW_A2A_ENABLED` from public docs; unverified on this version).
- A2A Agent Card `protocolVersion` (readable only after enablement and publication).
- Human Input pause/resume behaviour, persistence across reload, and branch outputs.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Four pre-existing Credential globals (`ASTRA_TOKEN`, `COMPONENT_ID`, `FIELD_NAME`, `FLOW_ID`) contradict "no globals" | Name collisions; unclear provenance | Leave untouched; ask owner to confirm origin; use a `TS_` prefix for TaskSprint variables |
| Any Langflow API key inherits admin privileges | Over-privileged automation | Bootstrap key for local scripts only, never in model inputs; revoke after setup |
| Enabling A2A needs a Railway variable change and Redeploy on the live service | Touches existing production service | Owner-approved change in Phase 08 only; confirm DB/volume untouched after redeploy |
| `custom_component_admin_only: false` | Non-admin users could add custom code if accounts exist | Workshop uses owner screen; review before giving any participant access |
| Public docs are 1.11.x while instance is 1.12.5 | Field/route drift | Treat installed schema and exports as binding |
| Docker absent | Local integration tests cannot run on this VM | Install Docker or approve an alternative before Phase 02 Compose work |

## Smallest next human action (Phase 01, private)

1. In Langflow, open profile menu → **Settings** → **Model Providers**. Click **+** on
   one provider and enter its API key privately (screen capture paused). Enable one
   model that supports tool calling.
2. Open **Langflow API Keys** → **Add New**. Name it `tasksprint-bootstrap`. Copy the
   key once into your password manager (or an ignored file under `.local/`). Do not
   paste it into chat.
3. Tell the coding session "provider configured, bootstrap key saved" (no values).
   Phase 01 then builds `TS-00 Connection Check` and captures component templates.

Optional, no urgency: confirm whether you recognise the four existing global variables.

## Gate 00

- Capability report produced: yes.
- Live infrastructure changed: no.
- Missing A2A/HITL behaviour and unknown field names documented: yes.
- No upgrade, database reset or protocol substitute performed: confirmed.

**Stopped at Gate 00.**
