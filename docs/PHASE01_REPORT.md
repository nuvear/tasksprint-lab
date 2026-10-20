# Phase 01 report — model connection and component templates

**Date:** 20 October 2026, 04:49–05:06 UTC. **Instance:** Langflow 1.12.5,
`https://langflow-railway-production-f493.up.railway.app`, owner's Chrome, signed in as
admin by the owner. **Gate:** GATE 01 reached with one stated limitation (true file
re-import not tested; see "Round trip"). No A2A readiness is claimed.

## Proof of model response (TESTED)

Flow `TS-00 Connection Check`, Playground, Default Session.

- Sent: `Check the model connection.`
- Received (verbatim): `TaskSprint model connection is working.`
- Status "Finished in", 594 tokens, 2.0 s. Traces: trace ID `691e4ffe-851b-4adb-97ec-9…`
  at 04:51:40, latency 2.04 s, status OK (`screenshots/01-20-flow-activity-trace.png`).
- No error. Screenshot `01-09-playground-response.png`.

This proves a plain-text model call only. Tool calling is not yet proven (Phase 04/06).

**Model used:** Agent **Language Model** dropdown, group **Anthropic**, model
`claude-sonnet-5-5` (serialized `model.value[0].name = "claude-sonnet-5-5"`,
`provider = "Anthropic"`, `metadata.tool_calling = true`). There is one combined dropdown
grouped by provider, not separate provider/model fields. Enabled models visible:
Anthropic claude-sonnet-5-5, claude-opus-5-5, claude-fable-5-1; OpenAI gpt-6.1-sol,
gpt-6-luna, gpt-6-sol, gpt-6-astra, gpt-daybreak-red-latest.

Agent Instructions set exactly to the guide text (three lines). Agent defaults left as
installed: Max Iterations 15, Calculator and Current Date tools **enabled** (see blockers).

## Flows created on the live instance

| Flow | ID | Content | Keep? |
|---|---|---|---|
| `TS-00 Connection Check` | `3f476c53-e39f-4157-8f73-5e488a0a43e9` | Chat Input `ChatInput-80GoH` → Agent `Agent-vZq8X` → Chat Output `ChatOutput-ca04x` | Disposable setup flow (A3) |
| `TS-00T Templates` | `0685ac65-234e-4752-bf76-ba45860e74be` | Unconnected: Human Input, A2A Agent, Run Flow (target = TS-00), Chat Input, Chat Output, Prompt Template, Agent | Template-only |
| `TS-00 Connection Check (1)` | `ed883180-37ff-47ff-be69-49d7e9cebaaa` | UI duplicate of TS-00 (round-trip proxy) | **Owner to delete** (see below) |

Project: `Starter Project`, folder id `a0398c1d-c458-4dac-8e3b-8cdec2a2b98e`. All three
are `flow_type: workflow`, `a2a_enabled: false`, `mcp_enabled: true` (default).

## Export evidence and limitations

- UI export exists: Share → **Export** (dialog: Name, Description, Lock Flow,
  **Save with my API keys** unchecked by default, red caution "Exporting this flow may
  expose sensitive credentials."). The dialog was opened and **cancelled**: an export
  downloads a file to the owner's Downloads, which requires the owner's explicit approval
  and is outside the connected folder. `01-13-export-dialog.png`.
- Serialized JSON was read instead from `GET /api/v1/flows/{id}` in the signed-in tab.
  Responses were 83,941 chars (TS-00) and 155,695 chars (TS-00T). The text extractor
  returns 50,000 chars; the rest was read from zoomed on-screen views.
- Result: `langflow/templates/TS-00_connection_check.partial.json` and
  `langflow/templates/TS-00T_templates.partial.json` are **structural captures, not
  importable exports**: component source (`template.code.value`) is replaced by a
  placeholder naming module + code_hash; edges, node ids, outputs, field names, types,
  `input_types`, model value/options and flow metadata are as returned. TS-00T reuses the
  TS-00 attribute dicts for Chat Input/Output/Agent (identical code_hash); Run Flow's
  dynamic target fields are summarised; the TS-00T Agent's model and default prompt are
  marked UNKNOWN/not transcribed. Owner user_id redacted.
- To obtain byte-exact exports: owner clicks flow row menu → **Export** (keys unchecked)
  and places the files in `langflow/exports/`, or a Phase 04 script fetches
  `GET /api/v1/flows/{id}` with the bootstrap key. Then rerun the credential scan.

## Round trip (Gate 01)

- **True file re-import: NOT TESTED.** Import requires a file picker / drag-and-drop of
  an exported file ("Already have a flow? Drag and drop to upload.", Projects upload icon,
  `POST /api/v1/flows/upload/`). No exported file was available without a download.
- Weaker proxy performed: flows list → row menu → **Duplicate** created
  `TS-00 Connection Check (1)`; Playground on the duplicate returned
  `TaskSprint model connection is working.` (594 tokens, 1.4 s;
  `01-31-duplicate-playground-response.png`). The duplicate kept node ids
  (`Agent-vZq8X`, `ChatInput-80GoH`) and received a new flow id.
- The duplicate was **not deleted**: deleting is an irreversible control that needs the
  owner's own confirmation. Owner: flows list → `TS-00 Connection Check (1)` → ⋯ →
  **Delete**.

Gate 01 status: model responds (TESTED); no literal credential (TESTED on captures);
export→re-import round trip **incomplete** until the owner exports a file and it is
re-imported (Phase 01 follow-up, 2 minutes of owner clicks).

## Credential scan

Command (run on the two capture files): regex for `sk-…`, `sk-ant-…`, `AKIA…`, `xox?-`,
`gh?_…`; any `[A-Za-z0-9+/=_-]{32,}` run excluding UUIDs and placeholders; and a listing
of every password / SecretStrInput / `*key*` / `*token*` field.

Result: **no literal credential found.** Only match for long runs:
`_resolve_flow_output__ChatOutput_ca04x__message` (a method name). Secret fields:
TS-00 Agent `api_key` (password, `load_from_db: false`, value `""`); TS-00T Agent
`api_key` (same); TS-00T A2A Agent `api_key` (password, `load_from_db: true`, value `""`).
The live API responses showed the same empty values.

## Component inventory (closes the Phase 00 unknown)

Present: Agent, A2A Agent, Human Input, Run Flow (Beta), Chat Input, Chat Output,
Prompt Template, Language Model, Message History, Memory Base, API Request, Python
Interpreter, If-Else, Loop, Structured Output, Guardrails, Smart Router, Webhook, New
Custom Component button. Text Input/Output and Condition exist only as Legacy.
**Absent: MCP Tools** while no MCP server is registered (MCP sidebar "No MCP Servers
Added"). Detail: `langflow/COMPONENT_MAP.md`.

A2A publication UI exists per flow (left rail Agent icon): "Serve as an A2A agent"
toggle, disabled with the banner "A2A is turned off on this server. Set
LANGFLOW_A2A_ENABLED=true to publish and test agents." This confirms the variable name
on 1.12.5 (previously only from docs). Nothing was enabled.

## Screenshots (TaskSprint_Build_Kit/docs/screenshots/, also copied to repo docs/screenshots/)

01-01-new-flow-assistant, 01-02-components-input-output, 01-03-models-agents-catalog,
01-04-agent-added, 01-05-model-dropdown, 01-06-agent-default-instructions,
01-07-instructions-entered, 01-08-ts00-wired, 01-09-playground-response,
01-10-agent-parameters, 01-11-agent-parameters-advanced, 01-12-share-menu,
01-13-export-dialog, 01-14-api-access-placeholder (shows `YOUR_API_KEY_HERE` placeholder
only), 01-15-search-mcp, 01-16-mcp-sidebar-empty, 01-17-a2a-pane-disabled,
01-18-a2a-pane-curl, 01-19-memories-pane, 01-20-flow-activity-trace, 01-21-search-text,
01-22-search-tools, 01-23-component-filter-beta-legacy, 01-24-search-mcp-legacy-on,
01-25-text-input-legacy, 01-26-flows-list, 01-27-global-variable-selector (names only),
01-28-ts00t-templates-canvas, 01-29-flow-row-menu, 01-30-duplicated,
01-31-duplicate-playground-response. No secret value appears in any screenshot.

## Manual click path (human-equivalent)

1. Welcome screen → **Create first flow**. A new flow opens with the assistant prompt
   "What do you want to build?" over an empty canvas; ignore it (this is the blank flow).
2. Click the flow name **New Flow** at the top → **Name** = `TS-00 Connection Check` → **Save**.
3. Left rail **Components** → **Input & Output** → drag **Chat Input** and **Chat Output**;
   **Models & Agents** → drag **Agent**.
4. Drag Chat Input's right handle to the Agent's **Input** handle; drag the Agent's
   **Response** handle to Chat Output's left handle.
5. Agent → **Language Model** → **Anthropic / claude-sonnet-5-5**.
6. Agent → **Agent Instructions** → expand icon → select all, replace with the three
   lines → **Finish Editing**. (The editor autosaves.)
7. **Playground** → type `Check the model connection.` → Enter → expect
   `TaskSprint model connection is working.`
8. Template flow: Projects page → **New Flow** → rename `TS-00T Templates` → add Human
   Input, Run Flow (pick `TS-00 Connection Check`), A2A Agent, Prompt Template, Agent,
   Chat Input, Chat Output.
9. Export (owner, optional): flows list → ⋯ → **Export** → keep **Save with my API keys**
   unchecked → **Export**. Re-import: drag the file onto the flows page.
10. Clean-up: flows list → `TS-00 Connection Check (1)` → ⋯ → **Delete**.

## Changes made

Live instance: created the three flows above; set one Agent model and instructions;
selected TS-00 as the Run Flow target inside TS-00T. Not changed: settings, Model
Providers, global variables, API keys, MCP servers, A2A flag, Railway, `nuvear/langflow-railway`.
The editor's "Show Legacy" view filter was toggled on to search and toggled back off.

Repository (uncommitted; the orchestrator commits): `langflow/templates/*.partial.json`,
`langflow/COMPONENT_MAP.md`, `docs/PHASE01_REPORT.md`, Phase 01 sections appended to
`docs/OBSERVED_UI.md` and `docs/BUILD_STATUS.md`, `docs/screenshots/01-*.png`.

## Blockers and risks

1. **Byte-exact export / re-import not done** (owner download needed). Not a model blocker.
2. **MCP Tools component absent** until an MCP server is registered (Phase 04 owner step).
3. Agent built-in **Calculator** and **Current Date** tools default ON; disable in
   TaskSprint agents to keep tool trajectories clean.
4. New flows default to `mcp_enabled: true`; TS-90 must be switched off the project MCP
   server (A3) — verify the switch location in the **MCP Server** tab (Phase 09).
5. The A2A Agent client node returns only text; protocol task/context/artifact IDs are
   not outputs. A10's "thin audited adapter" decision is needed in Phase 08.
6. A2A server curl sample uses a v0.3-style `message/send` JSON shape while the client
   bundles a2a SDK 1.2.1. Read the actual card `protocolVersion` after enabling (Phase 08).
7. Duplicate flow `ed883180-…` awaits owner deletion.

## Next action

- Owner (optional, closes the round-trip gap): export TS-00 with keys unchecked, drag the
  file back onto the flows page, run Playground once, delete both copies you don't need.
- Build: Phase 03 (runner) is in progress by another agent. Phase 04 (MCP, RAG, skills,
  local) and Phase 05 (Railway services, owner approval required) come next; Phase 06
  (Langflow wiring of the app and three specialists) depends on the Phase 05 lab service
  URL and on MCP Tools appearing after an MCP server is registered.
