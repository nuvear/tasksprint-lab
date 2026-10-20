# TaskSprint App Console: trusted Langflow custom component (Build Guide 06.2/06.3, Architecture A3/A8).
# Reviewed adapter: one fixed endpoint, deterministic verb check, no model, no code execution.
# Version 1.0.0. Source of truth: tasksprint-lab/components/app_console.py
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from lfx.custom.custom_component.component import Component
from lfx.io import MessageInput, MessageTextInput, Output, SecretStrInput
from lfx.schema.message import Message

ADAPTER_VERSION = "app_console/1.0.0"
COMMAND_PATH = "/v1/app/commands"  # fixed; the base URL comes from the TASKSPRINT_API_BASE global
VERBS = ("add", "list", "complete", "status")
HELP = "Commands: add <title> | list | complete <ID> | status"
WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
MAX_COMMAND_CHARS = 200


class TaskSprintAppConsole(Component):
    display_name = "TaskSprint App Console"
    description = ("Deterministic To-do App console: sends one add/list/complete/status command to the "
                   "TaskSprint lab with the application credential. No model, no code execution.")
    icon = "square-terminal"
    name = "TaskSprintAppConsole"

    inputs = [
        MessageInput(name="command", display_name="Command", info="One command per message.", required=True),
        MessageTextInput(name="api_base", display_name="TaskSprint API base",
                         info="Bind the Generic global TASKSPRINT_API_BASE (https origin, no path).",
                         value="TASKSPRINT_API_BASE", load_from_db=True, advanced=True),
        SecretStrInput(name="app_token", display_name="Application token",
                       info="Bind the Credential global TS_APP_TOKEN. Never type a token here.",
                       value="TS_APP_TOKEN", load_from_db=True, advanced=True),
        MessageTextInput(name="workspace", display_name="Workspace", value="demo-001", advanced=True),
    ]
    outputs = [Output(display_name="Result", name="result", method="run_command")]

    def _base(self) -> str:
        raw = (self.api_base or "").strip().rstrip("/")
        u = urlparse(raw)
        if u.scheme != "https" or not u.hostname or u.path or u.query or u.fragment or u.username:
            raise ValueError("TASKSPRINT_API_BASE must be an https origin without a path")
        return raw

    def run_command(self) -> Message:
        text = self.command.text if isinstance(self.command, Message) else str(self.command or "")
        text = (text or "").strip()
        verb = text.split(" ", 1)[0].lower() if text else ""
        if verb not in VERBS or len(text) > MAX_COMMAND_CHARS or "\n" in text:
            self.status = "rejected locally: UNKNOWN_COMMAND"
            return Message(text=f"UNKNOWN_COMMAND: {HELP}")
        workspace = (self.workspace or "").strip()
        if not WORKSPACE_RE.match(workspace):
            raise ValueError("workspace id is invalid")
        token = self.app_token or ""
        if len(token) < 32:
            raise ValueError("TS_APP_TOKEN is not bound (Credential global variable missing)")
        try:
            resp = httpx.post(self._base() + COMMAND_PATH, json={"command": text}, timeout=30.0,
                              headers={"Authorization": f"Bearer {token}", "X-TaskSprint-Workspace": workspace,
                                       "User-Agent": ADAPTER_VERSION}, follow_redirects=False)
        except httpx.HTTPError as exc:
            self.status = f"LAB_UNREACHABLE ({type(exc).__name__})"
            return Message(text="LAB_UNREACHABLE: the TaskSprint lab did not answer; nothing is known to have changed. "
                                "Check status before retrying.")
        try:
            body = resp.json()
        except ValueError:
            body = {}
        rid = resp.headers.get("x-request-id", "")
        if resp.status_code >= 400 or "error" in body:
            err = body.get("error") or {}
            code, msg = err.get("code", f"HTTP_{resp.status_code}"), err.get("message", "")
            self.status = f"{code} request_id={rid}"
            return Message(text=f"{code}: {msg}".strip())
        code, msg = body.get("code", "OK"), body.get("message", "")
        data = body.get("data") or {}
        artifact = (data.get("artifact") or {}).get("sha256") or data.get("active_sha256")
        tail = f"\n[{code}" + (f" | artifact {artifact[:12]}" if artifact else "") + f" | request {rid}]"
        self.status = f"{code} request_id={rid}"
        return Message(text=f"{msg}{tail}")
