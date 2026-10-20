# TaskSprint Bounded Toolset: trusted Langflow custom component (Architecture A8, A9; Phase 07).
# Exposes exactly the authenticated role's allowlisted TaskSprint MCP tools to an Agent, plus (for
# the coordinator only) three fixed delegation tools wrapping the Run Flow tools of TS-01/02/03.
# Every MCP tool call opens a fresh Streamable-HTTP MCP session that carries the server-issued run
# from the TaskSprint Run Context (X-TaskSprint-Run), so each Agent invocation is charged to its own
# run. The harness counts actions (tool calls and delegations, not model iterations), enforces the
# per-invocation budget and deadline, per-call timeouts, delegation depth, one repair cycle and
# no-progress stopping, and returns structured errors instead of raising. The model cannot change
# any limit: limits are component inputs, never tool arguments. The lab enforces the same budgets
# independently (8 actions per run, 12 for operations since 1.2.0; 24 per run tree, depth 2, 90 s / 180 s deadlines).
# 1.1.0 (Phase 08): the operations role (TS-20 Production Manager) and, for the coordinator, one fixed A2A
# delegation `assess_production_release` (the name prompts/coordinator.md uses; it carries
# the typed assess_release task), which accepts only the TaskSprint A2A Audit adapter's peer tool. The toolset
# (not the model) builds the typed assess_release payload from contracts/handoff-task.schema.json 1.1, counts
# the delegation as one action charged to the parent run, allows it once per turn and passes the parent run
# as the A2A contextId (lineage). The model supplies only the three evidence references.
# 1.2.0 (Phase 12): per-role action caps mirroring the lab's fixed table (operations 12, every other role 8);
# the flow's max_actions input is clamped to its role's cap, so a flow author still cannot exceed the lab.
# Version 1.2.0. Source of truth: tasksprint-lab/components/bounded_toolset.py
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import re
import time
from typing import Any
from urllib.parse import urlparse

import anyio
import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, DropdownInput, FloatInput, HandleInput, IntInput, MessageTextInput, Output, SecretStrInput
from lfx.schema.json_schema import create_input_schema_from_json_schema

ADAPTER_VERSION = "bounded_toolset/1.2.0"
# Per-invocation action caps; the same fixed table as services/lab/config.py (RUN_MAX_ACTIONS_BY_ROLE, default 8).
DEFAULT_MAX_ACTIONS = 8
ROLE_MAX_ACTIONS: dict[str, int] = {"operations": 12}
WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
RUN_RE = re.compile(r"^run_[0-9a-f]{32}$")
# Fixed per-role allowlist = the lab's Phase 04 visibility matrix. A tool the lab lists but this
# table does not name is not exposed; a tool named here but not listed by the lab is not exposed.
ALLOWLIST: dict[str, tuple[str, ...]] = {
    "product_owner": ("get_sprint_state", "search_approved_knowledge"),
    "developer": ("get_sprint_state", "search_approved_knowledge", "list_skills", "load_skill", "read_candidate",
                  "submit_candidate"),
    "qa": ("get_sprint_state", "read_candidate", "run_candidate_tests", "read_test_report", "read_recent_events"),
    "coordinator": ("get_sprint_state", "record_story", "transition_story", "read_preferences", "save_preference",
                    "read_test_report", "read_recent_events"),
    "operations": ("get_sprint_state", "list_skills", "load_skill", "read_candidate", "read_test_report",
                   "get_release_readiness", "create_release_plan", "read_release_plan", "execute_approved_plan",
                   "get_release_status", "get_app_health", "read_recent_events"),
}
# Delegation slots: fixed tool name, the only flow allowed in the slot, and its purpose.
DELEGATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("product_owner_flow", "ask_product_owner", "TS-01 Product Owner",
     "Delegate a scope or acceptance-criteria question to the Product Owner specialist (TS-01). It retrieves "
     "approved requirement evidence and returns a cited story proposal or answer. It cannot approve scope."),
    ("developer_flow", "ask_developer", "TS-02 Developer",
     "Delegate implementation or ONE repair of the complete(tasks, task_id) candidate to the Developer specialist "
     "(TS-02). For a repair, include the failing test report ID and the failed assertions (expected/actual). "
     "Returns the new candidate ID and hash. Submission is not a test pass."),
    ("qa_flow", "ask_qa", "TS-03 QA",
     "Delegate an independent protected-suite run for one exact candidate ID to the QA specialist (TS-03). "
     "Returns the runner-written test report ID and the failed assertions, if any."),
)
# The one A2A delegation (coordinator only): slot, tool name, peer, the adapter tool it accepts, purpose.
A2A_PEER: tuple[str, str, str, str, str] = (
    "operations_peer", "assess_production_release", "TS-20 Production Manager", "ts20_production_manager_a2a",
    "Ask the independent Production Manager (TS-20, over A2A) to ASSESS a release of one exact tested candidate. "
    "Give the candidate ID, its sha256 and the passing protected test report ID. Operations fetches its own "
    "evidence and returns a release plan reference or a blocked assessment. This never deploys and is not an "
    "approval: a human must review and approve any plan separately. Once per turn.")
A2A_PAYLOAD_SCHEMA_VERSION = "1.1"
# Lab errors after which the run can do nothing more in this invocation.
TERMINAL_LAB_CODES = {"BUDGET_EXHAUSTED", "RUN_EXPIRED", "RUN_NOT_ACTIVE", "RUN_STALE_GENERATION", "RUN_NOT_BOUND",
                      "WORKSPACE_INACTIVE", "UNAUTHENTICATED"}
NO_PROGRESS_REPEATS = 3  # the same call with the same arguments a third time stops the invocation
MAX_RESULT_CHARS = 8000


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class DelegationArgs(BaseModel):
    request: str = Field(..., min_length=1, max_length=4000,
                         description="The bounded task for the specialist: what to do, with the exact IDs it needs.")


class AssessArgs(BaseModel):
    candidate_id: str = Field(..., pattern=r"^cand_[0-9a-f]{24}$", description="Exact candidate ID to assess.")
    candidate_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$", description="That candidate's sha256.")
    app_test_run_id: str = Field(..., pattern=r"^tr_[0-9a-f]{24}$",
                                 description="The protected test report ID that passed for this exact hash.")


class _Ledger:
    """Per-invocation harness state. Lives only for one build of this component (one flow run)."""

    def __init__(self, run: dict, max_actions: int, invocation_timeout_s: float):
        self.run = run
        self.max_actions = max_actions
        server_deadline = run.get("deadline_epoch") or (time.time() + invocation_timeout_s)
        self.deadline = min(time.time() + invocation_timeout_s, server_deadline)
        self.actions = 0
        self.delegations: dict[str, int] = {}
        self.calls: dict[str, int] = {}
        self.stopped: dict | None = None
        self.trace: list[dict] = []

    def remaining(self) -> float:
        return self.deadline - time.time()

    def view(self) -> dict:
        return {"scope": "this Agent invocation (trusted wrapper; the lab's own run budget is reported separately "
                         "as 'budget')",
                "run_id": self.run["run_id"], "role": self.run.get("role"), "depth": self.run.get("depth"),
                "invocation_actions_used": self.actions, "invocation_max_actions": self.max_actions,
                "remaining_s": max(0, round(self.remaining(), 1)), "delegations": dict(self.delegations),
                "invocation_stopped": self.stopped}

    def stop(self, code: str, message: str) -> None:
        if self.stopped is None:
            self.stopped = {"code": code, "message": message}


class TaskSprintBoundedToolset(Component):
    display_name = "TaskSprint Bounded Toolset"
    description = ("Trusted harness: exposes only this role's allowlisted TaskSprint MCP tools (fresh MCP session per "
                   "call, bound to the Run Context's server-issued run) and, for the coordinator, three fixed "
                   "specialist delegations plus one fixed A2A assessment peer (TS-20), with action budgets, "
                   "deadlines, depth and repair limits.")
    icon = "shield-check"
    name = "TaskSprintBoundedToolset"

    inputs = [
        DataInput(name="run_info", display_name="Run", required=True,
                  info="Connect the 'Run' output of the TaskSprint Run Context in this flow."),
        DropdownInput(name="expected_role", display_name="Role", options=list(ALLOWLIST), value="product_owner",
                      info="The role this flow's credential must authenticate as. Fixes the tool allowlist."),
        SecretStrInput(name="role_token", display_name="Role token", value="", load_from_db=True,
                       info="Bind the same Credential global as the Run Context (TS_PO_TOKEN, TS_DEV_TOKEN, ...)."),
        MessageTextInput(name="api_base", display_name="TaskSprint API base", value="TASKSPRINT_API_BASE",
                         load_from_db=True, advanced=True, info="Bind the Generic global TASKSPRINT_API_BASE."),
        MessageTextInput(name="workspace", display_name="Workspace", value="demo-001", advanced=True),
        IntInput(name="max_actions", display_name="Max tool actions per invocation", value=8, advanced=True,
                 info="Tool calls plus delegations in one Agent invocation. Clamped to the role's lab cap "
                      "(operations 12, every other role 8)."),
        FloatInput(name="invocation_timeout_s", display_name="Invocation deadline (s)", value=90.0, advanced=True,
                   info="90 for a specialist, 180 for the coordinator. Never later than the lab run's deadline."),
        FloatInput(name="tool_timeout_s", display_name="Per-call timeout (s)", value=30.0, advanced=True),
        IntInput(name="max_depth", display_name="Max delegation depth", value=2, advanced=True),
        IntInput(name="max_repairs", display_name="Repair cycles per turn", value=1, advanced=True,
                 info="Developer and QA may each be asked 1 + this many times in one coordinator turn."),
        FloatInput(name="delegation_timeout_s", display_name="Delegation timeout (s)", value=90.0, advanced=True),
        HandleInput(name="product_owner_flow", display_name="Run Flow: TS-01 Product Owner", input_types=["Tool"],
                    required=False, info="Coordinator only: the Toolset of a Run Flow set to TS-01 Product Owner."),
        HandleInput(name="developer_flow", display_name="Run Flow: TS-02 Developer", input_types=["Tool"],
                    required=False, info="Coordinator only: the Toolset of a Run Flow set to TS-02 Developer."),
        HandleInput(name="qa_flow", display_name="Run Flow: TS-03 QA", input_types=["Tool"], required=False,
                    info="Coordinator only: the Toolset of a Run Flow set to TS-03 QA."),
        HandleInput(name="operations_peer", display_name="A2A peer: TS-20 Production Manager", input_types=["Tool"],
                    required=False, info="Coordinator only: the Toolset of the TaskSprint A2A Audit adapter bound to "
                    "the TS-20 Production Manager card."),
        FloatInput(name="a2a_timeout_s", display_name="A2A assessment timeout (s)", value=90.0, advanced=True),
    ]
    outputs = [Output(display_name="Toolset", name="component_as_tool", method="to_toolkit", types=["Tool"],
                      cache=False)]

    # ------------------------------------------------------------------ configuration checks
    def _config(self) -> tuple[str, str, str, dict]:
        base = (self.api_base or "").strip().rstrip("/")
        u = urlparse(base)
        if u.scheme != "https" or not u.hostname or u.path or u.query or u.fragment or u.username:
            raise ValueError("TASKSPRINT_API_BASE must be an https origin without a path")
        workspace = (self.workspace or "").strip()
        if not WORKSPACE_RE.match(workspace):
            raise ValueError("workspace id is invalid")
        token = self.role_token or ""
        if len(token) < 32:
            raise ValueError("role token is not bound (Credential global variable missing)")
        raw = self.run_info
        data = getattr(raw, "data", raw) if raw is not None else None
        if not isinstance(data, dict) or not RUN_RE.match(str(data.get("run_id", ""))):
            raise ValueError("connect the Run output of the TaskSprint Run Context (no server-issued run)")
        if data.get("role") != self.expected_role:
            raise ValueError(f"run role {data.get('role')!r} does not match this toolset's role {self.expected_role!r}")
        return base, workspace, token, dict(data)

    def _headers(self, token: str, workspace: str, run_id: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "X-TaskSprint-Workspace": workspace, "X-TaskSprint-Run": run_id,
                "User-Agent": ADAPTER_VERSION}

    # ------------------------------------------------------------------ MCP over Streamable HTTP (official SDK)
    async def _session_do(self, url: str, headers: dict, timeout: float, fn):
        from mcp import ClientSession  # Langflow 1.12 ships mcp>=1.17,<2

        try:
            from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
        except ImportError:  # older 1.x SDK
            create_mcp_http_client = None
            from mcp.client.streamable_http import streamablehttp_client
        with anyio.fail_after(timeout):
            if create_mcp_http_client is not None:
                async with create_mcp_http_client(headers=headers, timeout=httpx.Timeout(timeout)) as http:
                    async with streamable_http_client(url, http_client=http) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            return await fn(session)
            async with streamablehttp_client(url, headers=headers, timeout=timeout) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await fn(session)

    async def _list_tools(self, base: str, workspace: str, token: str, run_id: str) -> list:
        async def do(session):
            return (await session.list_tools()).tools
        return await self._session_do(base + "/mcp", self._headers(token, workspace, run_id),
                                      float(self.tool_timeout_s or 30), do)

    # ------------------------------------------------------------------ results
    @staticmethod
    def _out(payload: dict, ledger: _Ledger) -> str:
        # The harness view is a snapshot when this result is returned; parallel calls can finish in any order.
        payload = {**payload, "harness": ledger.view()}
        text = json.dumps(payload, sort_keys=True, default=str)
        return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "...[truncated]"

    def _refuse(self, ledger: _Ledger, tool: str, code: str, message: str, terminal: bool = True) -> str:
        if terminal:
            ledger.stop(code, message)
        ledger.trace.append({"tool": tool, "outcome": "refused", "code": code})
        return self._out({"error": {"code": code, "message": message, "source": "harness"}}, ledger)

    def _gate(self, ledger: _Ledger, tool: str, key: str) -> str | None:
        """Checks before any action; returns a structured refusal or None."""
        if ledger.stopped is not None:
            return self._refuse(ledger, tool, "HARNESS_STOPPED",
                                f"this invocation already stopped ({ledger.stopped['code']}); escalate to the human",
                                terminal=False)
        if ledger.remaining() <= 0:
            return self._refuse(ledger, tool, "INVOCATION_DEADLINE_PASSED",
                                "the invocation deadline has passed; stop and escalate")
        if ledger.actions >= ledger.max_actions:
            return self._refuse(ledger, tool, "BUDGET_EXHAUSTED",
                                f"the action budget of {ledger.max_actions} for this invocation is used; stop and "
                                "escalate")
        ledger.calls[key] = ledger.calls.get(key, 0) + 1
        if ledger.calls[key] >= NO_PROGRESS_REPEATS:
            return self._refuse(ledger, tool, "NO_PROGRESS",
                                f"the same call was requested {NO_PROGRESS_REPEATS} times without progress; stop")
        return None

    # ------------------------------------------------------------------ one bounded MCP tool call
    async def _call_mcp(self, ledger: _Ledger, conf: tuple, name: str, read_only: bool, args: dict) -> str:
        base, workspace, token = conf
        key = name + ":" + hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]
        refusal = self._gate(ledger, name, key)
        if refusal:
            return refusal
        attempts = 2 if read_only else 1  # one retry for a transient read; no blind write retries
        last_err = None
        for attempt in range(attempts):
            if ledger.actions >= ledger.max_actions or ledger.remaining() <= 0:
                break
            ledger.actions += 1
            timeout = max(0.5, min(float(self.tool_timeout_s or 30), ledger.remaining()))

            async def do(session):
                return await session.call_tool(name, args)
            try:
                res = await self._session_do(base + "/mcp", self._headers(token, workspace, ledger.run["run_id"]),
                                             timeout, do)
            except TimeoutError:
                ledger.stop("TOOL_TIMEOUT", f"{name} did not answer within {timeout:.0f} s")
                ledger.trace.append({"tool": name, "outcome": "timeout"})
                return self._out({"error": {"code": "TOOL_TIMEOUT", "source": "harness", "message":
                                            f"{name} did not answer within {timeout:.0f} s. The outcome is unknown; "
                                            "this invocation is stopped. Read state before any new attempt."}}, ledger)
            except Exception as exc:  # noqa: BLE001 - transport failure becomes a structured result
                last_err = f"{type(exc).__name__}"
                ledger.trace.append({"tool": name, "outcome": "transport_error", "attempt": attempt + 1})
                continue
            body = res.structuredContent
            if not isinstance(body, dict):
                texts = [c.text for c in (res.content or []) if getattr(c, "type", "") == "text"]
                try:
                    body = json.loads(texts[0]) if texts else {}
                except ValueError:
                    body = {"text": texts[0][:2000]}
            if res.isError:
                code = (body.get("error") or {}).get("code", "TOOL_ERROR")
                if code in TERMINAL_LAB_CODES:
                    ledger.stop(code, (body.get("error") or {}).get("message", ""))
                ledger.trace.append({"tool": name, "outcome": "error", "code": code})
                return self._out(body, ledger)
            ledger.trace.append({"tool": name, "outcome": "ok"})
            return self._out(body, ledger)
        if last_err is None:
            return self._refuse(ledger, name, "BUDGET_EXHAUSTED", "no action budget or time left for this call")
        return self._out({"error": {"code": "LAB_UNREACHABLE", "source": "harness",
                                    "message": f"{name}: the TaskSprint lab could not be reached ({last_err}). "
                                               "Nothing is known to have changed; escalate."}}, ledger)

    # ------------------------------------------------------------------ one bounded delegation
    async def _delegate(self, ledger: _Ledger, conf: tuple, slot: str, tool_name: str, inner, request: str) -> str:
        base, workspace, token = conf
        key = tool_name + ":" + hashlib.sha256(request.encode()).hexdigest()[:16]
        refusal = self._gate(ledger, tool_name, key)
        if refusal:
            return refusal
        depth = int(ledger.run.get("depth") or 0)
        if depth + 1 > max(0, min(2, int(self.max_depth))):
            return self._refuse(ledger, tool_name, "DELEGATION_DEPTH_EXCEEDED",
                                f"delegation depth would exceed {self.max_depth}", terminal=False)
        limit = 1 + max(0, min(1, int(self.max_repairs)))
        used = ledger.delegations.get(tool_name, 0)
        if tool_name in ("ask_developer", "ask_qa") and used >= limit:
            return self._refuse(ledger, tool_name, "REPAIR_BUDGET_EXHAUSTED",
                                f"{tool_name} was already used {used} times in this turn (one implementation plus "
                                f"{limit - 1} repair cycle); escalate to the human with the evidence IDs")
        if tool_name == "ask_product_owner" and used >= 2:
            return self._refuse(ledger, tool_name, "DELEGATION_LIMIT", "ask_product_owner already used twice this "
                                "turn; escalate the open scope question to the human", terminal=False)
        # Charge the delegation as one action of the parent run (and its tree) at the lab before starting it.
        ledger.actions += 1
        try:
            async with httpx.AsyncClient(timeout=min(15.0, max(0.5, ledger.remaining())),
                                         follow_redirects=False) as client:
                r = await client.get(base + "/v1/state", headers=self._headers(token, workspace, ledger.run["run_id"]))
        except httpx.HTTPError as exc:
            return self._out({"error": {"code": "LAB_UNREACHABLE", "source": "harness",
                                        "message": f"could not charge the delegation ({type(exc).__name__}); "
                                                   "not delegated"}}, ledger)
        if r.status_code != 200:
            try:
                err = r.json().get("error") or {}
            except ValueError:
                err = {}
            code = err.get("code", f"HTTP_{r.status_code}")
            if code in TERMINAL_LAB_CODES:
                ledger.stop(code, err.get("message", ""))
            ledger.trace.append({"tool": tool_name, "outcome": "refused_by_lab", "code": code})
            return self._out({"error": {"code": code, "message": err.get("message", ""), "source": "lab",
                                        "request_id": err.get("request_id")}}, ledger)
        ledger.delegations[tool_name] = used + 1
        timeout = max(1.0, min(float(self.delegation_timeout_s or 90), ledger.remaining()))
        field = self._inner_field(inner)
        started = time.time()
        try:
            with anyio.fail_after(timeout):
                out = await inner.ainvoke({"flow_tweak_data": {field: request}})
        except TimeoutError:
            ledger.stop("DELEGATION_TIMEOUT", f"{tool_name} did not finish within {timeout:.0f} s")
            ledger.trace.append({"tool": tool_name, "outcome": "timeout"})
            return self._out({"error": {"code": "DELEGATION_TIMEOUT", "source": "harness", "message":
                                        f"{tool_name} was cancelled after {timeout:.0f} s. Its lab run expires at its "
                                        "own deadline; read state before deciding. This turn is stopped."}}, ledger)
        except Exception as exc:  # noqa: BLE001
            ledger.trace.append({"tool": tool_name, "outcome": "error"})
            return self._out({"error": {"code": "DELEGATION_FAILED", "source": "harness",
                                        "message": f"{tool_name} failed ({type(exc).__name__}: {str(exc)[:300]})"}},
                             ledger)
        text = out if isinstance(out, str) else json.dumps(out, default=str)
        ledger.trace.append({"tool": tool_name, "outcome": "ok", "elapsed_s": round(time.time() - started, 1)})
        return self._out({"delegation": {"tool": tool_name, "flow": dict((d[1], d[2]) for d in DELEGATIONS)[tool_name],
                                         "parent_run_id": ledger.run["run_id"], "elapsed_s": round(time.time() - started, 1)},
                          "specialist_response": text[:6000]}, ledger)

    # ------------------------------------------------------------------ the one A2A delegation
    async def _assess(self, ledger: _Ledger, conf: tuple, inner, args: dict) -> str:
        base, workspace, token = conf
        tool_name = A2A_PEER[1]
        key = tool_name + ":" + hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]
        refusal = self._gate(ledger, tool_name, key)
        if refusal:
            return refusal
        depth = int(ledger.run.get("depth") or 0)
        if depth + 1 > max(0, min(2, int(self.max_depth))):
            return self._refuse(ledger, tool_name, "DELEGATION_DEPTH_EXCEEDED",
                                f"delegation depth would exceed {self.max_depth}", terminal=False)
        if ledger.delegations.get(tool_name, 0) >= 1:
            return self._refuse(ledger, tool_name, "DELEGATION_LIMIT", "assess_production_release was already used this turn; "
                                "report its result or escalate to the human", terminal=False)
        ledger.actions += 1
        try:
            async with httpx.AsyncClient(timeout=min(15.0, max(0.5, ledger.remaining())),
                                         follow_redirects=False) as client:
                r = await client.get(base + "/v1/state", headers=self._headers(token, workspace, ledger.run["run_id"]))
        except httpx.HTTPError as exc:
            return self._out({"error": {"code": "LAB_UNREACHABLE", "source": "harness",
                                        "message": f"could not charge the delegation ({type(exc).__name__}); "
                                                   "not delegated"}}, ledger)
        if r.status_code != 200:
            try:
                err = r.json().get("error") or {}
            except ValueError:
                err = {}
            code = err.get("code", f"HTTP_{r.status_code}")
            if code in TERMINAL_LAB_CODES:
                ledger.stop(code, err.get("message", ""))
            ledger.trace.append({"tool": tool_name, "outcome": "refused_by_lab", "code": code})
            return self._out({"error": {"code": code, "message": err.get("message", ""), "source": "lab",
                                        "request_id": err.get("request_id")}}, ledger)
        ledger.delegations[tool_name] = 1
        timeout = max(5.0, min(float(self.a2a_timeout_s or 90), ledger.remaining()))
        from datetime import datetime, timedelta, timezone
        deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout)
        payload = {"schema_version": A2A_PAYLOAD_SCHEMA_VERSION, "intent": "assess_release", "workspace_id": workspace,
                   "candidate_id": args["candidate_id"], "candidate_sha256": args["candidate_sha256"],
                   "app_test_run_id": args["app_test_run_id"], "agent_manifest_id": None,
                   "deadline_utc": deadline.isoformat(timespec="seconds").replace("+00:00", "Z"),
                   "allow_execute": False}
        started = time.time()
        try:
            with anyio.fail_after(timeout + 10):
                out = await inner.ainvoke({"payload_json": json.dumps(payload, sort_keys=True),
                                           "parent_run_id": ledger.run["run_id"]})
        except TimeoutError:
            ledger.stop("DELEGATION_TIMEOUT", f"{tool_name} did not finish within {timeout:.0f} s")
            ledger.trace.append({"tool": tool_name, "outcome": "timeout"})
            return self._out({"error": {"code": "DELEGATION_TIMEOUT", "source": "harness", "message":
                                        f"{tool_name} was cancelled after {timeout:.0f} s. Nothing was released; "
                                        "escalate to the human."}}, ledger)
        except Exception as exc:  # noqa: BLE001
            ledger.trace.append({"tool": tool_name, "outcome": "error"})
            return self._out({"error": {"code": "DELEGATION_FAILED", "source": "harness",
                                        "message": f"{tool_name} failed ({type(exc).__name__}: {str(exc)[:300]})"}},
                             ledger)
        text = out if isinstance(out, str) else json.dumps(out, default=str)
        try:
            result = json.loads(text)
        except ValueError:
            result = {"raw": text[:2000]}
        ledger.trace.append({"tool": tool_name, "outcome": (result or {}).get("outcome", "unknown"),
                             "elapsed_s": round(time.time() - started, 1)})
        return self._out({"delegation": {"tool": tool_name, "peer": A2A_PEER[2], "transport": "A2A",
                                         "parent_run_id": ledger.run["run_id"], "payload": payload,
                                         "elapsed_s": round(time.time() - started, 1)},
                          "peer_result": result}, ledger)

    def _peer_tools(self, ledger: _Ledger, conf: tuple) -> list:
        slot, tool_name, peer, inner_name, purpose = A2A_PEER
        value = getattr(self, slot, None)
        inner_list = value if isinstance(value, list) else ([value] if value else [])
        if self.expected_role != "coordinator":
            if inner_list:
                raise ValueError("only the coordinator toolset may carry the A2A peer")
            return []
        if not inner_list:
            return []  # Phase 07 flows without the peer keep working
        if len(inner_list) != 1:
            raise ValueError(f"connect exactly one TaskSprint A2A Audit adapter ({peer}) to '{slot}'")
        inner = inner_list[0]
        meta = getattr(inner, "metadata", None) or {}
        if getattr(inner, "name", "") != inner_name or not str(meta.get("source", "")).startswith("a2a_audit/"):
            raise ValueError(f"'{slot}' accepts only the TaskSprint A2A Audit adapter tool for {peer}")

        async def run(candidate_id: str, candidate_sha256: str, app_test_run_id: str) -> str:
            return await self._assess(ledger, conf, inner, {"candidate_id": candidate_id,
                                                            "candidate_sha256": candidate_sha256,
                                                            "app_test_run_id": app_test_run_id})
        return [StructuredTool(name=tool_name, description=purpose, args_schema=AssessArgs, coroutine=run,
                               func=self._sync(run), tags=[tool_name],
                               metadata={"source": ADAPTER_VERSION, "peer": peer,
                                         "peer_flow_id": meta.get("peer_flow_id")})]

    @staticmethod
    def _inner_field(inner) -> str:
        schema = inner.args_schema
        outer = getattr(schema, "model_fields", {}).get("flow_tweak_data")
        fields = getattr(outer.annotation, "model_fields", {}) if outer is not None else {}
        names = [n for n in fields if n.endswith("~input_value")]
        if len(names) != 1:
            raise ValueError("the Run Flow tool does not expose exactly one Chat Input text field")
        return names[0]

    # ------------------------------------------------------------------ tool construction
    @staticmethod
    def _sync(coro_fn):
        def run_sync(**kwargs):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(lambda: asyncio.run(coro_fn(**kwargs))).result()
        return run_sync

    def _delegation_tools(self, ledger: _Ledger, conf: tuple) -> list:
        tools = []
        wired = {slot: getattr(self, slot, None) for slot, *_ in DELEGATIONS}
        if self.expected_role != "coordinator":
            if any(wired.values()):
                raise ValueError("only the coordinator toolset may carry delegation tools")
            return tools
        for slot, tool_name, flow_name, purpose in DELEGATIONS:
            value = wired[slot]
            inner_list = value if isinstance(value, list) else ([value] if value else [])
            if len(inner_list) != 1:
                raise ValueError(f"connect exactly one Run Flow ({flow_name}) to '{slot}'")
            inner = inner_list[0]
            expected = _norm(flow_name + "_tool")
            if _norm(getattr(inner, "name", "")) != expected or flow_name not in (getattr(inner, "description", "") or ""):
                raise ValueError(f"'{slot}' accepts only the Run Flow tool for {flow_name}")

            run = self._delegation_fn(ledger, conf, slot, tool_name, inner)
            tools.append(StructuredTool(name=tool_name, description=purpose, args_schema=DelegationArgs,
                                        coroutine=run, func=self._sync(run), tags=[tool_name],
                                        metadata={"source": ADAPTER_VERSION, "flow": flow_name}))
        return tools

    def _delegation_fn(self, ledger: _Ledger, conf: tuple, slot: str, tool_name: str, inner):
        async def run(request: str) -> str:
            return await self._delegate(ledger, conf, slot, tool_name, inner, request)
        return run

    def _mcp_fn(self, ledger: _Ledger, conf: tuple, name: str, read_only: bool):
        async def run(**kwargs) -> str:
            args = {k: (v.model_dump(exclude_none=True) if isinstance(v, BaseModel) else v)
                    for k, v in kwargs.items() if v is not None}
            return await self._call_mcp(ledger, conf, name, read_only, args)
        return run

    async def _get_tools(self) -> list:
        base, workspace, token, run = self._config()
        max_actions = max(1, min(ROLE_MAX_ACTIONS.get(self.expected_role, DEFAULT_MAX_ACTIONS), int(self.max_actions)))
        limit_s = max(5.0, min(180.0, float(self.invocation_timeout_s or 90)))
        deadline_at = run.get("deadline_at")
        if isinstance(deadline_at, str):
            from datetime import datetime
            try:
                run["deadline_epoch"] = datetime.fromisoformat(deadline_at.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        ledger = _Ledger(run, max_actions, limit_s)
        self._ts_ledger = ledger
        conf = (base, workspace, token)
        listed = await self._list_tools(base, workspace, token, run["run_id"])
        allowed = ALLOWLIST[self.expected_role]
        tools = []
        for t in listed:
            if t.name not in allowed:
                continue
            schema = create_input_schema_from_json_schema(t.inputSchema or {"type": "object", "properties": {}})
            read_only = bool(getattr(t.annotations, "readOnlyHint", False)) if t.annotations else False

            run_tool = self._mcp_fn(ledger, conf, t.name, read_only)
            tools.append(StructuredTool(name=t.name, description=(t.description or "")[:1000], args_schema=schema,
                                        coroutine=run_tool, func=self._sync(run_tool), tags=[t.name],
                                        metadata={"source": ADAPTER_VERSION, "read_only": read_only}))
        tools += self._delegation_tools(ledger, conf)
        tools += self._peer_tools(ledger, conf)
        self.status = {"adapter": ADAPTER_VERSION, "role": self.expected_role, "run_id": run["run_id"],
                       "tools": [t.name for t in tools], "max_actions": max_actions,
                       "deadline_s": round(ledger.remaining(), 1)}
        return tools
