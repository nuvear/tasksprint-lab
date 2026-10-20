# Phase 05 report: Railway deployment

## Post-deploy checks, 20 Oct 2026

**Scope:** Build Guide 05.5, `docs/RAILWAY_SETUP.md` §4 steps 1–5, plus a Langflow
reachability check. Run from the owner's Linux aarch64 VM between 15:51 and 15:52 GMT+8
(07:51–07:52 UTC). **Result: all checks PASS.** Step 6 (persistence after redeploy) is pending.

**Not touched:** Railway configuration, Langflow, Langflow Postgres, `nuvear/langflow-railway`.
Nothing was redeployed or committed. Token values were read only by the scripts, which never
print them. No value from `.local/railway/*.env` appears below.

### Railway facts

| Item | Value |
|---|---|
| Repository | `nuvear/tasksprint-lab`, branch `main`, HEAD `237de27` |
| Lab | `tasksprint-lab`, public URL `https://tasksprint-lab-production.up.railway.app` |
| Lab deploy | 15:48 GMT+8, 20 Oct 2026. Start log: `uid=10002 … migrations_applied_now=[1, 2] … mcp_allowed_hosts=['tasksprint-lab-production.up.railway.app'] runner_configured=True roles_configured=9 demo_enabled=True` |
| Runner | `tasksprint-runner`, private only, `tasksprint-runner.railway.internal:8001`, online |
| Credential set | `.local/railway/role_tokens.env`, `.local/railway/lab.env`, `.local/railway/runner.env` (0600, git-ignored) |
| Edge | `server: railway-hikari`, `x-railway-edge: sin1` |
| Toolchain | `/tmp/ts/env.sh`: uv 0.12.13, CPython 3.12.14 (`/tmp/ts/uvpy`), venv `/tmp/ts/venv-mnt` (httpx 0.28.1, mcp); scripts run with `uv run --frozen --no-dev` |

### 1. Liveness without a token: PASS

```text
$ curl -s -i https://tasksprint-lab-production.up.railway.app/healthz
HTTP/2 200
content-type: application/json
date: Tue, 20 Oct 2026 07:51:40 GMT
server: railway-hikari
x-railway-request-id: 8dSgGyzpQPC1mxOZAax-fw
x-request-id: req_7c5ca50c8694b09f51853345
content-length: 42
x-hikari-trace: sin1.98a6
x-railway-edge: sin1

{"status":"ok","service":"tasksprint-lab"}
```

### 2. Business route without a token: PASS

```text
$ curl -s -o /dev/null -w '%{http_code}\n' -H 'X-TaskSprint-Workspace: demo-001' https://tasksprint-lab-production.up.railway.app/v1/state
401
```

### 3. Seed demo-001: PASS

Dry run first (no mutation):

```text
$ uv run python scripts/seed_demo.py --workspace demo-001 --dry-run --lab-url https://tasksprint-lab-production.up.railway.app --tokens-file .local/railway/role_tokens.env
HTTP 200
{
  "action": "reset_preview",
  "workspace_id": "demo-001",
  "exists": false,
  "mutation": "none"
}
```

Apply:

```text
$ uv run python scripts/seed_demo.py --workspace demo-001 --apply --lab-url https://tasksprint-lab-production.up.railway.app --tokens-file .local/railway/role_tokens.env
HTTP 200
{
  "action": "seed",
  "workspace_id": "demo-001",
  "generation": 1,
  "starter": {
    "candidate_id": "cand_561149e5c98bb5b7e8ab7357",
    "sha256": "561149e5c98bb5b7e8ab73579dee2bbd8f680010173ad5d8d4f5dcf89fac1e9b",
    "size_bytes": 186,
    "base_sha256": null,
    "author_role": "instructor",
    "origin": "fixture",
    "label": "starter-v0",
    "created_at": "2026-10-20T07:51:53Z",
    "provenance": {
      "origin": "fixture",
      "author_role": "instructor",
      "base_sha256": null,
      "sha256_verified": true
    },
    "fixture_label": "FIXTURE: known healthy starter baseline"
  },
  "release": {
    "operation": "seed",
    "candidate_id": "cand_561149e5c98bb5b7e8ab7357",
    "sha256": "561149e5c98bb5b7e8ab73579dee2bbd8f680010173ad5d8d4f5dcf89fac1e9b",
    "release_revision": 0,
    "request_id": "req_27ddef4440aa5d13e90e1a2b",
    "baseline": true
  },
  "tasks_seeded": [
    "T001",
    "T002"
  ],
  "sprint_id": "SPRINT-1"
}
```

Repeat (idempotency, exit 0):

```text
HTTP 409
{
  "error": {
    "code": "ALREADY_SEEDED",
    "message": "workspace already exists; use the confirmed reset (later phase)",
    "request_id": "req_1729e0878de3a19abe566b9c"
  }
}
```

### 4. Full stack check and persistence snapshot: PASS

```text
$ uv run python scripts/check_stack.py --target railway --base-url https://tasksprint-lab-production.up.railway.app --env-file .local/railway/role_tokens.env --snapshot save
PASS lab liveness without a token: GET /healthz -> 200
PASS business route without a token refused: GET /v1/state -> 401
PASS write route without a token refused: POST /v1/app/commands -> 401
PASS invalid token refused: GET /v1/state -> 401
PASS /mcp without a token refused: -> 401
PASS MCP initialize accepted for this host: -> 200
PASS authenticated state read (coordinator): -> 200
PASS application status: -> 200, business health healthy
PASS lab -> runner path: -> 200, code FEATURE_UNAVAILABLE, runner tasksprint-runner/0.3.0, ops 8
PASS persistence snapshot saved: railway_snapshot.json: 3 event IDs, 2 tasks (no secrets). Now redeploy the lab and run --snapshot verify
NOTE runner exposure: not testable from outside; confirm tasksprint-runner has no public domain in the Railway UI (Settings -> Networking)
SUMMARY: 10 pass, 0 fail, 0 skip
exit=0
```

Snapshot `.local/railway/railway_snapshot.json` (mode 0600, 437 bytes, git-ignored, no secrets):

```json
{
  "active_sha256": "561149e5c98bb5b7e8ab73579dee2bbd8f680010173ad5d8d4f5dcf89fac1e9b",
  "event_ids": [
    "evt_024d0a3f64f3d8aba1ede4da",
    "evt_83ce0949c436b21fae91ec20",
    "evt_9affe5bda62b96193c2c589f"
  ],
  "tasks": [
    {"completed": false, "id": "T001", "title": "Draft workshop agenda"},
    {"completed": false, "id": "T002", "title": "Book the sprint review room"}
  ]
}
```

### 5. MCP smoke test, real SDK client per role: PASS

```text
$ uv run python scripts/mcp_smoke.py --lab-url https://tasksprint-lab-production.up.railway.app --tokens-file .local/railway/role_tokens.env
PASS no token -> HTTP 401
PASS human_approver token refused at /mcp -> HTTP 403
PASS instructor token refused at /mcp -> HTTP 403
PASS evaluator token refused at /mcp -> HTTP 403
PASS coordinator protocol 2025-11-25: 7 tools: get_sprint_state, record_story, transition_story, read_preferences, save_preference, read_test_report, read_recent_events
PASS product_owner protocol 2025-11-25: 2 tools: get_sprint_state, search_approved_knowledge
PASS developer protocol 2025-11-25: 6 tools: get_sprint_state, search_approved_knowledge, list_skills, load_skill, read_candidate, submit_candidate
PASS qa protocol 2025-11-25: 5 tools: get_sprint_state, read_candidate, run_candidate_tests, read_test_report, read_recent_events
PASS operations protocol 2025-11-25: 12 tools: get_sprint_state, list_skills, load_skill, read_candidate, read_test_report, get_release_readiness, create_release_plan, read_release_plan, execute_approved_plan, get_release_status, get_app_health, read_recent_events
PASS application protocol 2025-11-25: 2 tools: get_release_status, get_app_health
RESULT PASS
exit=0
```

### Langflow reachable (no changes made): PASS

```text
$ curl -s -o /dev/null -w '%{http_code}\n' https://langflow-railway-production-f493.up.railway.app/health_check
200
```

### Summary

| # | Check | Result | Key output |
|---|---|---|---|
| 1 | `/healthz` without a token | PASS | `HTTP/2 200`, `{"status":"ok","service":"tasksprint-lab"}` |
| 2 | `/v1/state` without a token | PASS | `401` |
| 3 | Seed demo-001 | PASS | starter `561149e5…`, `tasks_seeded` T001, T002; repeat gives `409 ALREADY_SEEDED` |
| 4 | `check_stack.py --target railway --snapshot save` | PASS | `SUMMARY: 10 pass, 0 fail, 0 skip`; lab -> runner `FEATURE_UNAVAILABLE`, `tasksprint-runner/0.3.0` |
| 5 | `mcp_smoke.py` | PASS | `RESULT PASS`; 7/2/6/5/12/2 tools |
| 6 | Langflow `/health_check` | PASS | `200` |

## Persistence after redeploy (step 6) — 20 Oct 2026, 15:53–15:55 GMT+8

Redeployed **only** `tasksprint-lab` (Deployments → ⋮ → Redeploy; previous deployment `96e72b80` REMOVED, new `d630c208` ACTIVE). New deploy log (screenshot `05-08-lab-redeploy-log-persistence.jpg`):

```
lab start: bind=0.0.0.0:8000 uid=10002 privileges=started as root: gave the database directory to uid 10002, dropped privileges workers=1 schema_version=2 migrations_applied_now=[] journal_mode=TRUNCATE mcp_allowed_hosts=['tasksprint-lab-production.up.railway.app'] runner_configured=True roles_configured=9 demo_enabled=True
GET /healthz HTTP/1.1" 200
```

`check_stack.py --target railway ... --snapshot verify`:

```
PASS volume persistence after redeploy: saved newest event present; 2 tasks unchanged; active release unchanged
SUMMARY: 10 pass, 0 fail, 0 skip
```

Steps 7–8: `tasksprint-runner` is listed as "Unexposed service" (no public domain; screenshots `05-02`, `05-06`). `langflow-railway` and `Postgres` show no new deployment; Langflow `/health_check` → 200.

**GATE 05: PASSED.** Railway facts: project Langflow / environment production; services `tasksprint-runner` (private, port 8001, uid 10001) and `tasksprint-lab` (https://tasksprint-lab-production.up.railway.app, port 8000, uid 10002, volume `tasksprint-lab-volume` at `/data`). Both images built on the first attempt. Screenshots `05-01`…`05-08` in `TaskSprint_Build_Kit/docs/screenshots/`.
