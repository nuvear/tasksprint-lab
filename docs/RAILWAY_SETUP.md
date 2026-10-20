# Railway setup for the two TaskSprint services (Phase 05, owner steps)

**Status:** prepared on 20 Oct 2026 from the repository at `main`. Nothing here has been
run against Railway yet: the agent could not build images (no Docker on the build VM) and
does not deploy. Raj performs every step below. Railway UI labels are taken from Railway's
documentation (links at the end) and must be checked on screen; record any difference in
`docs/OBSERVED_UI.md`.

**Do not touch** the existing `langflow-railway` service, its `/app/langflow` volume, the
`Postgres` service, their variables, or `nuvear/langflow-railway`. Both new services live
in the same Railway project **and environment** as Langflow (private networking only
connects services in the same project environment).

## 0. Before you start (on your Mac, privately)

1. The GitHub repository `nuvear/tasksprint-lab` exists and `main` contains this commit
   (Railway deploys from `main`). Note: every push to `main` redeploys both services unless
   you set Watch Paths (optional, step 5).
2. Create a **separate credential set for Railway** (recommended; keeps the deployed lab's
   tokens independent of the ones used by local tests):

   ```bash
   uv run python scripts/local_init.py --dir .local/railway --db-path /data/tasksprint.sqlite3
   ```

   It writes three 0600 files and prints only names, never values:

   | File | Contents (names only) | Goes to |
   |---|---|---|
   | `.local/railway/lab.env` | `TASKSPRINT_DB_PATH`, `TASKSPRINT_DEMO_ENABLED`, `TASKSPRINT_ALLOWED_WORKSPACES`, `TS_RUNNER_TOKEN`, `TS_COORD_TOKEN_HASH`, `TS_PO_TOKEN_HASH`, `TS_DEV_TOKEN_HASH`, `TS_QA_TOKEN_HASH`, `TS_OPS_TOKEN_HASH`, `TS_APP_TOKEN_HASH`, `TS_APPROVER_TOKEN_HASH`, `TS_INSTRUCTOR_TOKEN_HASH`, `TS_EVALUATOR_TOKEN_HASH` | Railway **lab** service variables |
   | `.local/railway/runner.env` | `TS_RUNNER_TOKEN` only | Railway **runner** service variables |
   | `.local/railway/role_tokens.env` | the nine plaintext role tokens `TS_*_TOKEN` | **Not Railway.** Langflow Credential variables (Phase 06) and your private check scripts |

   To copy values: open the file yourself in a local editor (for example
   `open -e .local/railway/lab.env`), copy, paste into Railway's variable editor, close the
   file. Do not paste values into chat, a terminal command line, a screenshot, a commit or
   a Langflow prompt. If you would rather reuse the existing `.local/lab.env` set, use its
   hash lines but **not** its `TASKSPRINT_DB_PATH` (that is a local path).

## 1. Service `tasksprint-runner` (private, no domain)

1. Project **Langflow** → **New** (or **+ Create**) → **GitHub Repo** → `nuvear/tasksprint-lab`.
   Root directory `/` (repository root; both Dockerfiles use it as build context).
2. Rename the service to exactly **`tasksprint-runner`** (Settings → service name). The
   private DNS name is derived from it: `tasksprint-runner.railway.internal`.
3. **Variables** → Raw Editor, add:
   * `RAILWAY_DOCKERFILE_PATH` = `Dockerfile.runner`
   * `PORT` = `8001`
   * `TS_RUNNER_TOKEN` = (paste from `.local/railway/runner.env`)

   Nothing else. Do not link shared variables to this service. The runner refuses to start
   if it sees `TASKSPRINT_DB_PATH`, `TASKSPRINT_ENV_FILE`, `TASKSPRINT_API_BASE`, any other
   `TS_*` name, `LANGFLOW_*`, `*_API_KEY`, `DATABASE_URL`, `PGPASSWORD` or a Railway token.
   (Railway's own injected `RAILWAY_*` variables and `PORT` are fine.)
4. **Settings → Networking**: do **not** generate a public domain. Note the private
   address shown under Private Networking (expected `tasksprint-runner.railway.internal`).
5. **Settings → Deploy**: Healthcheck Path `/healthz`; Replicas `1`. No volume.
   Optional **Settings → Source → Watch Paths**: `services/runner/**`, `Dockerfile.runner`,
   `pyproject.toml`, `uv.lock`, `.python-version`.
6. **Deploy** (apply the staged changes). If a build started before the variables were set,
   it will have used the wrong builder; redeploy after step 3.
7. Deploy logs should show `runner start: bind=:: port=8001 uid=10001 workers=1`. `::` is
   deliberately dual-stack: Railway environments created before 16 Oct 2025 resolve
   `*.railway.internal` to IPv6 only, newer ones to IPv4 and IPv6.

## 2. Service `tasksprint-lab` (public HTTPS, volume `/data`)

1. **New** → **GitHub Repo** → `nuvear/tasksprint-lab`, root `/`. Rename to **`tasksprint-lab`**.
2. **Volume**: add a **new** volume to `tasksprint-lab` with mount path **`/data`**
   (command palette or right-click on the canvas → Volume; choose this service). Never attach
   the existing `/app/langflow` volume.
3. **Variables** → Raw Editor. Paste the whole content of `.local/railway/lab.env` (it
   already holds `TASKSPRINT_DB_PATH=/data/tasksprint.sqlite3`, `TASKSPRINT_DEMO_ENABLED=true`,
   `TASKSPRINT_ALLOWED_WORKSPACES`, `TS_RUNNER_TOKEN` and the nine hashes), then add:
   * `RAILWAY_DOCKERFILE_PATH` = `Dockerfile.lab`
   * `PORT` = `8000`
   * `RAILWAY_RUN_UID` = `0` (see "Why RAILWAY_RUN_UID=0" below)
   * `TASKSPRINT_RUNNER_URL` = `http://tasksprint-runner.railway.internal:8001`
     (equivalently, with Railway reference variables:
     `http://${{tasksprint-runner.RAILWAY_PRIVATE_DOMAIN}}:${{tasksprint-runner.PORT}}`)
   * `TASKSPRINT_MCP_ALLOWED_HOSTS` = the lab's domain from step 5, host only, no scheme,
     no path (e.g. `tasksprint-lab-production.up.railway.app`). Set it after step 5.

   Optionally, instead of pasting `TS_RUNNER_TOKEN` twice, set it on the lab as
   `${{tasksprint-runner.TS_RUNNER_TOKEN}}`.
4. **Settings → Deploy**: Healthcheck Path `/healthz`; Replicas **1** (one SQLite writer;
   the image always starts one worker). Optional Watch Paths: `services/lab/**`,
   `knowledge/**`, `skills/**`, `instructor/fixtures/**`, `Dockerfile.lab`, `pyproject.toml`,
   `uv.lock`, `.python-version`.
5. **Settings → Networking → Public Networking → Generate Domain**. If asked for a target
   port, enter **8000**. Copy the generated host into `TASKSPRINT_MCP_ALLOWED_HOSTS` (step 3).
6. **Deploy**. Variable changes need an explicit Deploy/Redeploy.
7. Deploy logs should show one line like
   `lab start: bind=0.0.0.0:8000 uid=10002 privileges=started as root: gave the database
   directory to uid 10002, dropped privileges workers=1 schema_version=2
   migrations_applied_now=[1, 2] ... mcp_allowed_hosts=['<your domain>'] runner_configured=True
   roles_configured=9 demo_enabled=True`. A warning containing `421` means
   `TASKSPRINT_MCP_ALLOWED_HOSTS` still lists only loopback hosts.

**Why `RAILWAY_RUN_UID=0`.** Railway mounts volumes owned by root and exposes only the mount
path and `RAILWAY_RUN_UID` as controls. The image's default user is uid 10002 (non-root), which
could not write `/data`. With `RAILWAY_RUN_UID=0` the container starts as root only long enough
for `services/lab/serve.py` to chown `/data` and the lab's own database files, then it drops
groups, gid and uid to 10002 irreversibly (it verifies that root cannot be regained) **before**
opening the database or the port. Without it the lab refuses to start with a message naming
this variable. The runner never needs it.

## 3. Variable reference (names and meaning; never put values in documents)

| Variable | Service | Secret | Meaning |
|---|---|---|---|
| `RAILWAY_DOCKERFILE_PATH` | both | no | `Dockerfile.lab` / `Dockerfile.runner`; selects the Dockerfile in the repo root |
| `PORT` | both | no | Listening port: lab `8000`, runner `8001`. Railway would inject one; set it so the private URL and target port are fixed |
| `TS_RUNNER_TOKEN` | both (same value) | **yes** | Transport-only lab → runner credential (≥ 32 chars); authorizes evaluation requests and nothing else |
| `RAILWAY_RUN_UID` | lab only | no | `0`: start as root to fix volume ownership; the entrypoint drops to uid 10002 before serving |
| `TASKSPRINT_DB_PATH` | lab | no | `/data/tasksprint.sqlite3` on the new volume |
| `TASKSPRINT_DEMO_ENABLED` | lab | no | `true` |
| `TASKSPRINT_ALLOWED_WORKSPACES` | lab | no | Designated synthetic workspaces the instructor may seed: `demo-001` |
| `TASKSPRINT_RUNNER_URL` | lab | no | `http://tasksprint-runner.railway.internal:8001` — private DNS `<service-name>.railway.internal` plus the runner's `PORT`; plain http on the private network, no path |
| `TASKSPRINT_MCP_ALLOWED_HOSTS` | lab | no | Host header allowlist for `/mcp` (DNS-rebinding guard): the lab's public domain, comma-separated `host[:port\|:*]`. Replaces the loopback default |
| `TS_COORD_TOKEN_HASH` | lab | private | SHA-256 of the coordinator token |
| `TS_PO_TOKEN_HASH` | lab | private | SHA-256 of the product-owner token |
| `TS_DEV_TOKEN_HASH` | lab | private | SHA-256 of the developer token |
| `TS_QA_TOKEN_HASH` | lab | private | SHA-256 of the QA token |
| `TS_OPS_TOKEN_HASH` | lab | private | SHA-256 of the operations token |
| `TS_APP_TOKEN_HASH` | lab | private | SHA-256 of the application token |
| `TS_APPROVER_TOKEN_HASH` | lab | private | SHA-256 of the human-approver token |
| `TS_INSTRUCTOR_TOKEN_HASH` | lab | private | SHA-256 of the instructor token |
| `TS_EVALUATOR_TOKEN_HASH` | lab | private | SHA-256 of the evaluator token |
| `TASKSPRINT_MCP_TOOL_TIMEOUT_S` | lab, optional | no | Per-tool deadline, default 20 s |
| `TASKSPRINT_SQLITE_JOURNAL_MODE` | lab, optional | no | Default `TRUNCATE`; leave unset |
| `TASKSPRINT_MAX_BODY_BYTES` | lab, optional | no | Default 65536 |
| `TASKSPRINT_BIND_HOST` | both, optional | no | Leave unset (lab `0.0.0.0`, runner `::`) |

Workers: always **1** (fixed in the image's entrypoint; not a variable). Replicas: **1**.

**Never set on either service:** plaintext role tokens (`TS_COORD_TOKEN` …), `TS_A2A_API_KEY`,
`TASKSPRINT_ENV_FILE` (no env file exists in the image), `TASKSPRINT_FIXTURES_DIR` (set by the
image), `TASKSPRINT_API_BASE` (that is a Langflow global, Phase 06), `LANGFLOW_*`, the Langflow
admin password, `LANGFLOW_SECRET_KEY` or the Postgres URL.

Railway injects (no action): `RAILWAY_PRIVATE_DOMAIN`, `RAILWAY_PUBLIC_DOMAIN`,
`RAILWAY_VOLUME_MOUNT_PATH`, `RAILWAY_ENVIRONMENT…` and similar.

## 4. Post-deploy checks (Build Guide 05.5), from your Mac

Replace `<lab>` with the generated host. The scripts read tokens from the private file and
never print them.

1. Liveness without a token (expect `200` and `{"status":"ok","service":"tasksprint-lab"}`):
   `curl -s -i https://<lab>/healthz`
2. Business route without a token (expect `401`):
   `curl -s -o /dev/null -w '%{http_code}\n' -H 'X-TaskSprint-Workspace: demo-001' https://<lab>/v1/state`
3. Seed the designated demo workspace once (instructor token; idempotent, `ALREADY_SEEDED`
   on repeat):
   `uv run python scripts/seed_demo.py --workspace demo-001 --apply --lab-url https://<lab> --tokens-file .local/railway/role_tokens.env`
4. Full check and persistence snapshot (expect every line `PASS`, then `SUMMARY: … 0 fail, 0 skip`):
   `uv run python scripts/check_stack.py --target railway --base-url https://<lab> --env-file .local/railway/role_tokens.env --snapshot save`
   It checks `/healthz`, 401 without/with an invalid token on REST and `/mcp`, MCP initialize
   accepted for this host (not 421), an authenticated coordinator state read, application
   `status`, and `complete T999` through the private runner (on starter v0 this answers
   `FEATURE_UNAVAILABLE` and changes nothing). It saves non-secret identifiers (newest event
   IDs, task list, active release hash) to `.local/railway/railway_snapshot.json` (0600).
5. Optional real MCP client per role:
   `uv run python scripts/mcp_smoke.py --lab-url https://<lab> --tokens-file .local/railway/role_tokens.env`
   (expect `RESULT PASS`; 7/2/6/5/12/2 tools for coordinator/PO/developer/QA/operations/app).
6. Persistence: redeploy **only `tasksprint-lab`** (its latest deployment → Redeploy). Railway
   never runs two deployments of a volume-backed service at once, so expect a brief outage.
   The new deploy log must show `migrations_applied_now=[]` and `schema_version=2`. Then:
   `uv run python scripts/check_stack.py --target railway --base-url https://<lab> --env-file .local/railway/role_tokens.env --snapshot verify`
   Expect `PASS volume persistence after redeploy: saved newest event present; 2 tasks unchanged; active release unchanged`.
   Do not restart Langflow or Postgres for this.
7. Runner privacy: `tasksprint-runner` → Settings → Networking shows no public domain
   (the script prints this as a NOTE; it cannot be tested from outside).
8. Langflow and Postgres unchanged: no new deployment appears on either service; Langflow
   `/login` still loads.

Record the outputs (they contain no secrets) in `docs/PHASE05_REPORT.md` with the date.

## 5. Langflow side (Phase 06, after GATE 05; for reference)

Langflow → profile **Settings → MCP Servers → Add MCP Server**, one server per agent role
(same URL, different token), so each agent's MCP Tools component sees only its role's tools:

| Field | Value |
|---|---|
| Name | e.g. `tasksprint-coordinator`, `tasksprint-product-owner`, `tasksprint-developer`, `tasksprint-qa`, `tasksprint-operations` |
| Transport | Streamable HTTP (the dialog's HTTP option) |
| URL | `https://<lab>/mcp` (exactly `/mcp`, no trailing slash) |
| Header | `Authorization` = `Bearer ` + the role's Credential global variable (`TS_COORD_TOKEN`, `TS_PO_TOKEN`, `TS_DEV_TOKEN`, `TS_QA_TOKEN`, `TS_OPS_TOKEN`) |
| Header | `X-TaskSprint-Workspace` = `demo-001` |

How the 1.12.5 dialog binds a header to a Credential variable is **not yet observed**
(PHASE04_REPORT). Observe it first and record it in `OBSERVED_UI.md`; never type a literal
token into a header field that is exported with flows. Create `TASKSPRINT_API_BASE`
(Generic) = `https://<lab>` as part of Phase 06.1. Instructor, approver and evaluator tokens
are refused at `/mcp` (403) by design.

## Sources (read 20 Oct 2026)

* Railway volumes: mounted as root; set `RAILWAY_RUN_UID=0` for non-root images; mounted at
  container start, not during build or pre-deploy — https://docs.railway.com/volumes.md and
  https://station.railway.com/questions/supported-isolation-for-one-time-sqlite-204de90e
* Private networking: `<service-name>.railway.internal`; environments created after
  16 Oct 2025 resolve to IPv4 and IPv6, legacy ones to IPv6 only —
  https://docs.railway.com/networking/private-networking/how-it-works.md
* Healthchecks: path set in service settings, used only at deploy start, `PORT` injected,
  host `healthcheck.railway.app`; volume-backed services cannot overlap deployments —
  https://docs.railway.com/deployments/healthchecks.md
* Dockerfile path variable `RAILWAY_DOCKERFILE_PATH` — https://docs.railway.com/builds/dockerfiles.md
* Generate Domain under Settings → Networking → Public Networking —
  https://docs.railway.com/networking/public-networking.md
* Dockerfile `VOLUME` is refused by Railway's builder ("The VOLUME keyword is banned in
  Dockerfiles. Use Railway volumes instead.") — https://station.railway.com/questions/build-from-dockerfile-error-the-volume-8a90b885
