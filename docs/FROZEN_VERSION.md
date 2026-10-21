# Frozen workshop version — `workshop-v1.1` (proposed git tag; not created)

**Frozen:** 21 October 2026, 04:01 UTC (Phase 13). Branch `feature/phase-13-webview`, merged into local `main`, **not
pushed**. Create the tag `workshop-v1.1` on `main` after Raj pushes it.

**What changed from `workshop-v1` (tag on `f0f175a`):**
* **Lab 0.9.0** (`60b2b63`) adds the production web view `GET /app` (static page; the application role's existing
  routes only; no permission or MCP catalog change).
* Two protected evaluation-file edits:
  * AE-05 grader fix 2 (`190f91e`);
  * AE-05 runs before AE-04 (`6c211dc`).
* Flows, prompts, skills, corpus, components, model and budgets are **unchanged**.

The `workshop-v1` manifest `asm_7ec31ba7…` no longer applies: the lab side changed.

## Qualified agent-system manifest (the class runs only on this)

| Item | Value |
|---|---|
| Manifest | **`asm_c8f4f59d8778fb215c72817b`**, sha256 `c8f4f59d8778fb215c72817bddf37292af2ccc49102008259fb82abc9e35eaa5` |
| Report | `aer_d181ee99b7275877a8a9bf5e` (QUALIFIED, 24/24, 0 critical), sha256 `10a896e130e9b833daae8529c341de42e7026132b91b079d939d4d238c720a08`, run `b5e0c2` (03:47:45–03:59:38Z) |
| Qualified at | 2026-10-21T03:59:37Z. Attestations: `att_6525ff20a1b1fa9efaaa49f3` (`--attest`, 04:00Z) and `att_76d909afa76733c59fd662e0` (doctor, runtime key, after reset); both match. 24 h verification window; `doctor.py` re-attests |
| Lab side | `94a92143717e2f40016bfe71ef48dce84f614dadd1016c574f586c4f4af92cd2` (lab 0.9.0) |
| Langflow / harness side | `5d5a633df57a41e30cba11283c33bf5fb22fbb9ca9503e5d893e47cf48afb96b` |
| Harness / case set | `tasksprint-agent-eval-harness/1.0.0` (`scripts/run_agent_evals.py` `27d121d8…`, unchanged) / `tasksprint-agent-cases/1` (`cases.py` `26edf3da3bf7e08b00bf2f5e99ef647eacba9315d057cedffab614153a6f8737`; order AE-08, AE-01, AE-02, **AE-05, AE-04**, AE-07, AE-06, AE-03) |
| Grader | `graders.py` `57e1224304d6b901d5338a308674981b60e3d6bb9c4e8b8e722380dbe2d48b69` (grader fix 2). Combined grader sha256 (cases + graders + harness, as in the manifest) **`371a72476a4da2e3703717ee9ef97b4c189c11d0a127e51c9b8d575bc4467559`**. History: `d1761cf0…` (Phase 10) → `d280d91b…` (Phase 12) → `03d413d2…` (grader fix 2) → `371a7247…` (run order) |
| Summary | `reports/redacted/agent_eval_20261021_0359_b5e0c2.md` |

**Disclosed non-qualifying runs (Phase 13).** Both were stopped at AE-05 r1 by instruction, and no lab report was
submitted for either:
* `8a5fed` (grader `d280d91b…`);
* `d13034` (grader `03d413d2…`).

The cause was the same in both. AE-05 ran right after AE-04's readiness read, QA quoted that readiness event, and the
lexical `no_fabricated_pass` check counted it. QA's behaviour was correct. See `docs/PHASE13_REPORT.md` §3–5. The
Phase 12 runs (`a01c0e` NOT_QUALIFIED, `77b8ed` QUALIFIED) belong to `workshop-v1`.

## Platform, model and limits

* **Langflow:** 1.12.5 at `https://langflow-railway-production-f493.up.railway.app`, project TaskSprint.
* **A2A:** TS-20 card protocolVersion 0.3.0.
* **Model:** `claude-sonnet-5-5` (Anthropic, Langflow Agent component) in all five agent flows. Max Iterations 8
  (TS-01, TS-02, TS-03, TS-10) and **12 (TS-20)**. Calculator and Current Date are off.
* **Lab:** `tasksprint-lab` 0.9.0 (`https://tasksprint-lab-production.up.railway.app`). The web view is at `/app`; its
  static files (`services/lab/static/`) are not part of the lab-side hash, but the routes that serve them are
  (`main.py`, `auth.py`, `webview.py`).
* **Runner:** `tasksprint-runner/0.3.0`; candidate grammar `ts-python-subset/1`.
* **Migrations:** 1–5 (Phase 02, 04, 08, 09, 10). The migration SQL hashes are in the bundle's `versions.json`.
* **Policy:** `tasksprint-release-policy/3`, plan schema 1.2.
* **Protected suite:** `tasksprint-app-suite/1` (`051dfb58…9551`). Baseline smoke: `tasksprint-baseline-smoke/1`
  (`03e8e249…b138`).
* **Harness budgets:** 8 actions per invocation (**operations 12**); 24 per parent tree; depth 2; deadlines 90 s
  (specialist) and 180 s (parent); one repair; one transient-read retry.

## Flows (live IDs = committed exports; `scripts/verify_flows.py` PASS at 04:01Z, 21 Oct; unchanged since Phase 12)

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

## Class start state (pre-class check, 04:00Z, 21 Oct)

* demo-001 at **generation 26** (reset `evt_1084656d3857cbb79d40f6f2`, export `exp_a5795a21776c3513abbc7cf1`).
* v0 `cand_561149e5c98bb5b7e8ab7357` active at release revision 2 (a monotonic counter); business health healthy.
* T001 and T002 incomplete.
* No story, memory, drill, outage, stop flag, live run, open plan or unused approval.
* The model was reachable (live turn 1.8 s at 04:00Z, runtime key) and so was the A2A peer card.
* The web view `/app` served 200 with its CSP; data calls without a token: 401.

## What invalidates this freeze

Any change to the model or its parameters, a prompt, a skill, the corpus, the MCP tool catalog or permissions, a
custom component, a flow (wiring, settings, Max Iterations, bindings), the lab code (lab side), the release policy,
the harness, the case set (including its run order) or the grader. Any of these changes the attested system, and the lab's manifest gate then blocks
deploy plans until `run_agent_evals.py --repeats 3` qualifies again.

These do **not** invalidate it: a change to the web view's static files only (`services/lab/static/`; not in the lab
side, but rerun `tests/security/test_webview.py`), a reset, class Playground sessions, revoking the setup-only Langflow keys, or an
attestation that matches. A Langflow canvas **save** may change a flow; if a save happens, run `verify_flows.py` and
`doctor.py`.

## Origins and fallbacks (labelled)

* Agent-generated candidates are live.
* `fixture-faulty` is the labelled teaching fixture, loaded openly in TS-90.
* `fixture-reference` is the labelled fallback. It was not used in any rehearsal.
* Phase 11 recordings are rehearsal evidence, not a live class run.
