# TaskSprint Run Context: trusted Langflow custom component (Architecture A8 POST /v1/runs, A9).
# Creates one server-issued run per flow invocation for this role, passes the chat message
# through unchanged, and exposes the run ID as a separate output. The role comes from the
# bound Credential global, the workspace from flow configuration, the budget from the server.
# Version 1.0.0. Source of truth: tasksprint-lab/components/run_context.py
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from lfx.custom.custom_component.component import Component
from lfx.io import MessageInput, MessageTextInput, Output, SecretStrInput
from lfx.schema.message import Message

ADAPTER_VERSION = "run_context/1.0.0"
RUNS_PATH = "/v1/runs"
WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
CONV_SAFE = re.compile(r"[^A-Za-z0-9_.:-]")


class TaskSprintRunContext(Component):
    display_name = "TaskSprint Run Context"
    description = ("Trusted runtime adapter: issues a bounded server-side run (POST /v1/runs) for this role "
                   "and Playground session, then passes the message through unchanged.")
    icon = "fingerprint"
    name = "TaskSprintRunContext"

    inputs = [
        MessageInput(name="input_value", display_name="Message", required=True),
        MessageTextInput(name="api_base", display_name="TaskSprint API base", value="TASKSPRINT_API_BASE",
                         load_from_db=True, advanced=True,
                         info="Bind the Generic global TASKSPRINT_API_BASE (https origin, no path)."),
        SecretStrInput(name="role_token", display_name="Role token", value="", load_from_db=True,
                       info="Bind this agent's Credential global (TS_PO_TOKEN, TS_DEV_TOKEN or TS_QA_TOKEN)."),
        MessageTextInput(name="workspace", display_name="Workspace", value="demo-001", advanced=True),
    ]
    outputs = [
        Output(display_name="Message", name="message", method="pass_message"),
        Output(display_name="Run ID", name="run_id", method="run_id_message"),
    ]

    def _run(self) -> dict:
        cached = getattr(self, "_ts_run", None)
        if cached is not None:
            return cached
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
        session = str(getattr(self.graph, "session_id", "") or getattr(self.graph, "flow_id", "") or "default")
        conversation = ("lf-" + CONV_SAFE.sub("-", session))[:64]
        resp = httpx.post(base + RUNS_PATH, json={"conversation_id": conversation}, timeout=20.0,
                          headers={"Authorization": f"Bearer {token}", "X-TaskSprint-Workspace": workspace,
                                   "User-Agent": ADAPTER_VERSION}, follow_redirects=False)
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code != 201 or "run_id" not in body:
            code = (body.get("error") or {}).get("code", f"HTTP_{resp.status_code}")
            raise ValueError(f"TaskSprint run context refused: {code}")
        self._ts_run = {k: body.get(k) for k in ("run_id", "role", "session_namespace", "max_actions",
                                                  "deadline_at", "depth")}
        self.status = self._ts_run
        return self._ts_run

    def pass_message(self) -> Message:
        self._run()
        return self.input_value if isinstance(self.input_value, Message) else Message(text=str(self.input_value or ""))

    def run_id_message(self) -> Message:
        return Message(text=self._run()["run_id"])
