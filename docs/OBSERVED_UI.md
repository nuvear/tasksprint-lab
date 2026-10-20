# Observed UI — Langflow 1.12.5

**Observed:** 20 October 2026, owner's Chrome, signed in as admin (owner signed in
privately). Viewport 1400 x 867. Read-only: nothing was clicked except the profile
menu toggle and sidebar navigation. No secret value appears in any screenshot
(credential values display as masked dots; the MCP Client config shows the literal
placeholder `YOUR_API_KEY`). Screenshots: `docs/screenshots/`.

Labels quoted verbatim in **bold**.

## Welcome screen — `/`  (`00-01-welcome.png`)

- Heading **Welcome to Langflow**, subtitle **Your new favorite way to ship Agents**.
- Cards **GitHub** and **Discord**; button **Create first flow**.
- Footer **Already have a flow? Drag and drop to upload.**
- Top bar: GitHub/Discord counters, notifications bell, profile avatar (top right).
- Status: OBSERVED, no flows exist.

## Profile menu  (`00-02-version-menu.png`)

Opened from the avatar at the upper right. Items, top to bottom:
**Version** `1.12.5 (latest)`, **Settings**, **Docs**, **GitHub**, **Discord**, **X**,
**Theme** (light / dark / system icons), **Logout**.

## Settings — page title **Settings**, subtitle **Manage the general settings for Langflow.**

Sidebar labels (exact order): **General**, **MCP Servers**, **Langflow API Keys**,
**Langflow MCP Client**, **Global Variables**, **Model Providers**, **DB Providers**,
**Shortcuts**, **Messages**.

Note: the guide text says "Settings → API Keys"; the actual label is
**Langflow API Keys** (route `/settings/api-keys`).

| Page | Route | Observed content | Screenshot |
|---|---|---|---|
| **General** | `/settings/general` | Sections **Language** (`English (Recommended)`), **Profile Picture** (**Save**), **Password** (fields **Current Password**, **Password**, **Confirm Password**; **Save**). Fields empty; not touched. | `00-03-settings-general.png` |
| **Model Providers** | `/settings/model-providers` | Subtitle **Configure AI model providers and manage their API keys.** Search box **Search providers...** List: **Anthropic**, **Azure AI Foundry**, **Google Generative AI**, **IBM WatsonX**, **Ollama**, **OpenAI**, **OpenAI Compatible**, **OpenRouter**, **vLLM**, each with a **+** control. None configured. | `00-04-settings-model-providers.png` |
| **Global Variables** | `/settings/global-variables` | Subtitle **Manage global variables and assign them to fields.** Button **Add New**. Columns **Variable Name**, **Type**, **Value**, **Apply To Fields**, **Access**, **Actions**. Rows: `ASTRA_TOKEN`, `COMPONENT_ID`, `FIELD_NAME`, `FLOW_ID`, all type **Credential**, values masked. Footer "1 to 4 of 4". | `00-05-settings-global-variables.png` |
| **Langflow API Keys** | `/settings/api-keys` | Subtitle **Your secret Langflow API keys are listed below. Do not share your API key with others, or expose it in the browser or other client-side code.** Button **Add New**. Empty state **No Data Available**. | `00-06-settings-api-keys.png` |
| **MCP Servers** | `/settings/mcp-servers` | Subtitle **Manage MCP Servers for use in your flows.** Button **Add MCP Server**. Empty state **No MCP servers added**. | `00-07-settings-mcp-servers.png` |
| **Langflow MCP Client** | `/settings/mcp-client` | Subtitle **Connect coding agents to build and run flows on this Langflow instance.** Tabs **Bob (IBM)**, **Claude Code**. JSON config: `command` `uvx`, `args` `--from lfx lfx-mcp`, env `LANGFLOW_SERVER_URL` (this instance) and `LANGFLOW_API_KEY` = `YOUR_API_KEY` placeholder. Warning: without an API key the agent must use the **login** tool with username and password. | `00-08-settings-mcp-client.png` |
| **DB Providers**, **Shortcuts**, **Messages** | — | Present in sidebar; not opened in Phase 00. | — |

## Discrepancies and observations

1. **Global variables.** Owner reported none; four Credential variables exist
   (`ASTRA_TOKEN`, `COMPONENT_ID`, `FIELD_NAME`, `FLOW_ID`). Not created by this build.
   Origin unconfirmed (possibly defaults or environment-sourced). Do not delete or edit
   them; avoid reusing these names for TaskSprint secrets.
2. **A2A disabled at server level.** `GET /api/v1/config` (authenticated) reports
   `"a2a_enabled": false`. Other relevant config: `allow_custom_components: true`,
   `custom_component_admin_only: false`, `webhook_auth_enable: true`,
   `mcp_servers_locked: false`, `authz_enabled: false`, `agentic_experience: true`,
   `default_folder_name: "Starter Project"`, `mcp_base_url: ""`.
3. **lfx-mcp client.** The instance advertises a programmatic flow-building path for
   coding agents. Using it requires a Langflow API key (inherits creator's admin
   privileges). Consider it only after Phase 01 templates exist, and never pass the
   bootstrap key to a model.

## Not yet observed (verify in Phase 01, inside the flow editor)

| Item | Why unknown |
|---|---|
| Component availability: **Agent**, **MCP Tools**, **Run Flow**, **A2A Agent**, **Human Input**, **Chat Input**, **Chat Output** | `/api/v1/all` is 2.78 MB of JSON; not reliably searchable without scripting (declined). Check the editor's component search. |
| Exact component type names, field names, input/output handles | Requires real exported templates |
| Global-variable binding syntax in exported JSON | Requires a sanitized export |
| Agent model-selection UI after a provider is configured | No provider configured yet |
| Flow-level A2A publication controls (`flow_type=agent`, `a2a_enabled`) in the UI | Schema fields exist (`FlowCreate.flow_type` enum `workflow`/`agent`, `a2a_enabled`, `a2a_card_overrides`); UI location unknown; server flag off |
| Human Input pause/resume behaviour and persistence scope | Only routes observed (`/api/v2/workflows/pending`, `/resume`) |
| Variables / API-key REST routes | Absent from OpenAPI; UI pages exist |


## Phase 01 additions — flow editor (20 Oct 2026, 04:49–05:06 UTC)

Observed in the owner's Chrome while building `TS-00 Connection Check` and
`TS-00T Templates`. Screenshots `01-01` … `01-31`. Field-level detail:
`langflow/COMPONENT_MAP.md`.

- **Create first flow** opens a new flow named **New Flow** directly, showing an
  assistant prompt **What do you want to build?** (model chip `claude-sonnet-5-5`),
  **Or start from a template:** **Simple Agent**, **Vector Store RAG**, **Browse more...**
  over an empty canvas. There is no separate "blank flow" choice. (`01-01`)
- Rename: click the flow name → popover **Name**, **Description**, **Lock Flow**,
  **Cancel**/**Save**; toast **Changes saved successfully**.
- Editor left rail (tooltips/labels): **Components**, **MCP**, **Bundles**, **Versions**,
  **Agent**, **Memories**, **Traces**. Components search box **Search** with `/` shortcut;
  filter icon reveals **Show Beta** (on) and **Show Legacy** (off). (`01-23`)
- Component categories: **Input & Output**, **Data Sources**, **Models & Agents**,
  **LLM Operations**, **Files & Knowledge**, **Processing**, **Flow Control**,
  **Utilities**, **Discover more components**, footer **New Custom Component**.
- Present: **Agent**, **A2A Agent**, **Human Input**, **Run Flow** (Beta), **Chat Input**,
  **Chat Output**, **Prompt Template**, **Language Model**, **Message History**, **API
  Request**, **Python Interpreter**, **If-Else**, **Loop**, **Structured Output**,
  **Guardrails**. Legacy only: **Text Input**, **Text Output**, **Condition…**.
  **MCP Tools: not in the catalog**; MCP rail shows **No MCP Servers Added** /
  **Add MCP Server**. (`01-15`, `01-16`, `01-24`)
- Agent node: **Language Model*** (one dropdown grouped **Anthropic** / **OpenAI**, footer
  **Refresh List**, **Manage Model Providers**), **Agent Instructions** (expand →
  **Edit text content** / **Finish Editing**), **Tools** handle, **Input**, output
  **Response**. Hover toolbar **Code | Parameters | Tool Mode | …**. **Parameters** opens
  **Component Parameters** ("Adjust component parameter visibility and define API
  inputs.") with **API** and **+ Add**/**Remove** per field. (`01-04`, `01-05`, `01-10`, `01-11`)
- Playground: **Sessions** / **Default Session**; reply header **AI**, **Finished in**,
  token count and seconds. (`01-09`)
- Share menu: **API access**, **Export**, **MCP Server**, **Embed into site**,
  **Shareable Playground** (toggle). API access shows `YOUR_API_KEY_HERE` placeholder,
  tabs **v1** / **v2 BETA**, **Python** / **JavaScript** / **cURL**. Export dialog:
  **Save with my API keys** (unchecked) + caution text. (`01-12` – `01-14`)
- A2A pane (rail **Agent**): banner **A2A is turned off on this server. Set
  LANGFLOW_A2A_ENABLED=true to publish and test agents.**; **Serve as an A2A agent**
  toggle **Off** ("Off. Nobody can reach it yet."); **Address** **URL** / **curl**;
  **Customize card** (Name, Version, Description, Tags, Examples, **Save**); **Try it**
  "A2A is off on this server, so there is nothing to call yet." (`01-17`, `01-18`)
- Traces rail → **Flow Activity** table (Run, Trace ID, Timestamp, Input, Output, Token,
  Latency, Status). Memories rail → **Memories**, **+ Create**. Versions rail →
  **Version History**, "Save a version of your flow" / **Keep Building** / **Save**.
- Global-variable picker: globe icon on text fields → search **Global Variables**;
  names now include `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` (created by Model Providers
  setup) besides the four Phase 00 names. Values not shown. (`01-27`)
- Flows list row menu: **Edit details**, **Export**, **Duplicate**, **Delete**; toast
  **Flow duplicated successfully**; duplicate named `TS-00 Connection Check (1)`. (`01-29`, `01-30`)

### Phase 00 unknowns now resolved

| Item | Result |
|---|---|
| Component availability | Present except MCP Tools (needs a registered MCP server) |
| Type names, fields, handles | `langflow/COMPONENT_MAP.md`, `langflow/templates/*.partial.json` |
| Agent model selection | Single grouped **Language Model** dropdown; value is a list with `{name, provider, metadata}` |
| Flow-level A2A controls | Rail **Agent** pane, **Serve as an A2A agent** toggle (disabled by server flag) |
| Global-variable binding syntax in JSON | Still UNKNOWN (no field was bound) |
| Human Input pause/resume, persistence | Source read only; not executed (Phase 09) |

## Phase 06 additions — globals, MCP servers, MCP Tools, Playground (20 Oct 2026, 11:36–12:05 UTC)

Screenshots `06-01` … `06-28`. Detail and evidence IDs: `docs/PHASE06_REPORT.md`.

- **Global Variables** after `scripts/import_globals.py`: rows `TASKSPRINT_API_BASE` **Generic**
  (value shown in clear, truncated: `https://tasksprint-lab-pr…`) and `TS_APP_TOKEN`,
  `TS_COORD_TOKEN`, `TS_DEV_TOKEN`, `TS_OPS_TOKEN`, `TS_PO_TOKEN`, `TS_QA_TOKEN` **Credential**
  (value `*****`); footer "1 to 13 of 13". (`06-01`) The REST payload the server accepts is
  `POST /api/v1/variables/ {name, value, type: "Generic"|"Credential", default_fields: []}`;
  `GET` returns `value: null` plus `has_value` for every row.
- **Add MCP Server** dialog: title **Add MCP Server**, subtitle **Add and save MCP servers to use
  across your flows.**, tabs **JSON** (textarea **Paste in JSON config**), **STDIO**,
  **Streamable HTTP/SSE**. The HTTP tab has **Name***, **Streamable HTTP/SSE URL***, **Headers**
  (key field **Type key...**, value field **Type a value...** with a **globe** icon, **+** adds a
  row, **×** removes), **Environment Variables** (key/value, **+**), buttons **Cancel**,
  **Add Server**. There is no separate transport selector beyond the tabs. (`06-02`, `06-03`)
- **Header value ↔ global variable — exact mechanism.** The globe opens **Search global
  variables...** with all variable names (`06-04`); choosing one replaces the whole value with a
  green chip, e.g. `TS_PO_TOKEN ×` (`06-05`) — a whole-value reference with no room for the
  `Bearer ` prefix. Typing the text `Bearer {{TS_PO_TOKEN}}` into the value field is kept as text
  (`06-06`) and is resolved by Langflow at connect time (`{{NAME}}` placeholder, lfx 1.12.5).
  **This is the binding used for every TaskSprint server.** Saved list: **Added MCP Servers**
  `tasksprint-product-owner` **2 tools** (`06-08`); after the script, six servers with 2/6/5/2/7/12
  tools (`06-09`). Reads (`GET /api/v2/mcp/servers/{name}`) return header values masked as
  `********`.
- **Flow editor, left rail MCP** (`06-14`): heading **MCP Servers**, one row per server (drag
  handle, **+** on hover), footer **Add MCP Server**, **Manage Servers**. A project MCP server
  `lf-tasksprint` appeared automatically after the `TaskSprint` project was created.
- **MCP Tools node** (dragging a server row onto the canvas creates it, server preselected):
  fields **MCP Server** (dropdown + refresh), **Tool*** (**Select a tool**) and output
  **Response** before Tool Mode; hover toolbar **Code | Parameters | Tool Mode | …**. With
  **Tool Mode** on the node shows **Actions** (tool chips such as `GET_SPRINT_STATE`,
  `SEARCH_APPROVED_KNOWLEDGE`, "+2 more") and the output **Toolset** (cyan handle), which
  connects to the Agent **Tools** handle (tooltip "Input type: Tool"). (`06-15`, `06-16`, `06-19`,
  `06-23`) Serialized: node type `MCP`, output `component_as_tool` (`Tool`), edge target field
  `tools` type `other`; `template.mcp_server.value = {name, config:{url, verify_ssl, headers}}`
  where, after save, each header value is the NAME of an auto-created Credential global
  `MCP_<SERVER>_<HEADER>_<hash>`; `tools_metadata.value` lists the tools.
- **Custom component with bound variables** (`06-13`): **Role token** shows the green chip
  `TS_PO_TOKEN ×`; serialized `load_from_db: true`, `value: "TS_PO_TOKEN"`, `password: true`.
- **Playground with an Agent using MCP tools**: each tool call is a collapsible row with the
  tool name in capitals and its latency (e.g. `SEARCH APPROVED KNOWLEDGE 105ms`); a failed call
  reads **ERROR USING GET SPRINT STATE** with a red dot (`06-27`); header **Finished in** with
  token count and seconds (e.g. 8.1K | 13.2s). Sessions panel lists **Default Session** and any
  API-supplied `session_id`. (`06-17`, `06-20`, `06-24`)
- **Unsaved-changes guard:** after a Playground run the editor holds unsaved changes; navigating
  away is blocked by a "Leave site?" dialog until **Ctrl+S** (toast **Flow saved successfully!**).
- Loading a flow whose edge handle type is wrong shows a red toast **Some connections were removed
  because they were invalid:** listing the edge (seen once with a hand-built Chat Output edge of
  type `str`; correct type is `other`). (`06-10` shows the fixed flow.)
- Not observed in Phase 06: the custom-component code editor's save button label; the
  project-creation dialog (project created by API).

## Phase 07 additions — Bounded Toolset, Run Flow tools, Sprint Room Playground (20 Oct 2026, 12:15–12:50 UTC)

- **Custom component compile rule (1.12.5):** an input named after a component method is refused
  by `POST /api/v1/custom_component` with "has input(s) 'run' named after a method of the component,
  so `self.<name>` would return the method instead of the configured value. Rename the input."
  (hence the toolset input is `run_info`, display name **Run**).
- **Multiple outputs:** without `group_outputs=True` a node shows one output with a selector
  (e.g. **Message ⌄**) and edges from the other outputs are not drawn; with it the Run Context
  shows **Message**, **Run ID** and **Run** handles at once (`07-01`). A `DataInput` is rendered as
  a JSON input (`_input_type: JSONInput`, accepts `Data`/`JSON`); the Data output type reads `JSON`.
- **TaskSprint Bounded Toolset node** (`07-01`, `07-03`): title with shield icon, fields **Run\***,
  **Role** (dropdown: product_owner, developer, qa, coordinator), **Role token** (green chip
  `TS_QA_TOKEN ×`), for the coordinator **Run Flow: TS-01 Product Owner**, **Run Flow: TS-02
  Developer**, **Run Flow: TS-03 QA** (cyan Tool handles); output **Toolset** (cyan) → Agent **Tools**.
- **Run Flow (Beta) node** (`07-03`): fields **Flow Name** (dropdown with refresh; lists flows of
  the same project), **Session ID** (advanced by default; made visible), **Actions** (after Tool
  Mode: chip `TS-01-PRODUCT-OWNER_TOOL`), output **Toolset**. Serialized: type `RunFlow`,
  `flow_name_selected` / `flow_id_selected`, dynamic fields `ChatInput-<id>~input_value`,
  `…~should_store_message`, `…~sender`, `…~sender_name`, `…~session_id`, `…~context_id`, `…~files`;
  only `~input_value` is a tool argument (inside `flow_tweak_data`). Tool Mode replaces the outputs
  with `component_as_tool` and adds `tools_metadata` (name `TS-01-Product-Owner_tool`, description
  "Tool designed to execute the flow 'TS-01 Product Owner'. Flow details: <flow description>.").
  Selecting a flow and switching Tool Mode both go through `POST /api/v1/custom_component/update`.
- **Canvas toolbar** (bottom): zoom percentage, **^**, a page icon, a shrink/expand-nodes toggle
  (collapses every node to its title bar, `07-02`), **?**.
- **Playground, Sprint Room:** tool rows read e.g. `GET SPRINT STATE 128ms`, `READ PREFERENCES`,
  `SAVE PREFERENCE 98ms`, `READ TEST REPORT`, `ACCESSING ASK DEVELOPER 3982ms`, `ACCESSING TS-02-DEVELOPER
  TOOL 50ms` (a delegation shows both the wrapper and the inner Run Flow tool); expanding a row shows
  the raw JSON result, e.g. `{"error": {"code": "TEST_RUN_NOT_FOUND", …}}` (`07-09`). Header
  **Finished in** with tokens and seconds (6.9K | 7.1s). The delegated specialist's own Chat Output
  message is also displayed in the Sprint Room session, before the coordinator's answer (`07-04`).
- **Sessions:** **+** next to **Sessions** creates "New Session 0", "New Session 1", … ; Default
  Session's id is the flow id; API runs appear under their `session_id`. Child sessions created by
  Run Flow appear in the specialist flow's Playground named after the coordinator run id
  (`run_a1b79b91af531e…`, `07-12`).
- **Agent behaviour observed:** the Agent can issue several tool calls in one step (parallel);
  results may complete out of order.
- **API tweaks:** `POST /api/v1/run/{flow_id}` with `tweaks: {"TaskSprintBoundedToolset-<id>":
  {"max_actions": 2}}` (or `invocation_timeout_s`) was accepted for these custom-component fields
  and applied to that run only.
- Still not observed: the custom-component code editor's save button label; the label of the
  node's advanced-settings panel in this phase (fields were set by the setup script).

## Phase 08 additions — A2A publishing, Agent Card, API keys (20 Oct 2026, 13:00–13:30 UTC)

**A2A enabled (verified before any Phase 08 change).** After the owner-approved
`LANGFLOW_A2A_ENABLED=true` redeploy: `GET /api/v1/config` → `"a2a_enabled": true`;
`GET /api/v1/a2a/agents` (bootstrap key) → `200 []`; the rail **Agent** pane no longer shows the
Phase 01 banner "A2A is turned off on this server…" (`08-04`, TS-30 viewed, nothing changed).

**Agent pane (left rail icon "Agent", robot), exact labels** (`08-04`, `08-07`, `08-08`):
* Header **Serve as an A2A agent** with a toggle and a status chip. States observed:
  **Draft** + "Off. Nobody can reach it yet." → after switching on: **Draft** + "Turn on, then save to
  publish." → after **Save**: **Live** + "Live. Reachable at the address below."
* Card preview: flow name, "from this flow" (after publish "1.12.5 · from this flow"); before publish
  "Not reachable yet. Publish to expose it." / "Publish to preview the input contract and address
  callers use."; after publish "Requires an API key (x-api-key)", **Input contract** "what a caller
  sends": `input_value` string optional, `session_id` string optional.
* **Address** with tabs **URL** / **curl**, a read-only text box and a copy button
  (accessible name "Copy agent card URL").
* **Customize card** "Optional. Overrides what the card advertises. Leave blank to use the flow's own
  name and description." Fields **Name**, **Version**, **Description**, **Tags** ("Keywords that help
  people find this agent.", placeholder "e.g. billing"), **Examples** ("Sample prompts shown to
  callers. They don't affect how it runs."), button **Save**; toast **Agent updated**.
* Right side **Try it** "over the live A2A endpoint": before publish "Publish the agent to test it over
  the live endpoint."; after: "Send a message to start a conversation with the live agent.", an
  **x-api-key for this agent** field ("This agent is behind an API key. Paste a valid key to test it."),
  **Message the agent**, **Send** (Send stays disabled without a key, so the UI cannot demonstrate a
  server-side denial; that test is by script, see PHASE08_REPORT).
* Saving with the toggle on sent `PATCH /api/v1/flows/{id}` and the flow became `flow_type=agent`,
  `a2a_enabled=true` (`a2a_card_overrides={}`); then `GET .../.well-known/agent-card.json` 200.
  No separate "save as agent type" step was needed: the pane's Save sets the type.

**Card URL format.** `<base>/api/v1/a2a/<flow id>/.well-known/agent-card.json`; JSON-RPC
`<base>/api/v1/a2a/<flow id>/jsonrpc`. **Observed discrepancy:** `GET /api/v1/a2a/agents` (`cardUrl`)
and the card's own `url` use **`http://`**langflow-railway-production-f493.up.railway.app (Langflow
behind Railway's TLS proxy builds URLs from the plain-HTTP request); Railway answers `http://` with
**301** to `https://`. The same card is served on `https://`. The trusted adapter therefore fetches
the card over https and upgrades the advertised RPC scheme to https (same host/path/transport),
recording that it did so; it never sends the key over http. The native **A2A Agent** node would treat
the `http://` RPC url as off-origin and strip `x-api-key` (lfx 1.12.5 `build_a2a_client`).

**Settings → Langflow API Keys** (`08-05`, Key column masked in the saved copy): columns **Name**,
**Key** (masked prefix), **Created**, **Last Used**, **Expires**, **Total Uses**; **Add New** button;
footer delete/refresh, "1 to 4 of 4". The page loads `GET /api/v1/api_key/`. Rows now:
`MCP Project TaskSprint - default`, `tasksprint-bootstrap`, `tasksprint-a2a-runtime` (new, expires
2027-01-18), `MCP Project Starter Project - default`. Times are shown in the browser's local zone (SGT).

**TS-10 canvas** (`08-09`, `08-10`): new node **TaskSprint A2A Audit** (fields **Agent card URL (fixed
peer)**, **Peer flow ID**, **A2A API key** = chip `TS_A2A_API_KEY`, **Coordinator token (audit)** =
chip `TS_COORD_TOKEN`; output **Toolset**) wired into the Bounded Toolset's new input
**A2A peer: TS-20 Production Manager**. Scrolling on the canvas zooms (40% → 26%).

**Peer off / on (live checks, `08-16`, `08-18`).** Switching **Serve as an A2A agent** off and pressing
**Save** returns the pane to **Draft** "Off. Nobody can reach it yet." with "Not reachable yet. Publish to
expose it." and toast **Agent updated**; the card answers 404 and `a2a_enabled=false` (`flow_type` stays
`agent`). Switching on + Save returns to **Live**. The Playground lists the adapter's inner call as a
separate step **TS20 PRODUCTION MANAGER A2A** under **ASSESS PRODUCTION RELEASE** (`08-12`). Leaving the
TS-10 editor after a Playground run showed the toast **Flow saved successfully!**; a direct URL navigation
was instead blocked by the browser's "Leave site?" dialog, so the breadcrumb **TaskSprint** was used.

## Phase 09 additions — Human Input, TS-90, project MCP server tools (20 Oct 2026, 14:15–14:30 UTC)

**Human Input in the Playground (`09-08`).** A run that reaches Human Input shows a chat card titled
**Waiting for Human Input** with the node's **Input** text rendered as Markdown (single newlines merge into
one paragraph; a fenced block becomes a horizontally scrolling code box) and one button per **User Choice**:
**Approve** (white) and **Reject** (red). Clicking sends `POST /api/v2/workflows/{job_id}/resume`; the card
then keeps only the chosen button with a check mark ("✓ Approve" / "✓ Reject") and the chosen branch's
Chat Output message appears below (`09-09`, `09-12`). The editor polls `GET /api/v2/workflows/pending?flow_id=…`
(also for other open flows). The pending entry carries `request_id` `<HumanInput node id>:<job id>`, `kind`
`node_input`, `options` `[{label, action_id}]`, `allowed_decisions`. Playground runs are background jobs
(`POST /api/v2/workflows`), so the job id is the run id.

**Reload (`09-10`).** After a reload the resolved card and the decision message remain in the session.
**Stale card (`09-13`).** If the suspended job was cancelled (`POST /api/v2/workflows/stop` → "Job … cancelled
successfully."), clicking a button still turns the card into "✓ Approve", but `/resume` answers **409**
and no message appears. Repeat resume of a completed job: 409 `NOT_RESUMABLE` "Job is not suspended, already
resumed, or the request_id is stale."

**Sessions.** The Playground's **+** next to **Sessions** creates "New Session 0", "New Session 1", …; the
first is "Default Session".

**Project → MCP Server tab (`09-04`, `09-05`).** **Flows/Tools** "No actions added to this server", **Edit
Tools** opens **MCP Server Tools** with columns **Flow Name**, **Description**, **Tool**, **Requires
Approval** (toggle) and a checkbox per flow (TS-90 listed as `TS_90_INSTRUCTOR_CONSOLE`, unchecked). Right
side: **Auth: ✓ API Key**, **Edit Auth**, tabs **Auto install** / **JSON**, OS tabs, **Transport** SSE /
Streamable HTTP, JSON with placeholder `YOUR_API_KEY`, **Generate API key** (not clicked).

**Agent pane for a non-agent flow (`09-03`).** TS-90 shows **Serve as an A2A agent** with the **Draft** chip
and toggle off, "Off. Nobody can reach it yet.", the flow name/description card, "Not reachable yet. Publish
to expose it.", **Address** URL/curl and **Customize card** (not saved).

**Global Variables (`09-01`).** The three new Credential rows `TS_APPROVER_TOKEN`, `TS_EVALUATOR_TOKEN`,
`TS_INSTRUCTOR_TOKEN` show value `*****`; table "1 to 23 of 23".

**Editor state.** Returning to a flow's canvas after Playground runs (TS-20, TS-90) left the editor with
unsaved client changes; navigating away raised the browser's "Leave site?" dialog, which was discarded.
The server copies were unchanged (`import_flows.py --dry-run` keep ×7).

