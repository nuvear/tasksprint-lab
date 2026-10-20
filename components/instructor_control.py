# TaskSprint Instructor Control: trusted, deterministic Langflow custom component for TS-90 (Architecture A3,
# A8, A11, A12; Build Guide 09.1-09.2). NO model, NO Agent, NO tool mode. It parses ONE typed command line:
#
#   confirm scope ST-001            instructor   human Product Owner scope confirmation
#   review plan_<24 hex>            approver     fetch the canonical review snapshot -> Human Input (Approve/Reject)
#   load fixture faulty|reference   instructor   register a LABELLED instructor fixture candidate
#   drill enable cand_<24 hex> [m]  instructor   completion_unavailable for the ACTIVE candidate, m minutes (1-30)
#   drill disable cand_<24 hex>     instructor
#   stop | resume                   instructor   kill switch for the workspace's agent runs
#   run evals                       evaluator    Phase 10 (explained here; nothing is called)
#   reset preview                   instructor   counts and pending work; changes nothing
#   reset confirm demo-001          instructor   A12 reset of the designated workspace only
#
# Anything else is refused with the usage text and no request. Three FIXED clients use three separate
# Credential globals (TS_APPROVER_TOKEN, TS_INSTRUCTOR_TOKEN, TS_EVALUATOR_TOKEN); the URL is the fixed
# TASKSPRINT_API_BASE origin. No text can choose a role, a token, a URL, a decision or an "approved" flag:
# for `review`, this component only READS the plan; the decision is the human's click on the native Human
# Input node, written afterwards by the separate TaskSprint Review Decision adapter against the exact
# snapshot hash shown here. Outputs: "Review" (only for a reviewable plan; feeds Human Input) and
# "Result" (everything else; feeds a Chat Output). The unused output is stopped so its branch never runs.
# Never place this flow on an MCP server, publish it over A2A, or give it to an agent as a tool.
# Version 1.0.0. Source of truth: tasksprint-lab/components/instructor_control.py
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx

from lfx.custom.custom_component.component import Component
from lfx.io import MessageInput, MessageTextInput, Output, SecretStrInput
from lfx.schema.message import Message

ADAPTER_VERSION = "instructor_control/1.0.0"
WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
MAX_LINE = 120
GRAMMAR = (
    ("confirm_scope", re.compile(r"^confirm scope (ST-\d{3})$", re.I)),
    ("review", re.compile(r"^review (plan_[0-9a-f]{24})$", re.I)),
    ("load_fixture", re.compile(r"^load fixture (faulty|reference)$", re.I)),
    ("drill_enable", re.compile(r"^drill enable (cand_[0-9a-f]{24})(?: ([1-9]|[12][0-9]|30))?$", re.I)),
    ("drill_disable", re.compile(r"^drill disable (cand_[0-9a-f]{24})$", re.I)),
    ("stop", re.compile(r"^stop$", re.I)),
    ("resume", re.compile(r"^resume$", re.I)),
    ("run_evals", re.compile(r"^run evals$", re.I)),
    ("reset_preview", re.compile(r"^reset preview$", re.I)),
    ("reset_confirm", re.compile(r"^reset confirm ([a-z0-9][a-z0-9-]{2,63})$")),
)
USAGE = ("Accepted commands (one per message): confirm scope ST-001 | review plan_<id> | load fixture faulty|reference"
         " | drill enable cand_<id> [minutes] | drill disable cand_<id> | stop | resume | run evals | reset preview"
         " | reset confirm <workspace>. Nothing was sent.")
FIXTURES = {"faulty": "faulty_delete", "reference": "reference_complete"}
REF_LINE = "TS-REVIEW-REF"


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def parse_command(text: str):
    line = " ".join((text or "").split())
    if not line or len(line) > MAX_LINE or "\n" in (text or "").strip():
        return None, ()
    for name, rx in GRAMMAR:
        m = rx.match(line)
        if m:
            return name, tuple(g for g in m.groups() if g is not None)
    return None, ()


def review_text(plan: dict) -> str:
    """Human-readable review plus the EXACT canonical snapshot (the adapter re-hashes this JSON)."""
    s = plan["review_snapshot"]
    t, cur = s["target"], s["current"]
    ev = s["application_test_evidence"]
    lines = [
        f"HUMAN REVIEW REQUIRED - {s['operation'].upper()} plan {s['plan_id']} for {s['environment']} "
        f"(workspace {s['workspace_id']})",
        f"Target: {t['candidate_id']} sha256 {t['sha256']} (origin {t['origin']}, label {t['label']})",
        f"Current active: {cur['candidate_id']} sha256 {cur['sha256']}; expected release revision "
        f"{s['expected_release_revision']}",
        "Application tests: " + ("none (rollback uses the baseline smoke suite)" if ev is None else
                                 f"{ev['test_run_id']} {ev['outcome']} (suite {ev['suite_sha256'][:16]}...)"),
        f"Agent-system manifest: {s['agent_baseline_manifest']['status']}",
        f"Rollback target: {s['rollback_target']['sha256']} (baseline evidence "
        f"{s['rollback_target']['baseline_evidence_id']})",
        f"Plan expires: {s['plan_expires_at']}",
        f"plan_sha256: {s['plan_sha256']}",
        f"snapshot_sha256: {plan['snapshot_sha256']}",
        s["consent_scope"],
        "Approve or Reject below. Typed chat is not a decision, and neither choice executes anything.",
        "",
        "Exact snapshot (canonical JSON; the decision is bound to its SHA-256):",
        "```json",
        canonical(s),
        "```",
        f"{REF_LINE} plan_id={s['plan_id']} plan_sha256={s['plan_sha256']} snapshot_sha256={plan['snapshot_sha256']}",
    ]
    return "\n".join(lines)


class TaskSprintInstructorControl(Component):
    display_name = "TaskSprint Instructor Control"
    description = ("Trusted human-only control (TS-90): typed command parser with fixed approver, instructor and "
                   "evaluator clients. No model. Review output feeds Human Input; Result feeds Chat Output.")
    icon = "shield-check"
    name = "TaskSprintInstructorControl"

    inputs = [
        MessageInput(name="input_value", display_name="Command", required=True),
        MessageTextInput(name="api_base", display_name="TaskSprint API base", value="TASKSPRINT_API_BASE",
                         load_from_db=True, advanced=True,
                         info="Bind the Generic global TASKSPRINT_API_BASE (https origin, no path)."),
        SecretStrInput(name="approver_token", display_name="Approver token (read plans)", value="",
                       load_from_db=True, info="Bind the Credential global TS_APPROVER_TOKEN."),
        SecretStrInput(name="instructor_token", display_name="Instructor token", value="", load_from_db=True,
                       info="Bind the Credential global TS_INSTRUCTOR_TOKEN."),
        SecretStrInput(name="evaluator_token", display_name="Evaluator token", value="", load_from_db=True,
                       info="Bind the Credential global TS_EVALUATOR_TOKEN (Phase 10 harness only)."),
        MessageTextInput(name="workspace", display_name="Workspace", value="demo-001", advanced=True),
    ]
    outputs = [
        Output(display_name="Review", name="review", method="review_output", group_outputs=True),
        Output(display_name="Result", name="result", method="result_output", group_outputs=True),
    ]

    # ------------------------------------------------------------------ fixed clients
    def _base(self) -> str:
        base = (self.api_base or "").strip().rstrip("/")
        u = urlparse(base)
        if u.scheme != "https" or not u.hostname or u.path or u.query or u.fragment or u.username:
            raise ValueError("TASKSPRINT_API_BASE must be an https origin without a path")
        return base

    def _ws(self) -> str:
        ws = (self.workspace or "").strip()
        if not WORKSPACE_RE.match(ws):
            raise ValueError("workspace id is invalid")
        return ws

    def _call(self, method: str, path: str, token: str, body: dict | None = None) -> tuple[int, dict]:
        if len(token or "") < 32:
            return 0, {"error": {"code": "CREDENTIAL_NOT_BOUND", "message": "the Credential global is not bound"}}
        try:
            resp = httpx.request(method, self._base() + path, json=body, timeout=30.0, follow_redirects=False,
                                 headers={"Authorization": f"Bearer {token}", "X-TaskSprint-Workspace": self._ws(),
                                          "User-Agent": ADAPTER_VERSION})
        except httpx.HTTPError as err:
            return 0, {"error": {"code": "LAB_UNREACHABLE", "message": type(err).__name__}}
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {"error": {"code": f"HTTP_{resp.status_code}", "message": "non-JSON reply"}}

    def _instructor(self, action: str, **fields) -> tuple[int, dict]:
        return self._call("POST", "/v1/instructor/actions", self.instructor_token,
                          {"action": action, "workspace_id": self._ws(), **fields})

    # ------------------------------------------------------------------ one parse + one request per run
    def _outcome(self) -> dict:
        cached = getattr(self, "_ts_outcome", None)
        if cached is not None:
            return cached
        raw = self.input_value.text if isinstance(self.input_value, Message) else str(self.input_value or "")
        cmd, args = parse_command(raw)
        out: dict
        if cmd is None:
            out = {"kind": "result", "command": None, "text": "REFUSED: unknown command. " + USAGE}
        elif cmd == "review":
            code, body = self._call("GET", f"/v1/release-plans/{args[0]}", self.approver_token)
            if code != 200:
                out = self._error(cmd, code, body)
            elif body.get("decision"):
                d = body["decision"]
                out = {"kind": "result", "command": cmd, "text": (
                    f"Plan {args[0]} already has a recorded human decision: {d['decision'].upper()} "
                    f"{d['approval_id']} at {d['created_at']} (status {d['status']}, snapshot "
                    f"{d['snapshot_sha256'][:16]}..., expires {d['expires_at']}). Plan state {body['state']}. "
                    "No new review was opened; nothing was executed.")}
            elif body.get("effective_state") != "AWAITING_APPROVAL":
                out = {"kind": "result", "command": cmd, "text": (
                    f"Plan {args[0]} is {body.get('effective_state')} and cannot be reviewed. Ask Operations for a "
                    "new plan; nothing was recorded.")}
            else:
                out = {"kind": "review", "command": cmd, "text": review_text(body),
                       "plan_id": args[0], "snapshot_sha256": body["snapshot_sha256"]}
        elif cmd == "run_evals":
            bound = len(self.evaluator_token or "") >= 32
            out = {"kind": "result", "command": cmd, "text": (
                "Agent evaluations are Phase 10: the trusted harness (scripts/run_agent_evals.py) runs the eight "
                "cases x3 against the real flows and records its report with the evaluator credential. Nothing was "
                f"run now. Evaluator credential bound: {'yes' if bound else 'no'} (never shown).")}
        else:
            if cmd == "confirm_scope":
                code, body = self._instructor("confirm_scope", story_id=args[0].upper())
            elif cmd == "load_fixture":
                code, body = self._instructor("load_fixture", fixture=FIXTURES[args[0].lower()])
            elif cmd == "drill_enable":
                extra = {"ttl_minutes": int(args[1])} if len(args) > 1 else {}
                code, body = self._instructor("drill_enable", fault_type="completion_unavailable",
                                              candidate_id=args[0].lower(), **extra)
            elif cmd == "drill_disable":
                code, body = self._instructor("drill_disable", fault_type="completion_unavailable",
                                              candidate_id=args[0].lower())
            elif cmd == "stop":
                code, body = self._instructor("stop", reason="TS-90 instructor stop")
            elif cmd == "resume":
                code, body = self._instructor("resume")
            elif cmd == "reset_preview":
                code, body = self._instructor("reset_preview")
            else:  # reset_confirm
                if args[0] != self._ws():
                    out = {"kind": "result", "command": cmd, "text": (
                        f"REFUSED: reset confirm must name this console's workspace ({self._ws()}). Nothing was sent.")}
                    self._ts_outcome = out
                    return out
                code, body = self._instructor("reset_confirm", confirm=args[0])
            out = self._error(cmd, code, body) if code != 200 else {
                "kind": "result", "command": cmd, "text": self._summary(cmd, body)}
        self._ts_outcome = out
        self.status = {"command": out["command"], "kind": out["kind"]}
        return out

    @staticmethod
    def _error(cmd: str, code: int, body: dict) -> dict:
        e = body.get("error") or {}
        return {"kind": "result", "command": cmd, "text": (
            f"NOT DONE ({cmd}): {e.get('code', 'HTTP_' + str(code))} - {e.get('message', '')} "
            f"[request {e.get('request_id', '-')}]")}

    @staticmethod
    def _summary(cmd: str, b: dict) -> str:
        if cmd == "confirm_scope":
            st = b["story"]
            return (f"Scope confirmed for {st['story_id']} (criteria v{st['criteria_version']}, revision "
                    f"{st['revision']}, stage {st['stage']}). {b.get('note', '')}")
        if cmd == "load_fixture":
            c = b["candidate"]
            return (f"Fixture loaded ({b['fixture']}): {c['candidate_id']} sha256 {c['sha256']} origin {c['origin']} "
                    f"label '{c['label']}' (created {b['created']}). Labelled instructor fixture, not live coding.")
        if cmd == "drill_enable":
            return (f"Drill {b['drill_id']} completion_unavailable ON for {b['candidate_id']} until {b['expires_at']} "
                    f"(created {b['created']}); app health {b['app_health']}. {b['note']}")
        if cmd == "drill_disable":
            return f"Drill OFF for {b['candidate_id']} ({b['disabled']} disabled); app health {b['app_health']}."
        if cmd in ("stop", "resume"):
            return (f"{cmd.upper()}: stopped={b['stopped']} (was {b['was_stopped']}); cancelled runs "
                    f"{len(b['cancelled_runs'])}; event {b['event_id']}. {b['note']}")
        if cmd == "reset_preview":
            p = b.get("pending") or {}
            return (f"Reset preview for {b['workspace_id']} (generation {b.get('generation')}): counts "
                    f"{json.dumps(b.get('counts'), sort_keys=True)}; pending runs {len(p.get('active_runs', []))}, "
                    f"plans {p.get('open_plans', [])}, approvals {p.get('active_approvals', [])}, drills "
                    f"{len(p.get('enabled_drills', []))}. Would: {'; '.join(b.get('would_do', []))}. Nothing changed. "
                    f"To apply: reset confirm {b['workspace_id']}")
        if cmd == "reset_confirm":
            return (f"Reset done: {b['workspace_id']} generation {b['generation']}; evidence export "
                    f"{b['export']['export_id']} sha256 {b['export']['export_sha256']}; cancelled plans "
                    f"{b['cancelled']['open_plans']}, approvals {b['cancelled']['active_approvals']}; restored v0 "
                    f"release {b['restored_v0_release_id']}; tasks {b['tasks_seeded']}; event {b['event_id']}.")
        return json.dumps(b, sort_keys=True)[:1500]

    # ------------------------------------------------------------------ outputs
    def review_output(self) -> Message:
        out = self._outcome()
        if out["kind"] != "review":
            self.stop("review")
            return Message(text="")
        return Message(text=out["text"])

    def result_output(self) -> Message:
        out = self._outcome()
        if out["kind"] == "review":
            self.stop("result")
            return Message(text="")
        return Message(text=out["text"])
