# Acceptance sign-off — workshop-v1 (Phase 12, 20 October 2026)

This is a copy of `docs/ACCEPTANCE.md`'s checklist with the actual result and an evidence pointer for each item.

**Result values.**
* **PASS (live):** shown against the deployed lab and Langflow.
* **PASS (isolated):** shown by the repository's isolated tests (`uv run pytest -q`; 639 passed on 20 Oct 2026, 23:5xZ).
* **NOT RUN / NOT DONE:** not evidenced. These are never counted as a pass.

**Scope of the evidence.** It holds for this bounded synthetic lab. It does not certify general sandbox security
or multi-user enterprise isolation. The admin account and trusted provisioning code remain powerful.

## Application checks

| ID | Result | Evidence |
|---|---|---|
| APP-01 | PASS (live + isolated) | Phase 11 `complete T001` → COMPLETED, same ID/title (`11-15`); `tests/unit/test_app_complete.py` |
| APP-02 | PASS (live + isolated) | Phase 11 `list` T002 unchanged (`11-15`); `test_reference_completes_retains_and_is_idempotent` |
| APP-03 | PASS (isolated) | `test_reference_completes_retains_and_is_idempotent` (repeat → `tasks_changed` 0) |
| APP-04 | PASS (isolated) | same test (`complete T999` → TASK_NOT_FOUND, records identical); PHASE03_REPORT |
| APP-05 | PASS (isolated) | `test_add_after_candidate_activation_creates_one_new_record` (added in Phase 12) |
| APP-06 | PASS (live + isolated) | Phase 11 `list` shows T001 [x] and T002 [ ] (`11-15`, `11-23`); APP-06 assertion in `test_app_complete.py` |
| APP-07 | PASS (live + isolated) | Phase 11 TS-30 `status` hash = receipt `rel_1e1e06da…` target (`11-15`); `interpreted_sha256` assertion |
| APP-08 | PASS (live + isolated) | Close/reopen: PHASE02_REPORT and `tests/integration/test_process_restart.py`. Real service restart: Phase 05 `check_stack.py --snapshot verify`; Phase 12 lab redeploy (0.7.0 → 0.8.0) kept every record (candidates 13, test runs 23, releases 3, generation 13 before and after) |

## Authorization, execution and recovery checks

| ID | Result | Evidence |
|---|---|---|
| SEC-01 | PASS (live + isolated) | Phase 05 `check_stack.py --target railway` (401s); `tests/security/test_deny_by_default.py` |
| SEC-02 | PASS (live + isolated) | PHASE04_REPORT / Phase 06 role tool counts; `test_wrong_roles_are_denied_on_every_route` |
| SEC-03 | PASS (isolated) | `tests/security/test_approval_execution.py` (agents cannot call approval, drill, reset or evaluator routes) |
| SEC-04 | PASS (isolated) | the report-immutability test in `tests/unit/test_protected_suite.py`; `tests/security/test_grader_isolation.py` |
| SEC-05 | PASS (live + isolated) | PHASE09_REPORT `APPROVAL_REQUIRED` `evt_a5b8e4b7…`; `test_approval_execution.py` |
| SEC-06 | PASS (live + isolated) | PHASE09_REPORT (forged fields 422); `tests/security/test_role_escalation.py` |
| SEC-07 | PASS (live + isolated) | PHASE09_REPORT (hash mismatches 409; operations approving 403) |
| SEC-08 | PASS (isolated) | `test_approval_execution.py` (expired/rejected/stale revision) |
| SEC-09 | PASS (live + isolated) | PHASE11_REPORT §5 replay (same receipt, ACTION_CONFLICT) |
| SEC-10 | PASS (isolated) | `tests/unit/test_state_machine.py` (optimistic concurrency) |
| SEC-11 | PASS (isolated) | `tests/unit/test_validator.py`, `tests/security/test_runner_escapes.py` |
| SEC-12 | PASS (isolated) | `tests/security/test_runner_escapes.py` (operation/elapsed limits) |
| SEC-13 | PASS (isolated) | `tests/security/test_commit_recheck.py`, `test_approval_execution.py` |
| SEC-14 | PASS (live + isolated) | `test_role_escalation.py`, `tests/unit/test_runs.py` (incl. Phase 12 per-role caps); live AE-06 3/3 (`77b8ed`) |
| SEC-15 | PASS (live + isolated) | PHASE09_REPORT (the operations credential cannot approve: 403); A2A contract rejects execution/approval fields (`tests/unit/test_a2a_exchanges.py`); AE-04 3/3 live (`77b8ed`) |
| SEC-16 | PASS (live) | TS-90 on neither MCP nor A2A (`verify_flows.py`, `doctor.py`, 23:50Z); not in any toolset allowlist (`test_components_static.py`) |
| SEC-17 | PASS (isolated) | `test_approval_execution.py` |
| SEC-18 | PASS (live + isolated) | `test_instructor_controls.py`; Phase 12 reset cancelled open plan `plan_ef3a06a8…` and run `run_6d79cc03…` (generation 20) |
| REC-01 | PASS (live + isolated) | Phase 11 drill `drl_92031e83…`: COMPLETION_UNAVAILABLE_DRILL, `/healthz` 200 (`11-16`, `11-17`); `test_instructor_controls.py` |
| REC-02 | PASS (live + isolated) | Phase 11 rollback `rel_3be93591…`, v0 active, T001 still completed (`11-21`…`11-23`) |
| REC-03 | PASS (live) | PHASE11_REPORT §5 (generations 12 and 13 identical); Phase 12 resets to generations 14–20 |
| REC-04 | PASS (same-instance dry-run); fresh-instance import **NOT RUN** | `export_bundle.py --redacted` + `import_flows.py --dry-run --flows-dir <bundle>/flows` keep ×7 (PHASE12_REPORT §4); helper-ID remap rehearsal PASS |

## Protocol checks

| ID | Result | Evidence |
|---|---|---|
| MCP-01 | PASS (live) | PHASE04_REPORT (protocol 2025-11-25, Streamable HTTP); Phase 06 role tool lists |
| MCP-02 | PASS (live) | Phase 06/11 tool calls with real lab records (e.g. `evt_526179e0…`) |
| MCP-03 | PASS (live + isolated) | PHASE04_REPORT (denial, timeout, session cleanup); AE-05 3/3 (`77b8ed`) |
| A2A-01 | PASS (live) | Card protocolVersion 0.3.0 (`verify_flows.py`, `doctor.py` 23:50Z); PHASE08_REPORT |
| A2A-02 | PASS (live) | Phase 11 Task `142844da-…`, artifact `c2a1511b-…`, exchange `a2ax_21440032…`, Operations run `run_ae180631…` |
| A2A-03 | PASS (live) | PHASE08_REPORT (no key / wrong key 401) |
| A2A-04 | PASS (live + isolated) | PHASE08_REPORT (PEER_UNAVAILABLE, DELEGATION_LIMIT); AE-07 3/3 (`77b8ed`) |
| HITL-01 | PASS (live) | PHASE09_REPORT approve/reject; Phase 11 approvals `apr_dd30ee46…` and `apr_48627549…` (Raj's clicks) |
| HITL-02 | PASS (scope stated) | PHASE09_REPORT: reload and repeat resume. **Langflow-restart durability of a pending Human Input: NOT TESTED** |

## Agent evaluation (24 trials, run `77b8ed`, report `aer_8ce88b1bcc26993f5533d584`, QUALIFIED)

| Case | Result | Evidence |
|---|---|---|
| AE-01 … AE-08 | 3/3 each, 0 critical (24/24) | `reports/redacted/agent_eval_20261020_2339_77b8ed.md` |

**Disclosures.**
* The earlier run `a01c0e` was NOT_QUALIFIED (22/24, 0 critical; AE-05 r1/r3). The cause was a grader false positive.
  The protected-file fix is in PHASE12_REPORT §3.
* Under the fixed grader, AE-05 r2 of `77b8ed` used the narrow exemption once. Under the old grader that trial would
  have failed (23/24).
* A three-repeat sample is small: these are counts, not a reliability percentage.

## Nine-term proof map

| Term | Evidence |
|---|---|
| Harness | AE-06 BUDGET_EXHAUSTED 3/3; Phase 11 §8 D2; per-role caps (`test_runs.py`) |
| Memory and State | `12-08` (fresh session reads canonical state plus the separate preference); AE-08 3/3 |
| RAG | Phase 11 story ST-001 citations (`11-04`); AE-01/AE-02 3/3 |
| MCP | Phase 06/11 tool calls; role denial SEC-02 |
| Agent Skills | `skill_loaded implement-todo-change 1.2.0` (`evt_83cca666…`, Phase 12); release-and-recover 1.0.0 (Phase 11) |
| Guardrails | SEC-05 raw denial; Phase 11 approved execution path (`11-13`, `11-14`) |
| Agent Evaluations | `77b8ed` report (independent harness, outcome + trajectory) |
| A2A | Phase 11 Task/artifact (`11-10`) |
| Multi-Agent Systems | Phase 11/12 traces with five distinct role runs (coordinator, product_owner, developer, qa, operations) |

## Final workshop-ready gate

| Item | Result | Evidence |
|---|---|---|
| All application, security, protocol and recovery checks have real results | PASS, with the NOT RUN items stated (REC-04 fresh instance; HITL-02 restart) | tables above |
| Critical failures resolved and rerun | PASS | `a01c0e` → grader fix → `77b8ed` QUALIFIED |
| Full scenario fits the rehearsed slots | PASS (Phase 11 full chain plus Phase 12 measurements) | SESSION_RUNBOOK "Timed plan". The fixed flows' full release chain was **not** re-run; the one-request rollback is **not** live-rehearsed |
| References and recordings labelled | PASS | FROZEN_VERSION "Origins and fallbacks" |
| Sanitized bundle reimports | PASS (same-instance dry-run) / fresh instance NOT RUN | PHASE12_REPORT §4 |
| Backend persists | PASS | APP-08 |
| Reset safe and repeatable | PASS | REC-03 |
| Session start: v0, two tasks, corpus/skills, no fault, no pending write, model connectivity, frozen manifest | PASS | `doctor.py` 23:47Z (live model turn 1.9 s) and 23:50Z after reset (18/18); `12-10`…`12-13`; FROZEN_VERSION |
| The human can stop the system and read evidence without the agents | PASS | TS-90 `stop`/`resume` (Phase 09, SEC-13); `doctor.py`, `phase11_checks.py snapshot` |
| Setup-only keys revoked after handover | **NOT DONE** | Raj revokes `tasksprint-bootstrap` (Settings → Langflow API Keys) after this phase |
