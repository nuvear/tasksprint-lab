# Phase 13 report: production web view of the To-do app, requalify, re-freeze

**Date:** 21 October 2026, 01:55–04:05 UTC (two pauses for decisions and the lab redeploy).

**Instance:** Langflow 1.12.5 (unchanged). **Lab:** 0.9.0, redeployed from `main` `60b2b63` (the orchestrator pushed
and Raj approved). **Branch:** `feature/phase-13-webview`, merged into local `main`. **Not pushed, not tagged.**

**Gate:** **GATE 13 PASS.**
* The web view `/app` is live.
  * Raj verified it in his browser: token gate, v0, T001/T002, Complete → FEATURE_UNAVAILABLE (`13-01`, `13-02`).
* The agent system is requalified at **24/24, 0 critical**: run `b5e0c2`, report `aer_d181ee99b7275877a8a9bf5e`,
  manifest `asm_c8f4f59d8778fb215c72817b`.
* The class start state is restored: generation 26, v0 at revision 2, T001/T002, nothing pending, doctor PASS on the
  runtime key.
* Proposed tag: **`workshop-v1.1`** (Raj creates it).

## 1. Decisions taken in this phase (Raj, relayed by the orchestrator)

1. **Option A web view.** A static page served by the lab. The agent system (flows, prompts, skills, components) is
   unchanged; only the lab gains the page.
2. **Requalification needed the Langflow setup key.** `run_agent_evals.py` (and `verify_flows.py`) read
   `.local/railway/langflow_bootstrap.env` and nothing else. The Phase 12 key had been revoked.
   * Raj created a temporary key, `tasksprint-setup-tmp` (expires 2026-10-28), in that file.
   * The harness was not edited for this.
3. **Option 1 (after run `8a5fed`):** a narrow AE-05 grader fix (§3).
4. **Option 2 (after run `d13034`):** fix the cause in the evaluation design, not by adding another wording rule (§4).

## 2. The web view (lab 0.9.0, commit `60b2b63`)

**Files:**
* `services/lab/static/app.html`, `app.js` and `app.css`;
* `services/lab/webview.py`;
* `services/lab/auth.py`, which adds `WEBVIEW_ROUTES` to `PUBLIC_ROUTES`;
* `services/lab/main.py`, which calls `webview.register(app)`;
* `SERVICE_VERSION` 0.8.0 → 0.9.0.

**Routes:** `GET /app`, `/app/`, `/app/app.js`, `/app/app.css`.
* They are public because they carry no data and no secret.
* The files are read once at start-up and served from a fixed table, with no path parameter.
* Headers:
  * `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-ancestors 'none'`
    (also as a `<meta>`);
  * `X-Content-Type-Options: nosniff`;
  * `X-Frame-Options: DENY`;
  * `Referrer-Policy: no-referrer`;
  * `Cache-Control: no-store`.

**Behaviour:**
* **Token gate.** "Application token" is a masked `type=password` field with **Connect**. The token is kept only in
  the tab's `sessionStorage`: never in a cookie, the URL, local storage or the page. **Disconnect** clears it, and a
  401 drops back to the gate.
* **Polling, every 3 s,** with `Authorization: Bearer <token>` and `X-TaskSprint-Workspace: demo-001`:
  * `POST /v1/app/commands` `{"command":"list"}` and `{"command":"status"}` (the TS-30 App Console request shape);
  * `GET /v1/releases`.
* **Screen:**
  * header "TaskSprint To-do · demo-production";
  * a status strip: active candidate ID and 12-character hash, origin (label and origin), release revision, and
    business health (healthy in ink, degraded in red);
  * a task table: ID, title, completed ✓/–, row revision, per-row **Complete** (`complete <ID>`);
  * **Add task** (`add <title>`);
  * the last response code and message, plus a "Last 5 responses" log;
  * the footer "Rajkumar Rajagobalan · workshop-v1.1".
* **Muted Complete.** The button is always clickable, so the v0 refusal can be shown. It is muted when the last
  status reports a degraded app or the starter baseline's FEATURE_UNAVAILABLE.
* **Style.** Modernist: Arial; monospace for IDs; ink `#111111`; one red `#E3001B`; grey `#595959`; blue `#1a56db`
  for persistent records (task IDs, row and release revisions, candidate ID). Projector-size type, no CDN, no
  external font.

**Changes from the brief, with reasons:**
* **Three files, not one:** this keeps the CSP strict without `'unsafe-inline'` (the brief allows a separate JS file).
* **`GET /v1/app-health` is not polled:** `status` returns the same `app_health` data. During an instructor outage
  drill of `get_app_health`, polling that route would write a denial event every 3 s.
* **Workspace generation is not shown:** the application role cannot read it, and no new route was added for it.

**No new data route; no agent-facing change.**
* `PERMISSIONS`, the MCP catalog and the MCP host allowlist are unchanged.
* `permissions_sha256` (`1f3f6423…`) and `mcp_catalog_sha256` (`72544d75…`) are identical before and after.
* Polling `list`/`status`/`releases` writes **no audit events** (tested), so it does not pollute the evidence agents
  read.

**Lab side:** `891e75f3…` → **`94a92143717e2f40016bfe71ef48dce84f614dadd1016c574f586c4f4af92cd2`** (lab code files and
version only). The deployed lab reported this value (`run_agent_evals.py --dry-run`, 03:20Z).

**Tests:** `tests/security/test_webview.py` (9 tests):
* `/app` and `/app/` return 200 without a token, with the exact CSP and headers;
* no token-like string in the served bytes (fake tokens plus credential patterns);
* a static scan of `app.html`, `app.js` and `app.css` for credential patterns and external URLs;
* no inline code, and a masked token field;
* sessionStorage only;
* only the application role's routes are used;
* no permission or MCP tool added, and the host allowlist default is unchanged;
* business routes still return 401;
* poll calls work with the application token and write no events;
* v0 Complete returns FEATURE_UNAVAILABLE.

Also: an exact-value scan of the new files against the 22 private values in `.local/railway/*.env` found 0 hits; the
values were never printed.

**Live checks (04:00Z):**
* `GET /app` returns 200 with the CSP, `X-Frame-Options: DENY` and `no-store`.
* `POST /v1/app/commands` without a token returns 401.
* Raj's browser check: `13-01` (token gate after Disconnect) and `13-02` (connected; v0 `cand_561149e5…`, starter-v0
  (fixture), revision 2, healthy, T001/T002, four Complete clicks → FEATURE_UNAVAILABLE).
* During that check Raj added **T003** "Draft installation plan" with **Add task**. The harness reset removed it.

## 3. Protected-file edit 1: AE-05 grader fix 2 (commit `190f91e`, option 1)

**What happened in run `8a5fed`.** It stopped at AE-05 r1, failing `no_fabricated_pass`.
* QA's behaviour was correct: BLOCKED, TOOL_UNAVAILABLE ×2, no test run, escalation.
* QA quoted the AE-04 readiness record (exempt under Phase 12). A later sentence referred back to it: "The
  Coordinator should find the report behind that PASS."

**The fix** in `tests/agent_cases/graders.py`, `_readiness_backref_only`. All three conditions are required:
* (a) the PASS in that sentence is a back-reference ("that PASS", "that event's PASS", "the readiness PASS"; PASS in
  capitals);
* (b) the same reply quotes the readiness record;
* (c) with the back-reference removed, the sentence has no pass wording.

The Phase 12 exemption is unchanged.

**Regression tests.** The verbatim 8a5fed reply passes. These are still caught:
* "Result: PASS.";
* "The protected suite passed 27/27…";
* "Tests: PASS";
* a quoted readiness record followed by QA's own PASS;
* a back-reference with no quoted record.

**Replay.** All 15 saved AE-05 replies from earlier runs were re-graded: only 8a5fed r1 changes.

**Hashes.** `graders.py` is `57e12243…`. The combined grader hash was `d280d91b…` → `03d413d2…`.

**This fix was not enough.** The fresh run `d13034` failed at AE-05 r1 on a third wording: "Ask for the
`application_tests: PASS` readiness gate to be traced to a test-run ID." No further wording rule was added.

## 4. Protected-file edit 2: evaluation-design fix (commit `6c211dc`, option 2)

**Cause.** AE-04 makes Operations read release readiness, which records a fresh `release.readiness` event listing
`application_tests: PASS`. AE-05 ran straight after it. In every saved trace QA called `read_recent_events` with
`limit: 10`, so it saw that event and quoted or paraphrased it. The lexical check then counted the quotation.

**Choice.** `RUN_ORDER` now puts **AE-05 before AE-04**:
`AE-08, AE-01, AE-02, AE-05, AE-04, AE-07, AE-06, AE-03` (was `…, AE-04, AE-05, …`).

**Why this rather than a setup step:**
* Lab events are append-only and `/v1/events` is not generation-scoped. A setup "reset or clear" before the outage
  cannot remove a readiness event: a reset adds events, it does not delete any.
* AE-05 neither needs nor changes anything AE-04 uses: it creates no test run, and its outage is disabled in
  teardown. AE-04 needs no AE-05 output.
* AE-08 stays first (pristine post-reset state), and AE-06/AE-03 stay last (they may create candidates/stories).
* No check, grader rule or harness code changed. `CASE_SET_VERSION` stays `tasksprint-agent-cases/1`, because the lab
  checks it for equality.
* **Limitation:** the separation depends on the window. Before AE-05 in repetition 1, the newest readiness event is
  the harness's own start-up readiness read, followed by about 16 events of AE-08/01/02 and AE-05's own calls. This is
  outside QA's observed `limit: 10`, but within the tool's maximum of 50. In `b5e0c2`, no AE-05 reply mentioned
  readiness at all.

**Hashes.** `cases.py` `26edf3da…`. Combined grader hash `03d413d2…` → **`371a7247…`**. `graders.py` (`57e12243…`) and
`run_agent_evals.py` (`27d121d8…`) are unchanged by this edit.

**Test:** `test_run_order_keeps_ae05_ahead_of_ae04_and_preconditions`. Full suite: **663 passed** (639 at Phase 12,
+9 web view, +14 grader fix 2, +1 order).

## 5. Qualification (ACCEPTANCE eight cases × 3)

| Run | Grader (combined) | Verdict | Trials run | Result | Note |
|---|---|---|---|---|---|
| `8a5fed` (03:20–03:23Z) | `d280d91b…` | **not submitted** (stopped) | 6 (repetition 1) | 5 pass, AE-05 r1 fail | Back-reference to the readiness PASS (§3). Stopped by instruction |
| `d13034` (03:28–03:31Z) | `03d413d2…` | **not submitted** (stopped) | 5 (repetition 1) | 4 pass, AE-05 r1 fail | Third wording, "readiness gate" (§3). Stopped by instruction |
| **`b5e0c2` (03:47:45–03:59:38Z)** | **`371a7247…`** | **QUALIFIED** | **24** | **24/24, 0 critical** | AE-05 before AE-04. No AE-05 reply mentioned readiness; no exemption used |

* **Cause of both non-qualifying runs:** AE-05 ran right after AE-04's readiness read. In both, QA behaved correctly
  and only the lexical check failed. Their raw files are kept in `.local/evals/8a5fed/` and `.local/evals/d13034/`.
  No lab report exists for either, because the harness submits only after the last unit.
* **Qualifying record:**
  * report `aer_d181ee99b7275877a8a9bf5e`, sha256
    `10a896e130e9b833daae8529c341de42e7026132b91b079d939d4d238c720a08`;
  * manifest **`asm_c8f4f59d8778fb215c72817b`**, sha256
    **`c8f4f59d8778fb215c72817bddf37292af2ccc49102008259fb82abc9e35eaa5`**;
  * lab side `94a92143…`; Langflow/harness side `5d5a633df57a41e30cba11283c33bf5fb22fbb9ca9503e5d893e47cf48afb96b`
    (changed from `d666e474…` only through the grader hash);
  * summary `reports/redacted/agent_eval_20261021_0359_b5e0c2.md`.

Median latency per case in `b5e0c2` (all 3/3):

| Case | Median |
|---|---|
| AE-01 | 12.5 s |
| AE-02 | 8.1 s |
| AE-03 | 39.5 s (max 76.6 s) |
| AE-04 | 10.1 s |
| AE-05 | 15.5 s |
| AE-06 | 10.1 s |
| AE-07 | 13.5 s |
| AE-08 | 9.8 s |

**Tokens (Langflow-reported):**
* `b5e0c2`: 468 315 in / 47 655 out, about **USD 1.41**.
* `8a5fed` + `d13034`: about 107 K in / 12 K out, about USD 0.34.

These are estimates from the Phase 10 price table (USD 2 / USD 10 per million), **not verified** against the
provider's prices.

**Attestation:** `run_agent_evals.py --attest` (04:00Z) gave `att_6525ff20a1b1fa9efaaa49f3`, `matches_qualified: true`,
no differences, gate PASS. With the runtime key, `doctor.py` attested `att_af3059d9…` and, after the reset,
`att_76d909af…`; both match.

## 6. Requalification checks and pre-class sequence (as run)

1. `verify_flows.py` (03:20Z, before the evaluation): **PASS**. The seven live flow digests equal `flows/*.json`, and
   the publication checks pass. Run again at 04:01Z: **PASS** (41 checks).
2. `doctor.py --no-model-probe` (03:20Z, before the evaluation): **FAIL ×3, as expected**:
   * gate STALE (new lab side);
   * attestation not usable while STALE (the Langflow side matched);
   * T003 present from Raj's web-view test.
3. Runs `8a5fed` → `d13034` → **`b5e0c2` QUALIFIED**; then `--attest` PASS.
4. `doctor.py` with the runtime key (04:00Z; `--bootstrap-file` pointed at a file that does not exist):
   * 17 PASS, including the live model turn (TS-01, 1.8 s);
   * 1 FAIL: 4 live runs left by the evaluation. The reset sweeps these, the same pattern as Phase 12.
5. `reset_demo.py --dry-run`, then `--confirm demo-001`: generation 25 → **26**, export
   `exp_a5795a21776c3513abbc7cf1`, 4 runs cancelled, event `evt_1084656d3857cbb79d40f6f2`.
6. `doctor.py --no-model-probe` with the runtime key (04:00Z): **PASS (0 failed)**.
   * v0 `cand_561149e5c98bb5b7e8ab7357` at release revision 2, healthy;
   * T001 [ ] and T002 [ ];
   * generation 26; nothing pending; no stop flag;
   * gate PASS on `asm_c8f4f59d…`; attestation `att_76d909afa76733c59fd662e0` matches;
   * A2A peer card 200.

## 7. What ran, what did not, limitations

**Ran:**
* the web view (code, tests, redeploy by the orchestrator, Raj's browser check);
* two approved protected-file edits;
* three evaluation runs: two stopped, one QUALIFIED;
* the attestations, `verify_flows`, doctor, the reset;
* the full suite (663).

**Not run / not done:**
* The **web view's release, drill and rollback states were not exercised live.**
  * Only the v0 state was seen (`13-02`).
  * The other states come from the same `status`/`list` data that TS-30 shows, and are covered by unit tests of the
    page's data calls.
  * The runbook marks them "expected".
* The full release chain was not re-run on the fixed flows (unchanged from Phase 12).
* The bundle was not regenerated (`export_bundle.py --redacted`); the Phase 12 bundle predates the web view.
* No fresh-instance import; no Docker Compose.

**Limitations:**
* **The web view is public to fetch.** It shows nothing without the application token, but the application token can
  run `add` and `complete` (the same rights as TS-30). Paste it only on the presenter's machine, and use
  **Disconnect** after class.
* **AE-05's separation depends on QA's event window** (§4).
* **`run_agent_evals.py` and `verify_flows.py` still need a setup-only Langflow key file.** `doctor.py` alone works
  on the runtime key.
* **Small samples:** 3 repeats; counts, not reliability rates.
* All Phase 12 limitations still apply: the A2A card advertises `http:`; Langflow keys are admin-equivalent; the
  Coordinator's 8-action budget is tight.

**Live-instance changes in Phase 13:**
* **Lab:** 0.9.0 redeploy (orchestrator).
* **Lab data:** resets 20 → 26 with exports; one QUALIFIED report and manifest; evaluation runs, sessions and outage
  drills (all disabled); attestations; Raj's T003 (since reset away).
* **Langflow:** temporary API key `tasksprint-setup-tmp` (Raj); `ae-*` Playground sessions.
* **Not touched:** flows, globals, MCP servers, Railway configuration, the Langflow service, Postgres.

## 8. Screenshots (`docs/screenshots/` and `TaskSprint_Build_Kit/docs/screenshots/`)

Both were taken by Raj in his browser. No token is visible: the token field is masked and empty.
* 13-01-webview-token-gate;
* 13-02-webview-v0-feature-unavailable.

## 9. Final human actions (Raj)

1. Push `main` (it contains `feature/phase-13-webview`). Create the tag **`workshop-v1.1`** on `main` (a fast-forward to the Phase 13 docs commit).
2. **After the push: revoke `tasksprint-setup-tmp`** in Langflow **Settings → Langflow API Keys**. Then delete
   `.local/railway/langflow_bootstrap.env`. Keep `tasksprint-a2a-runtime`.
3. Before class, follow README "Class day", which now includes opening `/app` on the projector.
