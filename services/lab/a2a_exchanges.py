"""Audited A2A exchange records (Architecture A9, A10; Phase 08).

The trusted Sprint Room adapter (``components/a2a_audit.py``) calls the Production
Manager over the genuine A2A JSON-RPC transport with the a2a SDK and then records the
redacted raw exchange here with the coordinator credential. No model can call this
route (it has no MCP tool). The lab does not trust the adapter's summary: it

* validates the carried ``assess_release`` payload against ``contracts/handoff-task``,
* derives the protocol task / context / message / artifact IDs from the returned Task
  object itself and checks them against the independent ``tasks/get`` read-back,
* links the exchange to the parent coordinator run and to the Operations runs created
  as that run's children (lineage), with Operations' own recorded tool calls, and
* verifies every plan / event / test-run / candidate ID quoted in the returned artifact
  against its own records (``linked_evidence``), so a fabricated reference is flagged.

Records are append-only (``a2a_exchanges`` triggers). Recording is evidence, not a
business mutation, so a late record after the parent run's deadline is accepted and
marked with the run's status at record time.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from .audit import REDACTED, record_event
from .clock import parse_iso, utc_now, utc_now_iso
from .config import REPO_ROOT
from .store import LabError

CONTRACT_PATH = REPO_ROOT / "contracts" / "handoff-task.schema.json"
_SENSITIVE_KEY = re.compile(r"(token|secret|password|passwd|authorization|api[_-]?key|credential|cookie)", re.I)
_SENSITIVE_VALUE = re.compile(r"(Bearer\s+\S+|ts_[a-z]+_[A-Za-z0-9_\-]{16,}|sk-[A-Za-z0-9_\-]{8,})")
_MAX_STR, _MAX_ITEMS, _MAX_DEPTH = 4000, 50, 10
REF_PATTERNS = {
    "plan": re.compile(r"\bplan_[0-9a-f]{24}\b"),
    "event": re.compile(r"\bevt_[0-9a-f]{24}\b"),
    "test_run": re.compile(r"\btr_[0-9a-f]{24}\b"),
    "candidate": re.compile(r"\bcand_[0-9a-f]{24}\b"),
}


def redact_deep(value: Any, depth: int = 0) -> Any:
    """Like audit.redact but keeps protocol payloads readable (longer strings, deeper nesting)."""
    if depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_ITEMS:
                out["_truncated"] = True
                break
            key = str(k)[:64]
            out[key] = REDACTED if _SENSITIVE_KEY.search(key) else redact_deep(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = [redact_deep(v, depth + 1) for v in list(value)[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            items.append("[TRUNCATED]")
        return items
    if isinstance(value, str):
        cleaned = _SENSITIVE_VALUE.sub(REDACTED, value)
        return cleaned if len(cleaned) <= _MAX_STR else cleaned[:_MAX_STR] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_deep(str(value), depth + 1)


@lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator, FormatChecker  # transitive dependency of the mcp SDK
    schema = json.loads(Path(CONTRACT_PATH).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker()), hashlib.sha256(
        Path(CONTRACT_PATH).read_bytes()).hexdigest()


def contract_problems(payload: Any) -> list[str]:
    validator, _ = _validator()
    problems = [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.validator}"
                for e in validator.iter_errors(payload)][:10]
    if not problems:
        try:
            parse_iso(payload["deadline_utc"])
        except (ValueError, TypeError, KeyError):
            problems.append("deadline_utc: date-time")
    return problems


def contract_sha256() -> str:
    return _validator()[1]


def _parts_text(parts: Any) -> list[str]:
    texts: list[str] = []
    for p in parts if isinstance(parts, list) else []:
        if isinstance(p, dict):
            if isinstance(p.get("text"), str):
                texts.append(p["text"])
            elif "data" in p:
                texts.append(json.dumps(p["data"], sort_keys=True, default=str))
    return texts


def protocol_ids(task: dict | None) -> dict[str, Any]:
    """IDs exactly as the returned Task carries them (a2a JSON / protobuf JSON field names)."""
    if not isinstance(task, dict):
        return {"task_id": None, "context_id": None, "state": None, "artifact_ids": [], "message_ids": []}
    status = task.get("status") if isinstance(task.get("status"), dict) else {}
    artifacts = [a for a in task.get("artifacts") or [] if isinstance(a, dict)]
    history = [m for m in task.get("history") or [] if isinstance(m, dict)]
    msgs = [m.get("messageId") or m.get("message_id") for m in history]
    st_msg = status.get("message") if isinstance(status.get("message"), dict) else None
    if st_msg:
        msgs.append(st_msg.get("messageId") or st_msg.get("message_id"))
    return {"task_id": task.get("id"), "context_id": task.get("contextId") or task.get("context_id"),
            "state": status.get("state"),
            "artifact_ids": [a.get("artifactId") or a.get("artifact_id") for a in artifacts][:20],
            "message_ids": [m for m in msgs if m][:20]}


def artifact_texts(task: dict | None) -> list[str]:
    if not isinstance(task, dict):
        return []
    out: list[str] = []
    for a in task.get("artifacts") or []:
        if isinstance(a, dict):
            out += _parts_text(a.get("parts"))
    return out


def link_evidence(conn: sqlite3.Connection, workspace_id: str, texts: list[str]) -> list[dict[str, Any]]:
    joined = "\n".join(texts)
    found: list[dict[str, Any]] = []
    for kind, rx in REF_PATTERNS.items():
        for ref in sorted(set(rx.findall(joined)))[:20]:
            item: dict[str, Any] = {"kind": kind, "id": ref, "exists": False}
            if kind == "plan":
                row = conn.execute("SELECT p.plan_sha256, s.state FROM release_plans p JOIN release_plan_states s"
                                   " ON s.plan_id = p.plan_id WHERE p.plan_id = ? AND p.workspace_id = ?",
                                   (ref, workspace_id)).fetchone()
                if row:
                    item.update(exists=True, plan_sha256=row["plan_sha256"], state=row["state"])
            elif kind == "event":
                row = conn.execute("SELECT action, outcome, actor_role FROM events WHERE event_id = ? AND"
                                   " workspace_id = ?", (ref, workspace_id)).fetchone()
                if row:
                    item.update(exists=True, action=row["action"], outcome=row["outcome"], actor=row["actor_role"])
            elif kind == "test_run":
                row = conn.execute("SELECT outcome, candidate_sha256 FROM test_runs WHERE test_run_id = ? AND"
                                   " workspace_id = ?", (ref, workspace_id)).fetchone()
                if row:
                    item.update(exists=True, outcome=row["outcome"])
            else:
                row = conn.execute("SELECT sha256 FROM candidates WHERE candidate_id = ? AND workspace_id = ?",
                                   (ref, workspace_id)).fetchone()
                if row:
                    item.update(exists=True, sha256=row["sha256"])
            found.append(item)
    return found


def peer_runs(conn: sqlite3.Connection, workspace_id: str, parent_run_id: str) -> list[dict[str, Any]]:
    """Operations runs created as children of the delegating coordinator run, with their own tool trace."""
    out = []
    for r in conn.execute("SELECT run_id, depth, actions_used, status, created_at FROM runs WHERE parent_run_id = ?"
                          " AND workspace_id = ? AND role = 'operations' ORDER BY created_at",
                          (parent_run_id, workspace_id)).fetchall():
        trace = []
        for e in conn.execute("SELECT event_id, action, outcome, details_json, created_at FROM events WHERE run_id = ?"
                              " ORDER BY rowid", (r["run_id"],)).fetchall():
            d = json.loads(e["details_json"])
            trace.append({"event_id": e["event_id"], "action": e["action"], "outcome": e["outcome"],
                          **{k: d[k] for k in ("tool", "code", "plan_id", "name", "version") if k in d}})
        out.append({"run_id": r["run_id"], "depth": r["depth"], "actions_used": r["actions_used"],
                    "created_at": r["created_at"], "tool_trace": trace[:40]})
    return out[:5]


def record_exchange(conn: sqlite3.Connection, *, workspace_id: str, actor_role: str, request_id: str,
                    body: Any) -> dict[str, Any]:
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (body.parent_run_id,)).fetchone()
    if run is None or run["workspace_id"] != workspace_id or run["role"] != actor_role:
        raise LabError(403, "RUN_NOT_BOUND", "parent run is not bound to this credential and workspace")
    problems = contract_problems(body.request)
    if problems:
        raise LabError(422, "CONTRACT_VIOLATION", "the carried assess_release payload does not match the contract",
                       {"problems": problems})
    if body.request["workspace_id"] != workspace_id:
        raise LabError(422, "CONTRACT_VIOLATION", "payload workspace does not match the trusted workspace")
    ids = protocol_ids(body.task)
    readback = protocol_ids(body.task_get)
    consistent = None
    if body.task is not None and body.task_get is not None:
        consistent = (readback["task_id"] == ids["task_id"] and readback["context_id"] == ids["context_id"]
                      and readback["state"] == ids["state"])
    if body.outcome == "completed" and (not ids["task_id"] or ids["state"] not in ("TASK_STATE_COMPLETED", "completed")):
        raise LabError(422, "EXCHANGE_INCONSISTENT", "a completed outcome requires a returned Task in a completed state")
    texts = artifact_texts(body.task)
    linked = link_evidence(conn, workspace_id, texts)
    peers = peer_runs(conn, workspace_id, body.parent_run_id)
    live = run["status"] == "active" and parse_iso(run["deadline_at"]) > utc_now()
    raw = redact_deep({"request_payload": body.request, "task": body.task, "task_get": body.task_get,
                       "http": body.http, "error": body.error})
    exchange_id = "a2ax_" + secrets.token_hex(12)
    now = utc_now_iso()
    record = {
        "exchange_id": exchange_id, "workspace_id": workspace_id, "parent_run_id": body.parent_run_id,
        "parent_run_status_at_record": "active" if live else ("expired" if run["status"] == "active" else run["status"]),
        "peer": {"flow_id": body.peer_flow_id, "card_url": body.card_url, "protocol_version": body.protocol_version,
                 "transport": body.transport},
        "adapter_version": body.adapter_version, "contract_sha256": contract_sha256(),
        "outcome": body.outcome, "protocol": ids, "tasks_get_consistent": consistent,
        "linked_evidence": linked, "peer_runs": peers,
        "started_at": body.started_at, "finished_at": body.finished_at, "recorded_at": now,
        "recorded_by": f"{actor_role} credential via trusted adapter",
    }
    exchange_json = json.dumps({**record, "raw": raw}, sort_keys=True, ensure_ascii=False)
    conn.execute(
        "INSERT INTO a2a_exchanges(exchange_id, workspace_id, parent_run_id, peer_flow_id, protocol_version, outcome,"
        " task_id, context_id, exchange_json, exchange_sha256, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (exchange_id, workspace_id, body.parent_run_id, body.peer_flow_id, body.protocol_version, body.outcome,
         ids["task_id"], ids["context_id"], exchange_json, hashlib.sha256(exchange_json.encode()).hexdigest(), now))
    record["event_id"] = record_event(
        conn, request_id=request_id, actor_role=actor_role, action="a2a.exchange", outcome=body.outcome,
        workspace_id=workspace_id, run_id=body.parent_run_id,
        details={"exchange_id": exchange_id, "task_id": ids["task_id"], "context_id": ids["context_id"],
                 "state": ids["state"], "artifact_ids": ids["artifact_ids"][:5], "peer_flow_id": body.peer_flow_id,
                 "protocol_version": body.protocol_version, "peer_runs": [p["run_id"] for p in peers],
                 "linked": [f"{x['id']}:{'ok' if x['exists'] else 'UNKNOWN'}" for x in linked][:10],
                 "error_code": (body.error or {}).get("code")})
    return record


def read_exchange(conn: sqlite3.Connection, workspace_id: str, exchange_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT exchange_json, exchange_sha256 FROM a2a_exchanges WHERE exchange_id = ? AND"
                       " workspace_id = ?", (exchange_id, workspace_id)).fetchone()
    if row is None:
        raise LabError(404, "EXCHANGE_NOT_FOUND", "A2A exchange record does not exist in this workspace")
    return {**json.loads(row["exchange_json"]), "exchange_sha256": row["exchange_sha256"]}
