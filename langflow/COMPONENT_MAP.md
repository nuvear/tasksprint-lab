# Langflow 1.12.5 component map (observed 20 Oct 2026)

Source: live instance `langflow-railway-production-f493.up.railway.app`, owner's
signed-in Chrome, flows `TS-00 Connection Check` (3f476c53-e39f-4157-8f73-5e488a0a43e9)
and `TS-00T Templates` (0685ac65-234e-4752-bf76-ba45860e74be). Field data comes from
`GET /api/v1/flows/{id}` (see `templates/*.partial.json`); UI labels from the editor.
Screenshots: `TaskSprint_Build_Kit/docs/screenshots/01-*.png`.

Labels: OBSERVED = seen in UI or API response. UNKNOWN = not observed in Phase 01.
Presence of a component is not a passing integration test.

## Handle encoding (edges)

Edges carry handles as strings in which `œ` replaces `"`:

```
sourceHandle  {œdataTypeœ:œ<NodeType>œ,œidœ:œ<nodeId>œ,œnameœ:œ<outputName>œ,œoutput_typesœ:[œMessageœ]}
targetHandle  {œfieldNameœ:œ<field>œ,œidœ:œ<nodeId>œ,œinputTypesœ:[œMessageœ],œtypeœ:œstrœ}
edge id       xy-edge__<srcId><sourceHandle>-<tgtId><targetHandle>
```

`edge.data.sourceHandle` = `{dataType, id, name, output_types}`; `edge.data.targetHandle`
= `{fieldName, id, inputTypes, type}` (plain JSON objects). Node ids are
`<Type>-<5 random chars>`, e.g. `Agent-vZq8X`; Prompt Template ids contain a space
(`Prompt Template-978ge`). Duplicating a flow keeps node ids and changes only the flow id
(OBSERVED on the duplicate `ed883180-…`).

## Components

| Display name (UI) | Sidebar category | `data.type` | Module / code_hash | Inputs with handles (field: input_types) | Outputs (name: types) | Status |
|---|---|---|---|---|---|---|
| **Chat Input** | Input & Output | `ChatInput` | `lfx.components.input_output.chat.ChatInput` / 45974e6b1909 | none connectable by default (`input_value` has `input_types: []`); advanced: should_store_message, sender, sender_name, session_id, context_id, files | `message`: Message ("Chat Message") | OBSERVED, TESTED in TS-00 |
| **Chat Output** | Input & Output | `ChatOutput` | `lfx.components.input_output.chat_output.ChatOutput` / 0aab1c78e1dc | `input_value` ("Inputs"): Data, JSON, DataFrame, Table, Message (required) | `message`: Message ("Output Message") | OBSERVED, TESTED |
| **Agent** | Models & Agents | `Agent` | `lfx.components.models_and_agents.agent.AgentComponent` / 14306d4a9373 (langchain 1.3.14, langgraph 1.2.9, langchain_core 1.5.1) | `model`: LanguageModel; `system_prompt` ("Agent Instructions"): Message; `tools`: Tool (list); `input_value` ("Input"): Message; `context_id`, `format_instructions`: Message | `response`: Message; `structured_response`: Data, JSON | OBSERVED, TESTED (plain text, no tools) |
| **A2A Agent** (client) | Models & Agents | `A2AAgent` | `lfx.components.models_and_agents.a2a_agent.A2AAgentComponent` / 5cf6abad189d (a2a SDK 1.2.1, httpx 0.28.1) | `agent_url`: Message; `input_value` ("Message", required, tool_mode): Message | `response`: Message | OBSERVED (placed only; not run) |
| **Human Input** | Flow Control | `HumanInput` | `lfx.components.flow_controls.human_input.HumanInput` / 63cbbf99823f | `prompt` ("Input"): Message | one per User Choice: `branch_approve`, `branch_reject` (Message, group_outputs); optional `branch_fallback` | OBSERVED (placed only; pause/resume not run) |
| **Run Flow** (Beta) | Flow Control | `RunFlow` | `lfx.components.flow_controls.run_flow.RunFlowComponent` / ea901208037d | `session_id`: Message; after a flow is chosen: `<targetNodeId>~input_value` etc. | after a flow is chosen: `<targetChatOutputId>~message` (e.g. `ChatOutput-ca04x~message`, display "Chat Output") | OBSERVED (target selected; not run) |
| **Prompt Template** | Models & Agents | `Prompt Template` | `lfx.components.models_and_agents.prompt.PromptComponent` / e3714ffe5d15 | `template` (type `prompt`; `{var}` creates inputs); `tool_placeholder` (hidden) | `prompt`: Message | OBSERVED (placed only) |
| **MCP Tools** | — | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | **NOT IN CATALOG** while no MCP server is registered. Search "MCP" returns only an IBM watsonx bundle item. Editor MCP sidebar: "No MCP Servers Added" / **Add MCP Server**. Capture in Phase 04. |
| **Language Model** | Models & Agents | UNKNOWN (not placed) | — | — | — | OBSERVED in sidebar |
| **Message History** | Models & Agents | UNKNOWN (not placed) | — | — | — | OBSERVED in sidebar (also Files & Knowledge: **Memory Base**) |
| **Embedding Model** | Models & Agents | not placed | — | — | — | OBSERVED in sidebar |
| **API Request** | Data Sources | not placed | — | — | — | OBSERVED in sidebar. A generic HTTP tool: must not be exposed to agents (AGENTS.md) |
| **Python Interpreter** | Utilities | not placed | — | — | — | OBSERVED in sidebar. Legacy "Python …" items under Tools / Prototypes when Show Legacy is on. Must not be given to agents. |
| **New Custom Component** | sidebar footer button | — | — | — | — | OBSERVED (custom components allowed by server config) |
| **Text Input** / **Text Output** | Input & Output | not placed | — | — | — | Present only as **Legacy** (hidden unless Show Legacy is on) |
| **If-Else** | Flow Control | not placed | — | — | — | OBSERVED; **Condition…** exists as Legacy |
| **Loop** | Flow Control | not placed | — | — | — | OBSERVED |
| **Structured Output** | LLM Operations | not placed | — | — | — | OBSERVED |
| **Guardrails** | LLM Operations | not placed | — | — | — | OBSERVED (relevant to the Guardrails term; not evaluated) |
| **Smart Router** | LLM Operations | not placed | — | — | — | OBSERVED |
| **Listen** (Beta), **Notify** (Beta) | Flow Control | not placed | — | — | — | OBSERVED |
| **Webhook** | Input & Output | not placed | — | — | — | OBSERVED |

Full sidebar (Show Beta on, Show Legacy off): Input & Output (Chat Input, Chat Output,
Webhook); Data Sources (API Request, Mock Data, SQL Database, URL, Web Search); Models &
Agents (A2A Agent, Agent, Embedding Model, Language Model, Message History, Prompt
Template); LLM Operations (Batch Run, Guardrails, LLM Selector, Smart Router, Smart
Transform, Structured Output); Files & Knowledge (File System, Knowledge, Memory Base,
Read File, Write File); Processing (Data Operations, Dynamic Create Data, Parser, Split
Text, Type Convert); Flow Control (Human Input, If-Else, Listen Beta, Loop, Notify Beta,
Run Flow Beta); Utilities (Calculator, Current Date, Python Interpreter). Bundles rail:
Agentics, File Processing, Amazon, Anthropic, Azure, Cassandra, Cohere, DataStax,
Docling, Google, IBM, LangChain, Ollama, OpenAI, Oracle, ToolGuard, ….

## Agent model selection (OBSERVED)

- The Agent node has a single **Language Model** dropdown grouped by provider (not a
  separate provider + model pair). Groups shown: **Anthropic** (claude-sonnet-5-5,
  claude-opus-5-5, claude-fable-5-1) and **OpenAI** (gpt-6.1-sol, gpt-6-luna, gpt-6-sol,
  gpt-6-astra, gpt-daybreak-red-latest). Footer: **Refresh List**, **Manage Model
  Providers**. The field filters to `{"tool_calling": true}` models.
- Serialized value (`template.model.value`) is a list with one object:
  `{"name":"claude-sonnet-5-5","icon":"Anthropic","provider":"Anthropic","metadata":{… "tool_calling":true,"model_type":"llm","context_window":1000000 …}}`;
  `template.model.options` lists every enabled model with `model_class`
  (`ChatAnthropic` / `ChatOpenAI`), `model_name_param: "model"`, `api_key_param: "api_key"`.
- Agent **API Key** (`api_key`, SecretStrInput, advanced, `load_from_db: false`, value
  `""`) overrides provider settings; the info text after selecting Claude reads "Falls back
  to ANTHROPIC_API_KEY environment variable". Leave it blank; the provider key is held in
  Model Providers.

## Agent settings (OBSERVED via Parameters panel and template)

Visible on node: Language Model*, Agent Instructions, Tools (handle), Input.
Advanced (Parameters panel, each with **API** and **+ Add**/**Remove**): API Key,
Context ID, Number of Chat History Messages (default 100), Max Tokens (0 = no limit),
Output Format Instructions, Output Schema (table), Handle Parse Errors (Enabled; adds
ToolRetryMiddleware, max 2 retries), **Max Iterations (15**, min 1, maps to
ModelCallLimitMiddleware.run_limit), Stream (Enabled), **Current Date (Enabled)**,
**Calculator (Enabled)**.

Note: Current Date and Calculator are built-in tools that are ON by default. Turn both
off in TaskSprint agents so tool trajectories contain only TaskSprint tools.

Default Agent Instructions in 1.12.5 are a long structured system prompt
("You are a Langflow Agent — …", sections Identity, Safety, Using tools, Doing tasks,
Action safety, Tone, Environment) with placeholders `{current_date}`, `{model_name}`,
`{optional_user_context}`. Replace it with `prompts/` role instructions.

## Tool Mode (OBSERVED)

The node hover toolbar shows **Code | Parameters | Tool Mode (toggle) | …**. Tool Mode
appears on Agent, Prompt Template and Run Flow (after a flow is selected); not on Chat
Input/Output or Human Input. Outputs flagged `tool_mode: true` become tool outputs.
Agent-as-tool name in source: `Call_Agent`.

## Global Variable binding (OBSERVED UI; no variable created)

- Text fields that accept variables show a **globe icon** at the right edge (e.g. Agent
  Input, A2A Agent **Agent URL**). Clicking it opens a dropdown with a search box
  **Global Variables** and the variable names. Observed names: `ANTHROPIC_API_KEY`,
  `ASTRA_TOKEN`, `COMPONENT_ID`, `FIELD_NAME`, `FLOW_ID`, `OPENAI_API_KEY`
  (the two provider names appeared after HUMAN 01.1; values were not displayed).
- Serialized form when bound: UNKNOWN (no field was bound). Expected per schema:
  `load_from_db: true` and `value: "<VARIABLE_NAME>"`. Note A2A Agent `api_key` already
  serializes `load_from_db: true` with an empty value. Verify in Phase 06 with a
  non-secret Generic variable (e.g. `TASKSPRINT_API_BASE`) before relying on it.

## Run Flow specifics

- **Flow Name** dropdown lists flows in the same project; selection stores
  `flow_name_selected.value` (name), `flow_id_selected.value` (flow id) and
  `selected_metadata {id, updated_at}`.
- Target inputs become fields named `<targetNodeId>~<field>`; outputs become
  `<targetNodeId>~<output>` with method `_resolve_flow_output__<nodeId_with_underscores>__<output>`.
  These embed node ids of the target flow. After importing flows into a fresh instance,
  remap flow ids and target node ids (or re-select the flow in the UI).

## Human Input specifics (from installed source, not executed)

- Pauses the run via `graph.request_pause(reason="human_input_required", data=…)` with
  `request_id = "<nodeId>:<run_id>"`, `kind: "node_input"`, `options [{action_id,label}]`,
  `allowed_decisions`, `timeout_seconds` (default 3 Days, only with **Enable Fallback**).
- Resume picks one branch by `action_id` (label lower-cased, spaces to `_`). Matches the
  routes seen in Phase 00: `GET /api/v2/workflows/pending`, `POST /api/v2/workflows/{job_id}/resume`.
- If no branch output is connected, the node does not pause ("Skipped: no connected outputs").
- Not tested: who may resume (authorization) and persistence across restart. Phase 09.

## A2A specifics (OBSERVED UI + source; nothing enabled)

- Client: **A2A Agent** node, Mode **Internal** (flows in this project published as A2A
  agents) or **External** (Agent URL; base or `/.well-known/agent-card.json`). Optional
  API Key is sent as `x-api-key`. Timeout (s) default 60. Uses a2a SDK 1.2.1 protobuf types;
  a non-COMPLETED remote task raises an error. The node returns only reply text: protocol
  task/context/artifact IDs are not exposed as outputs. A2A10 adapter decision is still open.
- Server: left rail **Agent** icon opens the per-flow A2A pane: banner "A2A is turned off
  on this server. Set LANGFLOW_A2A_ENABLED=true to publish and test agents.", toggle
  **Serve as an A2A agent** (Off), card preview, **Address** (URL | curl), **Customize card**
  (Name, Version, Description, Tags, Examples, **Save**), **Try it** panel.
  The curl sample is `POST /api/v1/a2a/<flow_id>/jsonrpc` with
  `{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","parts":[{"kind":"text","text":"Hello"}],"messageId":"1"}}}`
  (a v0.3-style JSON shape; read the real card `protocolVersion` in Phase 08).

## Other editor surfaces (OBSERVED)

Left rail (top to bottom): Components, MCP, Bundles, Versions, Agent (A2A), Memories,
Traces ("Flow Activity": Run, Trace ID, Timestamp, Input, Output, Token, Latency, Status).
Share menu: **API access**, **Export**, **MCP Server**, **Embed into site**,
**Shareable Playground** (toggle, off). Flows list row menu: **Edit details**, **Export**,
**Duplicate**, **Delete**. New flows open an assistant prompt "What do you want to build?"
over a blank canvas (no separate "blank flow" choice).

`mcp_enabled: true` is the default on new flows (API list). Every flow is therefore
listed on the project MCP server unless switched off. TS-90 must be excluded (A3).
