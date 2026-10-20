# TaskSprint Review Decision: trusted post-decision adapter for TS-90 (Architecture A11; Build Guide 09.2).
# Wired to ONE branch of the native Human Input node (one instance on "Approve", one on "Reject"). Its
# decision is the fixed node setting "Decision" (approve | reject), chosen when the flow is built, never
# parsed from text: the human's click selects which branch (and therefore which instance) runs at all.
#
# Across the Human Input pause it receives back the exact review text that TaskSprint Instructor Control
# produced (Human Input returns its prompt on the chosen branch). It extracts the canonical snapshot JSON,
# re-hashes it, requires that hash to equal the reference line AND the snapshot hash the backend computes
# for that plan now, then records ONE decision with the human-approver credential:
#     POST /v1/approvals {plan_id, plan_sha256, snapshot_sha256, decision, display_name?, hitl_request_id}
# The backend re-verifies everything (exact hashes, AWAITING_APPROVAL, expiry, one decision per plan).
# It never executes anything and never sends an "approved" flag. "Reviewer name" is a label only.
# Version 1.0.0. Source of truth: tasksprint-lab/components/review_decision.py
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlparse

import httpx

from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageInput, MessageTextInput, Output, SecretStrInput
from lfx.schema.message import Message

ADAPTER_VERSION = "review_decision/1.0.0"
WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
NAME_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,64}$")
REF_RE = re.compile(r"^TS-REVIEW-REF plan_id=(plan_[0-9a-f]{24}) plan_sha256=([0-9a-f]{64}) "
                    r"snapshot_sha256=([0-9a-f]{64})$", re.M)
BLOCK_RE = re.compile(r"^```json\n(\{.*\})\n```$", re.M)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def extract(text: str) -> tuple[dict, str, str, str]:
    """(snapshot, plan_id, plan_sha256, snapshot_sha256) from the reviewed text; raise if not exact."""
    refs, blocks = REF_RE.findall(text or ""), BLOCK_RE.findall(text or "")
    if len(refs) != 1 or len(blocks) != 1:
        raise ValueError("the reviewed text does not carry exactly one snapshot and one reference line")
    plan_id, plan_sha, snap_sha = refs[0]
    snapshot = json.loads(blocks[0])
    if canonical(snapshot) != blocks[0]:
        raise ValueError("the carried snapshot is not in canonical form")
    if hashlib.sha256(blocks[0].encode("ascii")).hexdigest() != snap_sha:
        raise ValueError("the carried snapshot does not hash to the referenced snapshot_sha256")
    if snapshot.get("plan_id") != plan_id or snapshot.get("plan_sha256") != plan_sha:
        raise ValueError("the reference line does not match the carried snapshot")
    return snapshot, plan_id, plan_sha, snap_sha


class TaskSprintReviewDecision(Component):
    display_name = "TaskSprint Review Decision"
    description = ("Trusted adapter after Human Input: records the fixed decision of this branch against the exact "
                   "reviewed snapshot hash (POST /v1/approvals). Never executes a release.")
    icon = "gavel"
    name = "TaskSprintReviewDecision"

    inputs = [
        MessageInput(name="reviewed", display_name="Reviewed snapshot (Human Input branch)", required=True),
        DropdownInput(name="decision", display_name="Decision (fixed for this branch)", options=["approve", "reject"],
                      value="reject", info="Set once when building the flow: approve on the Approve branch, reject "
                                           "on the Reject branch. Never derived from text."),
        MessageTextInput(name="reviewer_label", display_name="Reviewer name (label only)", value="", advanced=True,
                         info="Stored with the record; confers no authority."),
        MessageTextInput(name="api_base", display_name="TaskSprint API base", value="TASKSPRINT_API_BASE",
                         load_from_db=True, advanced=True),
        SecretStrInput(name="approver_token", display_name="Approver token", value="", load_from_db=True,
                       info="Bind the Credential global TS_APPROVER_TOKEN."),
        MessageTextInput(name="workspace", display_name="Workspace", value="demo-001", advanced=True),
    ]
    outputs = [Output(display_name="Decision record", name="record", method="record_decision")]

    def _hitl_request_id(self) -> str | None:
        graph = getattr(self, "graph", None)
        run_id = str(getattr(graph, "run_id", "") or "")
        ids = [v.id for v in getattr(graph, "vertices", []) or [] if str(v.id).startswith("HumanInput-")]
        if len(ids) == 1 and run_id:
            rid = f"{ids[0]}:{run_id}"
            return rid if re.match(r"^[A-Za-z0-9_.:\-]{1,160}$", rid) else None
        return None

    def record_decision(self) -> Message:
        decision = self.decision if self.decision in ("approve", "reject") else None
        if decision is None:
            raise ValueError("Decision must be configured as approve or reject")
        base = (self.api_base or "").strip().rstrip("/")
        u = urlparse(base)
        if u.scheme != "https" or not u.hostname or u.path or u.query or u.fragment or u.username:
            raise ValueError("TASKSPRINT_API_BASE must be an https origin without a path")
        ws = (self.workspace or "").strip()
        if not WORKSPACE_RE.match(ws):
            raise ValueError("workspace id is invalid")
        token = self.approver_token or ""
        if len(token) < 32:
            raise ValueError("approver token is not bound (Credential global TS_APPROVER_TOKEN missing)")
        text = self.reviewed.text if isinstance(self.reviewed, Message) else str(self.reviewed or "")
        try:
            _snap, plan_id, plan_sha, snap_sha = extract(text)
        except (ValueError, json.JSONDecodeError) as err:
            self.status = {"recorded": False, "reason": "snapshot"}
            return Message(text=f"NOT RECORDED: {err}. Nothing was recorded or executed; run review again.")
        headers = {"Authorization": f"Bearer {token}", "X-TaskSprint-Workspace": ws, "User-Agent": ADAPTER_VERSION}
        live = httpx.get(f"{base}/v1/release-plans/{plan_id}", headers=headers, timeout=30.0, follow_redirects=False)
        lb = live.json() if live.headers.get("content-type", "").startswith("application/json") else {}
        if live.status_code != 200 or lb.get("snapshot_sha256") != snap_sha:
            code = (lb.get("error") or {}).get("code") or ("SNAPSHOT_CHANGED" if live.status_code == 200 else
                                                           f"HTTP_{live.status_code}")
            self.status = {"recorded": False, "reason": code}
            return Message(text=f"NOT RECORDED: {code}. The backend no longer serves this exact snapshot for "
                                f"{plan_id}; nothing was recorded or executed. Run review {plan_id} again.")
        body = {"plan_id": plan_id, "plan_sha256": plan_sha, "snapshot_sha256": snap_sha, "decision": decision}
        label = " ".join(str(self.reviewer_label or "").split())
        if label and NAME_RE.match(label):
            body["display_name"] = label
        hitl = self._hitl_request_id()
        if hitl:
            body["hitl_request_id"] = hitl
        resp = httpx.post(f"{base}/v1/approvals", json=body, headers=headers, timeout=30.0, follow_redirects=False)
        try:
            rb = resp.json()
        except ValueError:
            rb = {}
        if resp.status_code != 201:
            e = rb.get("error") or {}
            self.status = {"recorded": False, "reason": e.get("code")}
            return Message(text=f"NOT RECORDED ({decision}): {e.get('code', 'HTTP_' + str(resp.status_code))} - "
                                f"{e.get('message', '')} [request {e.get('request_id', '-')}]. Nothing was executed.")
        self.status = {"recorded": True, "approval_id": rb["approval_id"], "decision": rb["decision"]}
        return Message(text=(
            f"HUMAN DECISION RECORDED: {rb['decision'].upper()} {rb['approval_id']} for {plan_id}\n"
            f"plan_sha256 {rb['plan_sha256']}\nsnapshot_sha256 {rb['snapshot_sha256']}\n"
            f"status {rb['status']}; plan state {rb['plan_state']}; expires {rb['expires_at']}; event {rb['event_id']}"
            f"; HITL request {rb.get('hitl_request_id') or '-'}\n{rb['note']}"))
