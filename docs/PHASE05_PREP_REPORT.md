# Phase 05 report (build side only): Railway preparation

**Date:** 20 October 2026. **Scope:** Build Guide 05.2 and the build-side parts of 05.5,
on the owner's Linux aarch64 VM. **Status:** PREPARED; **BLOCKED: image build and
deployment pending Raj** (05.3, 05.4 and the live 05.5 checks are owner steps).
**Not touched:** Langflow, Railway, Postgres, `nuvear/langflow-railway`, the owner's
`.local/` files and demo database (only variable *names* in `.local/lab.env` were listed).
No remote was added; nothing was pushed or deployed. No image was built: Docker is not
installed on this VM.

## Repository

| Item | Value |
|---|---|
| Branch | `feature/phase-04-mcp`; `main` fast-forwarded to it (no merge commit, no squash) |
| Commits | `541d12f` owner decisions (skill 1.1.0, Developer prompt); `1c671bb` entrypoints, Dockerfiles, migration lock, railway checks, RAILWAY_SETUP; then this report and BUILD_STATUS |
| Toolchain | as Phases 02–04 (`/tmp/ts/env.sh`: uv 0.12.13, CPython 3.12.14, venv under `/tmp/ts`) |
| Dependencies | unchanged; `uv lock --check --offline` → `Resolved 40 packages`, exit 0 |

## Owner decisions applied

1. **Phase 05 Railway services approved** — prepared here; Raj creates them (`docs/RAILWAY_SETUP.md`).
2. **`read_test_report` stays per A8** (qa, operations, coordinator). `prompts/developer.md`
   contradicted this ("read the immutable report"); minimal edit: *"When the Coordinator
   relays a QA failure (the failing assertions and observed data from the immutable report),
   read the candidate it tested. You cannot read test reports yourself."*
   `prompts/coordinator.md` does **not** contradict A8 and is unchanged. It does not say
   "relay" explicitly; the relay follows from QA's `qa_report` (failed criteria, evidence)
   plus the Coordinator's `ask_developer … one repair`. Optional one-sentence addition for
   Raj to consider (not applied): *"When QA reports a failure, read the report with
   read_test_report and pass its test-run ID, failing assertions and observed data to
   ask_developer."* Skill step 7 ("When an immutable QA report identifies a defect, inspect
   the failed assertion…") does not require the Developer to read the report and is unchanged.
3. **`implement-todo-change` 1.1.0** with the PHASE04_REPORT grammar text in step 4 and
   "a validator rejection you cannot fix within this grammar" in *Stop and escalate*.
   The lab enforces bumps: a database that recorded 1.0.0 (the owner's demo DB, and later any
   volume seeded before the bump) appends 1.1.0 and keeps the 1.0.0 row; 1.0.0 is no longer
   served because the file now carries 1.1.0. Verified by a new unit test and a real lab start
   (uvicorn, temporary credentials) against a database built from the previous commit's
   skills: `healthz 200`; skills table `[('implement-todo-change','1.0.0'),
   ('implement-todo-change','1.1.0'),('release-and-recover','1.0.0')]`.
   `SHA256SUMS.txt` is the kit-import manifest and was **not** updated (it already differs for
   files edited in earlier phases); the new hashes are reported by `GET /v1/skills`.

## Files created or changed

```text
services/lab/serve.py        lab entrypoint: $PORT, bind host, privilege drop, migrate once, redacted logs
services/runner/serve.py     runner entrypoint: $PORT, dual-stack ::, redacted logs (imports nothing from the lab)
services/lab/store.py        migrate(): one BEGIN IMMEDIATE transaction = cross-process migration lock
Dockerfile.lab, Dockerfile.runner, .dockerignore (new)
scripts/check_stack.py       --target railway, --base-url/--env-file, --snapshot save|verify
scripts/seed_demo.py         --lab-url (HTTPS instructor seed of a deployed lab)
docs/RAILWAY_SETUP.md (new), docs/BUILD_STATUS.md, docs/CANDIDATE_GRAMMAR.md (status line), this file
skills/implement-todo-change/SKILL.md (1.1.0), prompts/developer.md
.env.example, compose.yaml   comments only (PORT, TASKSPRINT_BIND_HOST, RAILWAY_RUN_UID)
tests/unit/test_serve.py, tests/unit/test_deploy_files.py,
tests/integration/test_serve_railway_mode.py (new); tests/unit/test_skills.py,
tests/security/test_runner_isolation.py (entrypoint imports allowlisted separately)
```

## Decisions and findings (Railway specifics)

1. **Volumes are mounted owned by root** on Railway; the only controls are the mount path and
   `RAILWAY_RUN_UID`. A non-root image cannot write `/data`. Design: the image's `USER` stays
   `10002:10002`; on Railway the lab sets `RAILWAY_RUN_UID=0`; `services.lab.serve` then
   chowns `/data` and only the lab's own DB files (`tasksprint.sqlite3*`), calls
   `setgroups([])`, `setgid(10002)`, `setuid(10002)`, verifies `setuid(0)` now fails, and only
   then opens the database or the port. The server never runs as root. Without the variable it
   refuses to start with a message naming it. The root path is unit-tested with a fake OS
   only; the first Railway deploy log is the real evidence (`privileges=started as root: …`).
2. **`::` is not dual-stack under uvicorn by default.** asyncio sets `IPV6_V6ONLY` on IPv6
   listeners, so a runner on `--host ::` refused IPv4 (observed: 127.0.0.1 got no answer).
   Both entrypoints pre-bind the socket; `::` sets `IPV6_V6ONLY=0` (tested: IPv4 and IPv6
   connect). The runner defaults to `::` because Railway environments created before
   16 Oct 2025 resolve `*.railway.internal` to IPv6 only; the lab defaults to `0.0.0.0` as
   requested (public traffic arrives through Railway's edge). Falls back to `0.0.0.0` if the
   container has no IPv6.
3. **`PORT` set explicitly** (lab 8000, runner 8001) so `TASKSPRINT_RUNNER_URL` and the domain
   target port are fixed; the entrypoints and Docker HEALTHCHECK read `$PORT`. Railway's
   healthcheck uses the service's Healthcheck Path (`/healthz`) only at deploy start, from host
   `healthcheck.railway.app`; `/healthz` has no Host filtering (only `/mcp` does).
4. **Migrations once, under a lock.** `Store.migrate` now runs check-and-apply in a single
   `BEGIN IMMEDIATE` transaction (busy timeout 30 s): concurrent starters serialise on the
   SQLite reserved lock, apply nothing twice, and a failing migration applies nothing
   (previously the read of applied versions was outside the per-migration transactions).
   Railway volumes cannot be attached during pre-deploy, so migrations run in the start
   command, before the port opens; `create_app` then only verifies checksums. Railway never
   overlaps deployments of a volume-backed service (brief outage on redeploy).
5. **Nothing is seeded at start-up.** A fresh start creates the database with 0 workspaces,
   tasks, stories, candidates, memories and events; the approved corpus (4 documents) and skill
   catalog (2 skills) are registered append-only as in Phase 04. Seeding is the explicit
   instructor action (`seed_demo.py --lab-url`).
6. **No `VOLUME` in Dockerfile.lab.** Railway's builder refuses the keyword ("The VOLUME keyword
   is banned in Dockerfiles. Use Railway volumes instead."). Compose declares its own volume.
7. **Lab image keeps `instructor/fixtures/`.** The brief listed lab contents as
   `services/lab`, `knowledge/`, `skills/`, migrations and asked `.dockerignore` to exclude
   `instructor/`. The lab's protected seed action reads `starter_v0.py` (and `load_fixture`
   reads the labelled faulty/reference fixtures) from `TASKSPRINT_FIXTURES_DIR`, so without
   them seeding fails. `.dockerignore` therefore has `instructor/*` + `!instructor/fixtures`.
   The fixtures stay server-side (instructor-only routes; never in RAG, skills or developer
   tools), as in Phases 02–04. **Raj to confirm.**
8. **Runner image installs the whole locked set** (one `uv.lock`; it includes mcp/httpx it does
   not import). Source code copied is only `services/__init__.py` + `services/runner/`. A
   runner-only dependency group would need a lock change; not done.
9. **Base images pinned by tag** (`python:3.12-slim`, `ghcr.io/astral-sh/uv:0.12.13`);
   **digest pinning is a TODO** for a Docker host (`docker buildx imagetools inspect …`).
10. **Logs.** A redaction filter sits on every handler (uvicorn access/error and app loggers):
    `Bearer …`, `ts_<role>_…` token shapes and `sk-…` keys are masked. Start-up logs one line
    of non-secret facts (bind, uid, privileges, schema version, migrations applied now, journal
    mode, MCP allowed hosts, runner configured yes/no, number of roles configured). A warning
    containing `421` is logged on Railway when the MCP allowlist is loopback-only.
11. **Separate Railway credential set recommended** (`local_init.py --dir .local/railway
    --db-path /data/tasksprint.sqlite3`); the existing `.local/lab.env` holds a local DB path.

## Commands and actual results

```text
$ uv run pytest -q tests/unit tests/security tests/integration tests/protocol    (baseline, f3de914)
422 passed in 16.38s
$ (after decisions 2-3)                                                           424 passed in 16.41s
$ uv run pytest -q tests/unit tests/security tests/integration tests/protocol    (1c671bb, final)
463 passed in 19.77s
$ uv run pytest -q tests/unit          315 passed in 3.12s
$ uv run pytest -q tests/security       92 passed in 1.59s
$ uv run pytest -q tests/integration    13 passed in 6.27s
$ uv run pytest -q tests/protocol       43 passed in 8.78s
0 failed, 0 skipped.
$ uv lock --check --offline             Resolved 40 packages, exit 0
$ git merge-base --is-ancestor main feature/phase-04-mcp && git fetch . feature/phase-04-mcp:main
$ git log --oneline -1 main             == git log --oneline -1 feature/phase-04-mcp
static scan of services/ for exec( / eval( / compile( / importlib / pickle / subprocess: none (only re.compile)
```

Manual runner check (`python -m services.runner.serve`, PORT=18302, fake 40-char token):

```text
runner start: bind=:: port=18302 uid=1077 workers=1
uvicorn.access ::ffff:127.0.0.1:48132 - "GET /healthz HTTP/1.1" 200
uvicorn.access ::1:39488 - "GET /healthz HTTP/1.1" 200
```

`tests/integration/test_serve_railway_mode.py` (real processes, fresh temporary credentials):
runner via `serve` with only PATH/LANG/PORT/token; lab via `serve` with Railway-style process
variables (no env file), `TASKSPRINT_MCP_ALLOWED_HOSTS=tasksprint-lab-test.up.railway.app,127.0.0.1:*`;
state read before seeding → 404 (nothing seeded); MCP initialize with that Host → 200, other
Host → 421; `seed_demo.py --lab-url` → HTTP 200; `check_stack.py --target railway
--snapshot save` → all PASS; lab stopped and restarted on the same file (redeploy rehearsal),
second start logs `migrations_applied_now=[]`; `--snapshot verify` → `PASS volume persistence
after redeploy: saved newest event present`; no token value in any script output or log; the
token-shaped request path appears as `[REDACTED]`.

## Static Dockerfile checks (no image built)

`tests/unit/test_deploy_files.py` parses both Dockerfiles and `.dockerignore` with Python:
FROM `python:3.12-slim` and uv `0.12.13` by tag with the digest TODO present; `uv sync --frozen
--no-dev` then `rm` of uv; no pip/apt/curl/wget/uv add; final `USER` numeric non-root after the
last RUN; `EXPOSE` and `ENV PORT` (8000/8001); HEALTHCHECK on `/healthz` reading `PORT`; CMD
`/opt/venv/bin/python -m services.<svc>.serve`; no `VOLUME`; every COPY source exists and no
file under it is excluded by `.dockerignore` (moby-style matcher); runner COPYs exactly
`pyproject.toml uv.lock .python-version services/__init__.py services/runner/`; lab COPYs
those plus `services/lab/ knowledge/ skills/ instructor/fixtures/`; no TOKEN/SECRET/HASH/
PASSWORD/API_KEY in ENV/ARG/LABEL; `.dockerignore` excludes `.local/`, `instructor/*` (except
fixtures), `tests/`, `docs/`, `langflow/`, `.git`, `**/*.sqlite3`, `scripts/`, `.env*`.
These are static checks only; `docker build` (or Railway's builder) is the proof.

## Variable names for Railway (full table in `docs/RAILWAY_SETUP.md`)

`.local/lab.env` keys (names read with `grep -o '^[A-Z_]*='`; values not read):
`TASKSPRINT_DB_PATH`, `TASKSPRINT_DEMO_ENABLED`, `TASKSPRINT_ALLOWED_WORKSPACES`,
`TS_RUNNER_TOKEN`, `TS_COORD_TOKEN_HASH`, `TS_PO_TOKEN_HASH`, `TS_DEV_TOKEN_HASH`,
`TS_QA_TOKEN_HASH`, `TS_OPS_TOKEN_HASH`, `TS_APP_TOKEN_HASH`, `TS_APPROVER_TOKEN_HASH`,
`TS_INSTRUCTOR_TOKEN_HASH`, `TS_EVALUATOR_TOKEN_HASH`. Add on the lab: `RAILWAY_DOCKERFILE_PATH`,
`PORT`, `RAILWAY_RUN_UID`, `TASKSPRINT_RUNNER_URL`, `TASKSPRINT_MCP_ALLOWED_HOSTS`. Runner:
`RAILWAY_DOCKERFILE_PATH`, `PORT`, `TS_RUNNER_TOKEN` only.

## BLOCKED and not run

| Item | Reason |
|---|---|
| `docker build` of both images; digest pinning | Docker not installed on the VM |
| Railway services, volume, domain, private DNS (05.3, 05.4) | Owner steps; repository `nuvear/tasksprint-lab` created by Raj |
| Real root → uid 10002 drop on a root-owned volume | Only possible in the container; check the first lab deploy log |
| Live 05.5 checks (HTTPS 401s, MCP host, lab → runner over private DNS, persistence after redeploy) | Need the deployed services; commands in `RAILWAY_SETUP.md` step 4 |
| Compose run | Docker not installed (carried from Phase 03) |

## Manual (human) equivalent

1. Apply the two owner decisions (skill 1.1.0 text, Developer prompt sentence); run the suite.
2. Fast-forward `main` to the feature branch.
3. Write the two entrypoints (read `PORT`; lab: drop privileges after fixing `/data`, migrate,
   start one worker; runner: dual-stack socket), the Dockerfiles and `.dockerignore`.
4. Make `Store.migrate` a single `BEGIN IMMEDIATE` transaction.
5. Add the railway mode to `check_stack.py` and `--lab-url` to `seed_demo.py`; run the suite.
6. Follow `docs/RAILWAY_SETUP.md`.

## Next action (Raj)

1. Push `main` to the new `nuvear/tasksprint-lab` repository (you are creating it).
2. Decide the open points below, then follow `docs/RAILWAY_SETUP.md` §0–§4 and send back the
   redacted outputs of the step-4 commands and the two `lab start:` / `runner start:` log lines.
3. On a Docker host (optional before Railway): `docker build -f Dockerfile.lab .` and
   `docker build -f Dockerfile.runner .`, then pin the digests.

Open points for Raj: (a) keep `instructor/fixtures/` in the lab image (finding 7);
(b) `RAILWAY_RUN_UID=0` + privilege drop (finding 1) versus another approach; (c) separate
Railway credential set (recommended) or reuse `.local/lab.env` hashes; (d) optional
coordinator relay sentence (decision 2); (e) Watch Paths so a push redeploys only the changed
service; (f) the persistence proof uses the newest event IDs readable by the coordinator and
the task list — acceptable as GATE 05 evidence?
