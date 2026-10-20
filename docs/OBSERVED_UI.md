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
