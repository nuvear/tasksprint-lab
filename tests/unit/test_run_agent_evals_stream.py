"""Phase 10: the harness's streamed Langflow run (adopted after the 60 s disconnect in rehearsal c22095).

Uses httpx.MockTransport with TEST-ONLY bodies in the shape Langflow 1.12.5's /api/v1/run?stream=true
emits (JSON event objects separated by blank lines); no network, no model.
"""
from __future__ import annotations

import json
import sys

import httpx
import pytest

from services.lab.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import run_agent_evals as h  # noqa: E402

RESULT = {"outputs": [{"outputs": [{"results": {"message": {"text": "final answer"}}}]}], "session_id": "s"}


def lf_with(body: str, status: int = 200, seen: list | None = None) -> h.Langflow:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, content=body.encode(), headers={"content-type": "text/event-stream"})
    return h.Langflow("https://lf.invalid", "test-only-key", transport=httpx.MockTransport(handler))


def ev(event, data):
    return json.dumps({"event": event, "data": data}) + "\n\n"


def test_streamed_run_returns_the_end_result_and_requests_streaming():
    seen = []
    body = ev("add_message", {"text": "step"}) + ev("token", {"chunk": "x"}) + ev("end", {"result": RESULT})
    code, resp, ms = lf_with(body, seen=seen).run("TS-10", "hi", "sess", None)
    assert code == 200 and h._output_text(resp) == "final answer" and resp["_stream_events"] == 3
    assert seen[0].url.params["stream"] == "true" and json.loads(seen[0].content)["session_id"] == "sess"


def test_error_event_and_missing_end_are_errors_not_results():
    code, resp, _ = lf_with(ev("add_message", {}) + ev("error", {"error": "boom"})).run("TS-01", "hi", "s", None)
    assert code == 0 and "boom" in resp["_error"]
    code, resp, _ = lf_with(ev("add_message", {})).run("TS-01", "hi", "s", None)
    assert code == 0 and "without an end event" in resp["_error"]
    code, resp, _ = lf_with(json.dumps({"detail": "nope"}), status=403).run("TS-01", "hi", "s", None)
    assert code == 403


def test_the_last_event_without_a_trailing_blank_line_is_parsed():
    code, resp, _ = lf_with(ev("add_message", {}) + json.dumps({"event": "end", "data": {"result": RESULT}})).run(
        "TS-03", "hi", "s", None)
    assert code == 200


@pytest.mark.parametrize("flow", ["TS-90", "TS-02", "TS-30"])
def test_the_harness_refuses_to_invoke_non_evaluated_flows(flow):
    with pytest.raises(h.SetupError):
        lf_with(ev("end", {"result": RESULT})).run(flow, "hi", "s", None)
