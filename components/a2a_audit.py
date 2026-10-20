# TaskSprint A2A Audit: trusted Langflow custom component (Architecture A9, A10; Phase 08).
# A thin audited adapter around a GENUINE A2A client (the a2a SDK that ships with Langflow 1.12, the same
# client the native "A2A Agent" component uses). It exists because the native node returns only the reply
# text and hides the protocol Task / context / message / artifact IDs that A10 requires us to capture.
#
# It calls exactly one fixed peer: the TS-20 Production Manager's published Agent Card (Langflow
# /api/v1/a2a/<flow id>/.well-known/agent-card.json). The card's advertised protocolVersion and JSON-RPC url
# are used as served; an off-origin or different-flow RPC url is refused. Authentication: the Langflow API
# key from the Credential global TS_A2A_API_KEY, sent only as x-api-key to the card's own origin (never to
# the model, never recorded). One message/send (non-streaming) carries the typed assess_release payload as an
# application/json data part with contextId = the delegating coordinator run (lineage); then tasks/get reads
# the task back from the peer's durable task store. The raw JSON-RPC bodies (no headers) and the result are
# recorded in the TaskSprint lab (POST /v1/a2a-exchanges, coordinator credential), which derives the IDs,
# links Operations' own runs and tool trace and verifies every quoted evidence ID.
#
# This component is NOT given to the Agent directly: its Toolset output is wired only into the TaskSprint
# Bounded Toolset slot "A2A peer: TS-20 Production Manager", which exposes it to the coordinator as the
# budgeted delegation `assess_release` with typed arguments. There is no task stub or simulated server:
# on any failure it returns a structured error and no artifact.
# Version 1.0.0. Source of truth: tasksprint-lab/components/a2a_audit.py
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import anyio
import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from lfx.custom.custom_component.component import Component
from lfx.io import FloatInput, MessageTextInput, Output, SecretStrInput

ADAPTER_VERSION = "a2a_audit/1.0.0"
PEER_TOOL_NAME = "ts20_production_manager_a2a"
PEER_NAME = "TS-20 Production Manager"
UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
CARD_RE = re.compile(rf"^https://([A-Za-z0-9.\-]+)/api/v1/a2a/({UUID_RE})/\.well-known/agent-card\.json$")
RUN_RE = re.compile(r"^run_[0-9a-f]{32}$")
WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
MAX_CARD_BYTES = 256 * 1024
MAX_BODY_CHARS = 12000
COMPLETED = "TASK_STATE_COMPLETED"


class PeerArgs(BaseModel):
    payload_json: str = Field(..., max_length=4000, description="Serialized assess_release payload (trusted toolset).")
    parent_run_id: str = Field(..., pattern=r"^run_[0-9a-f]{32}$", description="Delegating coordinator run.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clip_json(data: Any) -> Any:
    text = json.dumps(data, default=str)
    return data if len(text) <= MAX_BODY_CHARS else {"_truncated_json": text[:MAX_BODY_CHARS]}


class TaskSprintA2AAudit(Component):
    display_name = "TaskSprint A2A Audit"
    description = ("Trusted adapter: calls the fixed TS-20 Production Manager A2A agent with the a2a SDK "
                   "(message/send + tasks/get) and records the redacted exchange and lineage in the TaskSprint lab. "
                   "Wire its Toolset only into the Bounded Toolset's A2A peer slot.")
    icon = "bot"
    name = "TaskSprintA2AAudit"

    inputs = [
        MessageTextInput(name="card_url", display_name="Agent card URL (fixed peer)", value="",
                         info="The TS-20 Production Manager card URL exactly as its A2A pane shows it."),
        MessageTextInput(name="peer_flow_id", display_name="Peer flow ID", value="",
                         info="The TS-20 flow id; the card URL and its RPC url must name this flow."),
        SecretStrInput(name="api_key", display_name="A2A API key", value="", load_from_db=True,
                       info="Bind the Credential global TS_A2A_API_KEY (a Langflow API key). Never model-visible."),
        SecretStrInput(name="audit_token", display_name="Coordinator token (audit)", value="", load_from_db=True,
                       info="Bind TS_COORD_TOKEN: records the exchange in the lab (POST /v1/a2a-exchanges)."),
        MessageTextInput(name="api_base", display_name="TaskSprint API base", value="TASKSPRINT_API_BASE",
                         load_from_db=True, advanced=True),
        MessageTextInput(name="workspace", display_name="Workspace", value="demo-001", advanced=True),
        FloatInput(name="timeout_s", display_name="Peer timeout (s)", value=90.0, advanced=True),
    ]
    outputs = [Output(display_name="Toolset", name="component_as_tool", method="to_toolkit", types=["Tool"],
                      cache=False)]

    # ------------------------------------------------------------------ configuration
    def _config(self) -> dict:
        m = CARD_RE.match((self.card_url or "").strip())
        peer = (self.peer_flow_id or "").strip()
        if not m or m.group(2) != peer:
            raise ValueError("card URL must be https://<host>/api/v1/a2a/<peer flow id>/.well-known/agent-card.json "
                             "for the configured peer flow id")
        base = (self.api_base or "").strip().rstrip("/")
        u = urlparse(base)
        if u.scheme != "https" or not u.hostname or u.path or u.query or u.fragment or u.username:
            raise ValueError("TASKSPRINT_API_BASE must be an https origin without a path")
        if not WORKSPACE_RE.match((self.workspace or "").strip()):
            raise ValueError("workspace id is invalid")
        if len(self.api_key or "") < 16:
            raise ValueError("A2A API key is not bound (Credential global TS_A2A_API_KEY missing)")
        if len(self.audit_token or "") < 32:
            raise ValueError("coordinator token is not bound (TS_COORD_TOKEN)")
        return {"card_url": self.card_url.strip(), "host": m.group(1), "peer": peer, "origin": f"https://{m.group(1)}",
                "lab": base, "workspace": self.workspace.strip(),
                "timeout": max(5.0, min(170.0, float(self.timeout_s or 90)))}

    # ------------------------------------------------------------------ one audited exchange
    async def _exchange(self, conf: dict, payload: dict, parent_run_id: str) -> dict:
        from a2a.client.card_resolver import parse_agent_card
        from a2a.client.client import ClientConfig
        from a2a.client.client_factory import create_client
        from a2a.helpers.proto_helpers import new_data_part
        from a2a.types import a2a_pb2 as pb

        http_log: list[dict] = []
        wire: dict[str, Any] = {}
        started = _now()
        record: dict[str, Any] = {"outcome": "not_sent", "task": None, "task_get": None, "error": None,
                                  "protocol_version": None, "transport": None}

        async def on_request(request: httpx.Request) -> None:
            if (request.url.scheme, request.url.host) != ("https", conf["host"]):
                raise httpx.UnsupportedProtocol("refusing a request outside the fixed peer origin")
            request.extensions["ts_started"] = time.monotonic()

        async def on_response(response: httpx.Response) -> None:
            await response.aread()
            req = response.request
            entry: dict[str, Any] = {"http_method": req.method, "path": req.url.path, "status": response.status_code,
                                     "elapsed_ms": int((time.monotonic() - req.extensions.get("ts_started",
                                                                                              time.monotonic())) * 1000)}
            if req.method == "POST":
                try:
                    body = json.loads(req.content or b"{}")
                    entry["rpc_method"] = body.get("method")
                    entry["request"] = _clip_json(body)
                except ValueError:
                    entry["request"] = None
                try:
                    rbody = response.json()
                    if isinstance(rbody, dict) and "result" in rbody:  # stored in full as task / task_get
                        entry["response"] = {"jsonrpc": rbody.get("jsonrpc"), "id": rbody.get("id"),
                                             "result": "(recorded as task / task_get)"}
                    else:
                        entry["response"] = _clip_json(rbody)
                    if entry.get("rpc_method") and isinstance(rbody, dict):
                        wire[entry["rpc_method"]] = rbody
                except ValueError:
                    entry["response"] = response.text[:500]
            elif req.url.path.endswith("/agent-card.json") and response.status_code == 200:
                try:
                    card = response.json()
                    entry["card"] = {k: card.get(k) for k in ("name", "protocolVersion", "url", "preferredTransport",
                                                              "version", "security")}
                except ValueError:
                    entry["card"] = None
            http_log.append(entry)

        client_http = httpx.AsyncClient(timeout=httpx.Timeout(conf["timeout"]), follow_redirects=False,
                                        headers={"x-api-key": self.api_key},
                                        event_hooks={"request": [on_request], "response": [on_response]})
        try:
            async with client_http:
                resp = await client_http.get(conf["card_url"])
                if resp.status_code != 200 or len(resp.content) > MAX_CARD_BYTES:
                    record.update(outcome="unreachable", error={
                        "code": "PEER_UNAVAILABLE", "message": f"agent card answered HTTP {resp.status_code}; the peer "
                        "is not published or not reachable. No task was sent."})
                    return {**record, "http": http_log, "started_at": started, "finished_at": _now()}
                card_json = resp.json()
                record["protocol_version"] = card_json.get("protocolVersion")
                record["transport"] = card_json.get("preferredTransport") or "JSONRPC"
                rpc = urlparse(str(card_json.get("url", "")))
                if (rpc.scheme, rpc.hostname, rpc.path) != ("https", conf["host"],
                                                            f"/api/v1/a2a/{conf['peer']}/jsonrpc"):
                    record.update(outcome="protocol_error", error={
                        "code": "PEER_CARD_MISMATCH", "message": "the card advertises an RPC url other than the fixed "
                        "peer's own JSON-RPC endpoint; refused"})
                    return {**record, "http": http_log, "started_at": started, "finished_at": _now()}
                card = parse_agent_card(card_json)
                client = await create_client(card, client_config=ClientConfig(
                    streaming=False, httpx_client=client_http, accepted_output_modes=["application/json"]))
                message = pb.Message(message_id=uuid.uuid4().hex, context_id=parent_run_id, role=pb.Role.ROLE_USER,
                                     parts=[new_data_part(payload, media_type="application/json")])
                final = None
                with anyio.fail_after(conf["timeout"]):
                    async for item in client.send_message(pb.SendMessageRequest(message=message)):
                        if item.HasField("task"):
                            final = item.task
                record["outcome"] = "protocol_error"
                if final is None:
                    record["error"] = {"code": "PEER_NO_TASK", "message": "the peer returned no Task"}
                else:
                    with anyio.fail_after(30):
                        await client.get_task(pb.GetTaskRequest(id=final.id))
                    state = pb.TaskState.Name(final.status.state)
                    if state == COMPLETED:
                        record["outcome"] = "completed"
                    else:
                        record.update(outcome="failed", error={"code": "PEER_TASK_NOT_COMPLETED",
                                                               "message": f"peer task ended {state}"})
        except TimeoutError:
            record.update(outcome="timeout", error={"code": "PEER_TIMEOUT", "message": f"no answer within "
                          f"{conf['timeout']:.0f} s; the peer task may still finish. Nothing was released."})
        except Exception as exc:  # noqa: BLE001 - becomes a structured, recorded failure
            statuses = [h["status"] for h in http_log]
            if 401 in statuses or 403 in statuses:
                record.update(outcome="unauthorized", error={"code": "PEER_UNAUTHORIZED",
                                                             "message": "the peer rejected the A2A credential"})
            elif 404 in statuses:
                record.update(outcome="unreachable", error={"code": "PEER_UNAVAILABLE",
                                                            "message": "the peer endpoint answered 404"})
            else:
                record.update(outcome="protocol_error" if record["outcome"] != "not_sent" else "unreachable",
                              error={"code": "PEER_ERROR", "message": f"{type(exc).__name__}: {str(exc)[:200]}"})
        sent = (wire.get("message/send") or {}).get("result")
        got = (wire.get("tasks/get") or {}).get("result")
        record["task"] = sent if isinstance(sent, dict) else None
        record["task_get"] = got if isinstance(got, dict) else None
        if record["outcome"] == "completed" and record["task"] is None:
            record.update(outcome="protocol_error", error={"code": "PEER_WIRE_UNREADABLE",
                                                           "message": "could not read the raw message/send result"})
        return {**record, "http": http_log, "started_at": started, "finished_at": _now()}

    async def _record(self, conf: dict, payload: dict, parent_run_id: str, ex: dict) -> dict:
        body = {"parent_run_id": parent_run_id, "peer_flow_id": conf["peer"], "card_url": conf["card_url"],
                "protocol_version": ex["protocol_version"], "transport": ex["transport"],
                "adapter_version": ADAPTER_VERSION, "request": payload, "outcome": ex["outcome"],
                "task": ex["task"], "task_get": ex["task_get"], "http": ex["http"][:12], "error": ex["error"],
                "started_at": ex["started_at"], "finished_at": ex["finished_at"]}
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as lab:
                r = await lab.post(conf["lab"] + "/v1/a2a-exchanges", json=body, headers={
                    "Authorization": f"Bearer {self.audit_token}", "X-TaskSprint-Workspace": conf["workspace"],
                    "User-Agent": ADAPTER_VERSION})
            data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"recorded": False, "error": {"code": "AUDIT_UNREACHABLE", "message": type(exc).__name__}}
        if r.status_code != 201:
            return {"recorded": False, "error": (data.get("error") or {"code": f"HTTP_{r.status_code}"})}
        return {"recorded": True, **data}

    async def _call(self, payload_json: str, parent_run_id: str) -> str:
        conf = self._config()
        if not RUN_RE.match(parent_run_id or ""):
            return json.dumps({"error": {"code": "BAD_PARENT_RUN", "source": "adapter"}})
        try:
            payload = json.loads(payload_json)
        except ValueError:
            return json.dumps({"error": {"code": "BAD_PAYLOAD", "source": "adapter"}})
        if not isinstance(payload, dict) or payload.get("intent") != "assess_release" or \
                payload.get("allow_execute") is not False:
            return json.dumps({"error": {"code": "BAD_PAYLOAD", "source": "adapter",
                                         "message": "only an assess_release payload with allow_execute=false"}})
        ex = await self._exchange(conf, payload, parent_run_id)
        audit = await self._record(conf, payload, parent_run_id, ex)
        texts = []
        if ex["outcome"] == "completed":
            for a in (ex["task"] or {}).get("artifacts") or []:
                for p in a.get("parts") or []:
                    if isinstance(p, dict) and isinstance(p.get("text"), str):
                        texts.append(p["text"])
        out: dict[str, Any] = {
            "peer": PEER_NAME, "outcome": ex["outcome"], "protocol_version": ex["protocol_version"],
            "protocol": audit.get("protocol") if audit.get("recorded") else {
                "task_id": (ex["task"] or {}).get("id"), "context_id": (ex["task"] or {}).get("contextId")},
            "error": ex["error"],
            "operations_artifact": "\n".join(texts)[:5000] if texts else None,
            "audit": {"recorded": audit.get("recorded"), "exchange_id": audit.get("exchange_id"),
                      "event_id": audit.get("event_id"), "error": audit.get("error"),
                      "linked_evidence": audit.get("linked_evidence"),
                      "operations_runs": [{"run_id": p["run_id"], "tools": [t.get("tool") or t["action"]
                                                                            for t in p["tool_trace"]]}
                                          for p in audit.get("peer_runs") or []]},
            "note": ("The artifact is Operations' assessment. It is not an approval and nothing was deployed. "
                     "Evidence IDs marked exists=false in linked_evidence are not backed by lab records."),
        }
        if ex["outcome"] == "completed" and not audit.get("recorded"):
            out["error"] = {"code": "AUDIT_NOT_RECORDED", "message": "the exchange could not be recorded; treat the "
                            "assessment as unverified and escalate"}
        return json.dumps(out, sort_keys=True, default=str)

    @staticmethod
    def _sync(coro_fn):
        def run_sync(**kwargs):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(lambda: asyncio.run(coro_fn(**kwargs))).result()
        return run_sync

    async def _get_tools(self) -> list:
        conf = self._config()

        async def run(payload_json: str, parent_run_id: str) -> str:
            return await self._call(payload_json, parent_run_id)

        self.status = {"adapter": ADAPTER_VERSION, "peer": PEER_NAME, "peer_flow_id": conf["peer"],
                       "card_url": conf["card_url"]}
        return [StructuredTool(name=PEER_TOOL_NAME, description=f"Internal A2A peer call to {PEER_NAME} (wire into "
                               "the TaskSprint Bounded Toolset only).", args_schema=PeerArgs, coroutine=run,
                               func=self._sync(run), tags=[PEER_TOOL_NAME],
                               metadata={"source": ADAPTER_VERSION, "peer_flow_id": conf["peer"]})]
