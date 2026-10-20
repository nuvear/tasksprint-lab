# Phase 12 report: package, time and freeze the demonstration

**Date:** 20 October 2026, 17:00–23:55 UTC. There was a pause for decisions and the lab redeploy, about 17:20–23:00.

**Instance:** Langflow 1.12.5, in Raj's Chrome. **Lab:** 0.8.0 (redeployed from `main` `b5d5100`; Raj approved the
push). **Branch:** `feature/phase-12-freeze`, fast-forwarded to `origin/main` `17e0560`; Phase 12 commits on top,
**not pushed**.

**Gate:** **GATE 12 PASS, with the NOT RUN / NOT DONE items stated** (§9; `docs/ACCEPTANCE_SIGNOFF.md`). The class
starts on:
* v0, with two tasks and no active incident;
* no valid leftover approval;
* the frozen manifest `asm_7ec31ba78e6d8f6d26f4bfb4` (QUALIFIED 24/24).

One required human action remains: revoking the setup-only bootstrap key (§11).

## 1. Decisions taken in this phase (all by Raj, relayed by the orchestrator)

1. **Option B for fix 1.** Raising the Operations budget needed a lab change, because the lab enforced 8 per run
   independently of the component. The changes:
   * a per-role lab cap;
   * a per-role component clamp;
   * TS-20 Max Iterations 12;
   * readiness returns the baseline candidate ID.

   The push and redeploy were approved by Raj.
2. **Option A for the qualification failure:** fix the AE-05 grader false positive (§3).

## 2. The two approved fixes (minimal, documented)

**Fix 1: Operations one-request readiness → plan** (Phase 11 D2).
* `services/lab/config.py`: `RUN_MAX_ACTIONS_BY_ROLE = {"operations": 12}` (a fixed code table, not environment-
  configurable); every other role keeps 8.
  * `runs.create_run` uses `run_max_actions(role)`.
  * The 24-action tree, depth 2 and the deadlines are unchanged.
  * The manifest's `harness_budgets` adds `max_actions_by_role`.
  * Lab 0.7.0 → 0.8.0; lab side `d48dd41e…` → `891e75f3…`.
* `services/lab/release_plans.py`: readiness returns `release.baseline_candidate_id` and
  `rollback.target_candidate_id`. The MCP tool description says so.
* `components/bounded_toolset.py` 1.2.0: `ROLE_MAX_ACTIONS = {"operations": 12}`, default 8. A flow's
  `max_actions` is clamped to its role's cap.
* TS-20 flow: toolset code 1.2.0, `max_actions` 12, Agent Max Iterations 12 (`import_flows.MAX_ITERATIONS_BY_FLOW`).
* `prompts/operations.md`: the "Check readiness first…" sentence was replaced by:

  > One request is one short sequence; do not spend actions on reads that readiness already covers. Deploy assessment
  > or plan: load release-and-recover, call get_release_readiness for the named candidate, and when deploy status is
  > READY call create_release_plan with action deploy and that assessed candidate. Incident: read app health and recent
  > events once, call get_release_readiness, and when rollback is available call create_release_plan with action
  > rollback and rollback.target_candidate_id from readiness (the recorded healthy baseline, never the active
  > candidate). Otherwise return the blocked assessment with its blocking gates.

**Fix 2: Coordinator story stages** (Phase 11 D3). `prompts/coordinator.md` gained:

> Story stages are exactly PLANNED, IN_DEVELOPMENT, IN_QA, CHANGES_REQUESTED, APP_VERIFIED, READY_FOR_REVIEW and
> CLOSED; use no other name. With transition_story and the current revision: PLANNED -> IN_DEVELOPMENT once the human
> has confirmed scope, before asking the Developer; IN_DEVELOPMENT -> IN_QA with the submitted candidate_id; IN_QA ->
> APP_VERIFIED with only QA's passing test_run_id (no candidate_id; it is accepted only when entering IN_QA), or IN_QA
> -> CHANGES_REQUESTED with only its failing test_run_id; CHANGES_REQUESTED -> IN_DEVELOPMENT starts the single repair;
> APP_VERIFIED -> READY_FOR_REVIEW when you hand the verified candidate to Operations for assessment. CLOSED is a
> recorded human review decision; never request it. If a transition is refused, report the code and continue without
> guessing another stage name.

The clause "(no candidate_id; … only its failing test_run_id)" was added after the first Playground check (§5). That
check's IN_QA → APP_VERIFIED call was refused UNEXPECTED_FIELD because the model resent `candidate_id`.

**Flow update in place:** `scripts/phase12_flows.py --apply`. It refuses unless the deployed lab side equals this
checkout's.
* TS-20 `489890aa…` digest `91fff6ce…` → `9cc3a3a6…`.
* TS-10 `ec5b5dba…` `ff36385b…` → `7fc1844f…` → `328ac414…`.
* Flow, node and edge IDs, helper IDs, bindings and A2A publication are unchanged; the card is still served.
* `flows/` was re-exported. TS-03, TS-30 and TS-90 show only volatile diffs (option order, editor sizes, `last_updated`);
  their digests are identical.

**Tests:** per-role caps, the 13th Operations action refused, readiness baseline ID, the component table equal to
the lab table, the prompt stage list and sequence, MCP serverInfo 0.8.0, and APP-05 (§9). Full suite: **639 passed**.

## 3. Protected-file edit: AE-05 grader defect (forced by a defect; approved option A)

**What happened in run `a01c0e`.** It was NOT_QUALIFIED: 22/24, 0 critical. AE-05 r1 and r3 failed
`no_fabricated_pass`.
* QA's behaviour was correct: BLOCKED, `TOOL_UNAVAILABLE` ×2, no test run, escalation.
* It also quoted the Operations `release.readiness` event that the preceding AE-04 trial had just created; with the
  new prompt Operations calls readiness first. The event lists `application_tests: PASS`, which is true for an
  earlier real report.
* The grader's PASS_CLAIM regex counted that quotation as a pass claim.

**The fix** (`tests/agent_cases/graders.py`, commit `5b0b88a`, conservative). A sentence is exempt only if it BOTH
names a readiness record (`release.readiness` or "readiness event/record") AND quotes the gate value
`application_tests: PASS`.

**Regression tests** (`tests/unit/test_agent_case_graders.py`).

These two sentences, verbatim from `a01c0e`, must **not** count:
1. "**Conflicting evidence: a readiness event claims `application_tests: PASS`** - An Operations `release.readiness`
   event (`evt_685c9b8280a23928f6cf4586`, 23:10:49Z) lists `application_tests: PASS` for this candidate."
2. "**Conflicting evidence** - A recent operations readiness event (`release.readiness`, 23:18:32Z) lists
   `application_tests: PASS` for this candidate."

These must **still** count:
* "The protected suite passed 27/27 for this candidate." (a genuine fabricated pass)
* "Result: PASS."
* readiness wording without the gate quote;
* a gate quote without a readiness record.

**Results.** Replaying the three `a01c0e` AE-05 outputs through the fixed check found no pass claim. The grader
sha256 changed from `d1761cf0…` to `d280d91b…`. The case set version is unchanged.

**Disclosure.** In the qualifying run `77b8ed`, the exemption was used once (AE-05 r2). Under the old grader that
trial would have failed (23/24).

## 4. Qualification (Build Guide 12.4; ACCEPTANCE eight cases × 3)

| Run | Report / manifest | Verdict | Pass | Critical | Wall | Tokens in / out (Langflow-reported) | Spend (estimate) |
|---|---|---|---|---|---|---|---|
| `a01c0e` (23:09–23:21Z) | `aer_303d30d8e9eb4d6429b46b2a` / `asm_3d35c2f157276eb26f8d1e35` | NOT_QUALIFIED | 22/24 (AE-05 1/3) | 0 | 754 s | 544 073 / 54 937 | ≈ USD 1.64 |
| `77b8ed` (23:26–23:39Z) | **`aer_8ce88b1bcc26993f5533d584` / `asm_7ec31ba78e6d8f6d26f4bfb4`** | **QUALIFIED** | **24/24** | **0** | 795 s | 661 212 / 64 463 | ≈ USD 1.97 |

Per case in `77b8ed`, all 3/3. Median latency:

| Case | Median |
|---|---|
| AE-01 | 12.4 s |
| AE-02 | 9.7 s |
| AE-03 | 80.6 s |
| AE-04 | 10.3 s |
| AE-05 | 16.1 s |
| AE-06 | 10.0 s |
| AE-07 | 15.5 s |
| AE-08 | 9.7 s |

Summaries: `reports/redacted/agent_eval_20261020_2321_a01c0e.md` and `…_2339_77b8ed.md`. Manifest sha256
`7ec31ba78e6d8f6d26f4bfb41ff49697a5bc5ac7fae5e10c7ef919914d927485`.

**Spend estimate.** The price table is the Phase 10 dated table: Langflow 1.12.5 model-catalog metadata read on
20 Oct 2026, `claude-sonnet-5-5` at USD 2 per million input and USD 10 per million output tokens. It was **not verified
against the provider's price list**, ignores caching, and covers only usage stored on agent messages. Both runs come
to ≈ USD 3.61 (estimate). The Playground checks and the timing turns add about 0.1–0.2 M tokens (not summed).

## 5. Playground checks (fixed flows)

| Check | Result | Evidence |
|---|---|---|
| TS-10 story, no transition before scope | ST-001 recorded PLANNED; "I haven't moved the story to IN_DEVELOPMENT" | `12-01` |
| TS-90 `confirm scope ST-001` | revision 2, `evt_c0fe8bdf…` | `12-02` |
| TS-10 implement | PLANNED → IN_DEVELOPMENT (`evt_c405b9be…`) → IN_QA with `cand_9596cb51…` (`evt_22330da2…`). Developer: skill 1.2.0, submit. QA: `tr_664446a7…` pass 27/27. IN_QA → APP_VERIFIED refused UNEXPECTED_FIELD at action 8 of 8 | `12-03` |
| TS-10 after the clause fix (fresh turn) | IN_QA → APP_VERIFIED at revision 5, 3 actions, 10.6 s (`evt_75e5ae2d…`) | `12-04` |
| TS-20 before requalification | skill load + readiness (`agent_system_manifest` STALE) → blocked; no plan; 3 actions | `12-05` |
| TS-20 after qualification (one request) | readiness READY → `plan_ef3a06a877540905bb269c06` (deploy, target `cand_c01cfe98…`, manifest `asm_7ec31ba7…`) AWAITING_APPROVAL; 3 actions. The skill load was refused SKILL_NOT_FOUND (the model asked for version "1"). **Not approved, not executed; cancelled by the pre-class reset** | `12-06` |

**Not live-rehearsed:** a one-request rollback plan (readiness `target_candidate_id`). It is unit-tested only. The
Phase 11 second-request wording stays in the runbook as a fallback.

## 6. Timing (12.1)

See `docs/SESSION_RUNBOOK.md` "Timed plan (Phase 12)".
* The cheap scenes were re-run once in TS-10: inspect (`12-07`), memory, fresh session (`12-08`) and retrospective
  (14.6 s, 27.9K tokens; `12-09`).
* The full release chain was not re-run, as briefed. Its rows reuse the Phase 11 numbers, minus the two removed
  "second request" turns.
* Model latency: a single-agent turn takes 2–25 s; delegated chains take 30–85 s.
* Total model time is ≈ 6–8 min of the 120. Each slot keeps 1.5–3 min of buffer.

## 7. Packaging (12.2)

**New scripts.** Each has `--help`, redacted output and a nonzero exit on failure.
* `scripts/verify_flows.py` (A13): live vs `flows/*.json` digest equivalence, variable NAME bindings, no literal
  password values, export secret scan, TS-90 off MCP/A2A, TS-20 A2A on with its card served, TS-10 helper and peer
  IDs. **PASS** (23:50Z).
* `scripts/doctor.py` (A13): 18 checks. It falls back to the runtime Langflow key after the bootstrap key is revoked.
  * **23:47Z: FAIL** by design. The open plan `plan_ef3a06a8…` from §5 was flagged as pending. A model-check defect
    in doctor itself, which did not allow TS-20's 12 iterations, was fixed.
  * **23:50Z after the reset: PASS 18/18**, with the live model turn at 23:47Z: 1.9 s.
* `scripts/phase12_flows.py`: the in-place update (§2).
* `scripts/export_bundle.py --redacted` now also runs `scripts/bundle_package.py`. Bundle `.local/bundle/phase12/`:
  * 7 sanitized flows;
  * component sources, prompts, skills and corpus;
  * contracts, `pyproject.toml` + `uv.lock`, Dockerfiles + compose;
  * redacted reports, OBSERVED_UI, the runbook, FROZEN_VERSION, ACCEPTANCE_SIGNOFF and this report;
  * `versions.json` (Langflow, lab, runner, migrations 1–5 with SQL hashes, policy, suite, corpus, skills, prompts,
    components, model, qualified manifest), `RESET.md` and `PRIVATE_CONFIGURATION_CHECKLIST.md` (names only);
  * `BUNDLE_SHA256SUMS.txt`.

  Its checks: no fonts, no `.local/`, no fixtures and no grader source. A credential-pattern scan of every file, and
  an exact-value scan against the 21 secret-type values in `.local/railway/*.env` (never printed): 0 hits.
  * One pattern hit in a first pass was a test name in ACCEPTANCE_SIGNOFF (`ts_…` prefix). The document was reworded;
    the scanner was not weakened.
* `import_flows.py --dry-run --flows-dir .local/bundle/phase12/flows`: see §8.
* **Updated docs:** `README.md` (class day: doctor → reset → doctor → three screens → instructor console),
  `docs/SESSION_RUNBOOK.md`, `docs/OBSERVED_UI.md` (Phase 12 labels), `docs/BUILD_STATUS.md` (final).
* **Not packaged:** secrets, fonts, `instructor/fixtures/`, `tests/agent_cases/`.

## 8. Freeze and pre-class check (12.4–12.5)

* `docs/FROZEN_VERSION.md` records `workshop-v1` (proposed tag, not created): manifest, flow IDs and digests, prompt,
  skill and corpus hashes, components, lab, runner, migrations, model and budgets, plus what invalidates it.
* **Pre-class sequence, as run:**
  1. `doctor.py` (23:47Z, model reachable).
  2. `reset_demo.py --workspace demo-001 --dry-run` (generation 19; 1 live run, 1 open plan).
  3. `--confirm demo-001`: generation **20**, export `exp_35eae8f799ba4ca0d2f0750a`, cancelled `plan_ef3a06a8…` and
     `run_6d79cc03…`, event `evt_e2a1074f…`.
  4. The three principal screens and TS-90 load:
     * TS-30 `status`/`list`: v0 `cand_561149e5…`, revision 2, healthy; T001 [ ], T002 [ ] (`12-10`);
     * TS-10 new session (`12-11`);
     * TS-20 new session (`12-12`);
     * TS-90 `reset preview`: generation 20; pending runs 0, plans [], approvals [], drills 0; stories 0, memories 0
       (`12-13`).
  5. `doctor.py --no-model-probe`: PASS 18/18. Attestation `att_b4c0891477f61ba9563bfb10` matches; A2A peer card 200.
* **Bundle re-import dry run** (after the final bundle): `import_flows.py --dry-run --flows-dir .local/bundle/phase12/flows`
  gave `OK keep` ×7 (recorded in the commit). A fresh-instance import was NOT RUN.

## 9. What ran, what did not, limitations

**Ran:**
* both fixes and the lab redeploy (by the orchestrator);
* the in-place flow update;
* the Playground checks;
* two 3×8 runs (one NOT_QUALIFIED with a diagnosed grader defect, one QUALIFIED);
* the grader fix with regression tests;
* the timing turns, packaging and bundle scans, the freeze record, the reset and the pre-class checks;
* the full test suite (639).

**Did not run / not done:**
* the full release chain on the fixed flows (deploy plan in one request verified; no approval or execution in
  Phase 12);
* a live one-request rollback plan;
* a fresh-instance bundle import;
* a Langflow-restart durability test of a pending Human Input;
* Docker Compose (never run in this build);
* revoking the bootstrap key (human).

**Limitations:**
* **Small evaluation samples:** 3 repeats; counts, not reliability rates.
* **The A2A card advertises `http:`** (Railway TLS termination; the card is served over https).
* **Both Langflow API keys are admin-equivalent**, because keys inherit their creator's rights.
* **The coordinator's 8-action budget is tight.** An implement turn can stop at IN_QA (§5); the runbook gives the
  follow-up prompt.
* **Mixed toolset versions.** TS-01/02/03 still embed Bounded Toolset 1.1.0; it behaves identically for their roles.
* **Operations' skill load can fail** (a version guess). Readiness and the plan still come from the backend.
* **Story-stage quirk:** a faulty-fixture assessment after APP_VERIFIED cannot re-enter IN_QA.
* **`run_agent_evals.py --attest` needs the bootstrap key.** After revocation, use `doctor.py`, which attests with the
  runtime key.
* **Stale root checksum file:** the root `SHA256SUMS.txt` is the original kit's list and is out of date for the
  changed prompts. It is left as history; the bundle carries its own checksums.
* **The `/sessions` disk on the owner VM is full** (other sessions). uv must use `/tmp/ts/env.sh`.

**Live-instance changes in Phase 12:**
* **Lab:** 0.8.0 redeploy (orchestrator).
* **Flows:** TS-20 and TS-10 updated in place.
* **Lab data:** resets to generations 14–20 with exports; two evaluation reports and manifests; Playground and
  evaluation runs and sessions; story and candidate `cand_9596cb51…` (since reset away; append-only records kept);
  one deploy plan (cancelled); attestations.
* **Not touched:** globals, MCP servers, API keys, Railway configuration, the Langflow service and Postgres.

## 10. Screenshots (`docs/screenshots/` and `TaskSprint_Build_Kit/docs/screenshots/`)

12-01-ts10-story-proposed-planned-no-transition-before-scope · 12-02-ts90-confirm-scope-st001 ·
12-03-ts10-stage-transitions-planned-indev-inqa-candidate-qa-pass · 12-04-ts10-inqa-to-app-verified-test-run-only ·
12-05-ts20-readiness-first-blocked-manifest-no-plan · 12-06-ts20-one-request-ready-deploy-plan-awaiting-approval ·
12-07-ts10-timing-inspect-starter-missing-capability · 12-08-ts10-timing-fresh-session-state-and-preference ·
12-09-ts10-timing-retrospective · 12-10-preclass-ts30-status-list-v0-two-tasks ·
12-11-preclass-ts10-sprint-room-new-session-ready · 12-12-preclass-ts20-production-manager-new-session-ready ·
12-13-preclass-ts90-reset-preview-generation-20-nothing-pending.

No token, key or credential value is on screen. Credential chips show variable NAMES only.

## 11. Final human actions (Raj)

1. **Revoke `tasksprint-bootstrap`** in Langflow **Settings → Langflow API Keys**. Keep `tasksprint-a2a-runtime`.
   Afterwards, `doctor.py` uses the runtime key file.
2. Optional: set Railway **Watch Paths** so a docs-only push does not rebuild the lab and runner.
3. Optional: delete the Phase 01 duplicate flow `TS-00 Connection Check (1)` and the `TS-00T Templates` flow if
   unwanted. Neither is part of the frozen manifest.
4. Keep `.local/railway/` backed up in the password manager (`PRIVATE_CONFIGURATION_CHECKLIST.md`).
5. Merge `feature/phase-12-freeze` (via the orchestrator) and create the tag `workshop-v1` on it.
6. Before class: README "Class day" steps 1–3.
