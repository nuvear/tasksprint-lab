# Frozen workshop version — `workshop-v1` (proposed git tag; not created)

**Frozen:** 20 October 2026, 23:50 UTC (Phase 12). Branch `feature/phase-12-freeze` (not pushed). The deployed lab
code is commit `b5d5100` on `origin/main` (+ empty retrigger `17e0560`). The grader fix is commit `5b0b88a`.
Create the tag on the commit that adds this file, once the orchestrator has merged the branch.

## Qualified agent-system manifest (the class runs only on this)

| Item | Value |
|---|---|
| Manifest | `asm_7ec31ba78e6d8f6d26f4bfb4`, sha256 `7ec31ba78e6d8f6d26f4bfb41ff49697a5bc5ac7fae5e10c7ef919914d927485` |
| Report | `aer_8ce88b1bcc26993f5533d584` (QUALIFIED, 24/24, 0 critical), sha256 `1c2c6b74…f9242`, run `77b8ed` (23:26:10–23:39:28Z) |
| Qualified at | 2026-10-20T23:39:27Z. Last attestation `att_b4c0891477f61ba9563bfb10` (23:50Z, matches). 24 h verification window; `doctor.py` re-attests |
| Lab side | `891e75f30db995f9f8b93970fd6b1a4862163e80ba6b6f0c59e303311aec6031` |
| Langflow / harness side | `d666e4744381b5c00c8a2e8d7cfe8e26f9c2d85e4025d924c6f56bb067badd6e` |
| Harness / case set / grader | `tasksprint-agent-eval-harness/1.0.0` / `tasksprint-agent-cases/1` / grader sha256 `d280d91b34be9f92bf56663af665bfc83adaae39148fb84f87bb166378fe8cf3` |
| Summary | `reports/redacted/agent_eval_20261020_2339_77b8ed.md` |

## Platform, model and limits

* **Langflow:** 1.12.5 at `https://langflow-railway-production-f493.up.railway.app`, project TaskSprint.
* **A2A:** TS-20 card protocolVersion 0.3.0.
* **Model:** `claude-sonnet-5-5` (Anthropic, Langflow Agent component) in all five agent flows. Max Iterations 8
  (TS-01, TS-02, TS-03, TS-10) and **12 (TS-20)**. Calculator and Current Date are off.
* **Lab:** `tasksprint-lab` 0.8.0 (`https://tasksprint-lab-production.up.railway.app`).
* **Runner:** `tasksprint-runner/0.3.0`; candidate grammar `ts-python-subset/1`.
* **Migrations:** 1–5 (Phase 02, 04, 08, 09, 10). The migration SQL hashes are in the bundle's `versions.json`.
* **Policy:** `tasksprint-release-policy/3`, plan schema 1.2.
* **Protected suite:** `tasksprint-app-suite/1` (`051dfb58…9551`). Baseline smoke: `tasksprint-baseline-smoke/1`
  (`03e8e249…b138`).
* **Harness budgets:** 8 actions per invocation (**operations 12**); 24 per parent tree; depth 2; deadlines 90 s
  (specialist) and 180 s (parent); one repair; one transient-read retry.

## Flows (live IDs = committed exports; `scripts/verify_flows.py` PASS at 23:50Z)

| Flow | Live ID | Content digest | `flows/` file sha256 | Notes |
|---|---|---|---|---|
| TS-30 To-do App | `1613b28e-6e07-4056-a832-b9abeceb607e` | `5d2cc5086a7cb9e3` | `9e9c449e…0077` | App Console 1.0.1 |
| TS-01 Product Owner | `da674f03-2861-4b3f-9f25-129bb86a588f` | `3a33c7047c9b5bd8` | `7ac525d2…9ec5` | Bounded Toolset 1.1.0 embedded (cap 8; same behaviour as 1.2.0 for this role) |
| TS-02 Developer | `9610ee79-66ce-4f92-b304-44d9e5c8be38` | `790759914b507786` | `05b6c13f…c9ef` | as TS-01 |
| TS-03 QA | `8906e4df-4fe3-489f-b30b-d5e57230459c` | `fe30048f942744c5` | `469a9fd4…0db1` | as TS-01 |
| TS-20 Production Manager | `489890aa-4bd0-4641-b669-070f10e0922b` | `9cc3a3a621414162` | `64fc255e…d9f2` | Bounded Toolset 1.2.0, max_actions 12, A2A on |
| TS-10 Sprint Room | `ec5b5dba-d7d2-4aeb-899c-016a3f66b4eb` | `328ac41413c4f485` | `10a512c3…f4a0` | Bounded Toolset 1.2.0, A2A Audit 1.0.0 |
| TS-90 Instructor Console | `cda48ae0-d8bb-44bc-a422-91f9576fba43` | `ecdd3429e009ba81` | `dc0837e8…b02c` | human-only; MCP and A2A off |

**Components (repository source):** `bounded_toolset` 1.2.0 (`6924d9c8…`), `run_context` 1.2.0, `a2a_audit` 1.0.0,
`app_console` 1.0.1, `instructor_control` 1.0.1, `review_decision` 1.0.0. The per-file sha256 values are in
`versions.json`.

## Prompts, skills, corpus

| Item | Version / sha256 |
|---|---|
| `prompts/coordinator.md` | `0d67dc6d…1468` (Phase 12: story stages) |
| `prompts/operations.md` | `97dd00fc…0e20` (Phase 12: one-request readiness → plan) |
| `prompts/product_owner.md`, `developer.md`, `qa.md` | `82537ee3…`, `d03bd9f2…`, `e2393167…` (unchanged in Phase 12) |
| Skill `implement-todo-change` | 1.2.0, body `894af05f…4328`, package `935c2d0b…3e2e` |
| Skill `release-and-recover` | 1.0.0, body `92d996e2…0c2f`, package `ddf70afa…20fa6` |
| Corpus manifest | `01058009bba9c688…18e1`: product brief 1.1, definition of done 1.0 and release policy 1.0 (approved); early design note 0.1 (archived, for AE-02) |

## Class start state (pre-class check, 23:48–23:50Z)

* demo-001 at **generation 20** (reset `evt_e2a1074f…`, export `exp_35eae8f799ba4ca0d2f0750a`).
* v0 `cand_561149e5c98bb5b7e8ab7357` active at release revision 2 (a monotonic counter); business health healthy.
* T001 and T002 incomplete.
* No story, memory, drill, outage, stop flag, live run, open plan or unused approval.
* The model was reachable (live turn 1.9 s at 23:47Z) and so was the A2A peer card.

## What invalidates this freeze

Any change to the model or its parameters, a prompt, a skill, the corpus, the MCP tool catalog or permissions, a
custom component, a flow (wiring, settings, Max Iterations, bindings), the lab code (lab side), the release policy,
or the harness or grader. Any of these changes the attested system, and the lab's manifest gate then blocks
deploy plans until `run_agent_evals.py --repeats 3` qualifies again.

These do **not** invalidate it: a reset, class Playground sessions, revoking the setup-only bootstrap key, or an
attestation that matches. A Langflow canvas **save** may change a flow; if a save happens, run `verify_flows.py` and
`doctor.py`.

## Origins and fallbacks (labelled)

* Agent-generated candidates are live.
* `fixture-faulty` is the labelled teaching fixture, loaded openly in TS-90.
* `fixture-reference` is the labelled fallback. It was not used in any rehearsal.
* Phase 11 recordings are rehearsal evidence, not a live class run.
