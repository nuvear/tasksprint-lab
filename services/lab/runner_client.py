"""Lab-side client for the separate bounded runner (Architecture A2, A6).

The lab sends candidate source (with its SHA-256), a bounded copy of task
records and the task ID; it never sends database paths, role tokens or any
other secret except the transport-only runner token in the Authorization
header. Every response is checked: the runner must echo the exact source hash
it interpreted, and the envelope must have the documented shape. Anything
else is treated as RUNNER_UNAVAILABLE (fail closed, no mutation).
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from .store import LabError

_STATUSES = {"ok", "rejected", "error"}
_CODE = re.compile(r"^[A-Z_]{1,40}$")
ENVELOPE_KEYS = {"status", "runner_version", "grammar_version", "source_sha256", "result", "error", "ops",
                 "elapsed_ms", "limits"}


class RunnerClient:
    def __init__(self, base_url: str, token: str, *, timeout_s: float = 5.0, http: httpx.Client | None = None):
        self._token = token
        self._timeout = timeout_s
        # ``http`` lets tests pass a client bound to an in-process runner app.
        self._http = http or httpx.Client(base_url=base_url, timeout=timeout_s, follow_redirects=False,
                                          trust_env=False)

    def __repr__(self) -> str:  # never show the token
        return "RunnerClient(<configured>)"

    def evaluate(self, *, source: str, source_sha256: str, tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
        body = {"source": source, "source_sha256": source_sha256, "tasks": tasks, "task_id": task_id}
        try:
            resp = self._http.post("/v1/evaluate", json=body, headers={"Authorization": f"Bearer {self._token}"})
        except httpx.HTTPError as exc:
            raise LabError(503, "RUNNER_UNAVAILABLE", "the bounded runner could not be reached",
                           {"audit": {"transport_error": type(exc).__name__}}) from None
        if resp.status_code != 200:
            code = "RUNNER_UNAVAILABLE"
            try:
                code = str(resp.json()["error"]["code"])[:40]
            except Exception:  # noqa: BLE001 - any malformed error body is just unavailable
                pass
            raise LabError(503, "RUNNER_UNAVAILABLE", "the bounded runner refused the evaluation request",
                           {"audit": {"runner_status": resp.status_code, "runner_code": code}})
        try:
            doc = resp.json()
        except ValueError:
            raise LabError(503, "RUNNER_UNAVAILABLE", "runner returned a malformed response") from None
        if type(doc) is not dict or not ENVELOPE_KEYS <= set(doc) or doc["status"] not in _STATUSES:
            raise LabError(503, "RUNNER_UNAVAILABLE", "runner returned a malformed response")
        if doc["source_sha256"] != source_sha256:
            raise LabError(503, "RUNNER_UNAVAILABLE", "runner did not interpret the requested source hash")
        if doc["status"] != "ok":
            err = doc.get("error")
            if type(err) is not dict or type(err.get("code")) is not str or not _CODE.match(err["code"]):
                raise LabError(503, "RUNNER_UNAVAILABLE", "runner returned a malformed error")
        if type(doc["ops"]) is not int or type(doc["runner_version"]) is not str:
            raise LabError(503, "RUNNER_UNAVAILABLE", "runner returned a malformed response")
        return doc


def build_runner(settings: Any) -> RunnerClient | None:
    if not settings.runner_url:
        return None
    return RunnerClient(settings.runner_url, settings.runner_token, timeout_s=settings.runner_timeout_s)
