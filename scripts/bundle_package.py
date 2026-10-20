"""Package the non-flow parts of the redacted workshop bundle (Build Guide 12.2; used by export_bundle.py).

Copies, into the bundle directory: component sources, role prompts, skills, the knowledge corpus, contracts,
pyproject.toml + uv.lock, Dockerfiles + compose.yaml, the redacted test/evaluation reports, the observed UI labels,
the runbook and the frozen-version record. Writes versions.json (Langflow, lab, runner, migrations, policy, suite,
corpus, skills, prompts, components, model, qualified manifest), RESET.md and PRIVATE_CONFIGURATION_CHECKLIST.md
(variable NAMES only). Never copied: .local/, instructor fixtures, grader source (tests/agent_cases/), font files.
Then every bundle file is scanned: credential patterns (export_bundle.scan) and an exact-value check that no
value from .local/railway/*.env occurs in any file (values are compared in memory and never printed).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

from lf_common import REPO_ROOT, read_env

COPY = ["components/*.py", "prompts/*.md", "skills/*/SKILL.md", "knowledge/*.md", "contracts/*", "pyproject.toml",
        "uv.lock", "Dockerfile.lab", "Dockerfile.runner", "compose.yaml", "reports/redacted/*.md",
        "docs/OBSERVED_UI.md", "docs/SESSION_RUNBOOK.md", "docs/FROZEN_VERSION.md", "docs/ACCEPTANCE_SIGNOFF.md",
        "docs/PHASE12_REPORT.md",
        "README.md"]
NEVER = (".local", "instructor", "tests", ".venv", "__pycache__")
FONT_EXT = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
PRIVATE_FILES = ["role_tokens.env", "lab.env", "runner.env", "a2a_runtime.env", "langflow_bootstrap.env"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _versions(langflow_version: str | None, gate: dict | None) -> dict:
    sys.path.insert(0, str(REPO_ROOT))
    from services.lab import SERVICE_VERSION, agent_evaluations, baseline_smoke, release_plans, testing
    from services.lab.store import MIGRATIONS
    from services.runner import GRAMMAR_VERSION, RUNNER_VERSION
    side = agent_evaluations.lab_side()
    comps = {}
    for p in sorted((REPO_ROOT / "components").glob("*.py")):
        line = next((ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("ADAPTER_VERSION")), "")
        comps[p.name] = {"adapter_version": line.split("=", 1)[1].strip().strip('"') if line else None, "sha256": sha(p)}
    return {
        "langflow_version": langflow_version, "lab_service_version": SERVICE_VERSION,
        "lab_side_sha256": agent_evaluations.lab_side_sha256(), "runner_version": RUNNER_VERSION,
        "candidate_grammar": GRAMMAR_VERSION,
        "migrations": [{"id": i, "description": d, "sql_sha256": hashlib.sha256(s.encode()).hexdigest()}
                       for i, d, s in MIGRATIONS],
        "release_policy_version": release_plans.POLICY_VERSION, "release_plan_schema": release_plans.PLAN_SCHEMA_VERSION,
        "protected_suite": {"version": testing.SUITE_VERSION, "sha256": testing.SUITE_SHA256},
        "baseline_smoke": {"version": baseline_smoke.SMOKE_VERSION, "sha256": baseline_smoke.SMOKE_SHA256},
        "harness_budgets": side["harness_budgets"], "corpus": side["corpus"], "skills": side["skills"],
        "prompts": {p.name: sha(p) for p in sorted((REPO_ROOT / "prompts").glob("*.md"))},
        "components": comps, "model": "claude-sonnet-5-5 (Anthropic, Langflow Agent component)",
        "qualified_manifest": gate,
    }


RESET = """# Reset and recovery (demo-001 only)

Reset touches only the designated workspace in the TaskSprint lab. Nothing in Langflow changes, and append-only
evidence (candidates, test runs, plans, approvals, releases and events) is kept.

1. Preview (read-only): `uv run --frozen --no-dev python scripts/reset_demo.py --workspace demo-001 --dry-run
   --lab-url https://tasksprint-lab-production.up.railway.app --tokens-file .local/railway/role_tokens.env`
   Or in TS-90 Instructor Console: `reset preview`.
2. Apply: the same command with `--confirm demo-001` in place of `--dry-run` (the workspace must be repeated).
   Or in TS-90: `reset confirm demo-001`.
3. Result: a new generation, v0 active, T001/T002 incomplete, no story, memory, drill, outage, stop flag, open
   plan or unused approval. Runs and approvals of earlier generations can no longer act.
4. Verify: `uv run --frozen --no-dev python scripts/doctor.py --no-model-probe` (expect PASS).

The release revision is a monotonic counter and does not return to 0. Reset never restores a database snapshot
and never touches Railway, Langflow or its Postgres. Emergency stop: TS-90 `stop` (clears with `resume`).
"""


def _checklist(known_vars: set[str]) -> str:
    rows = []
    for f in PRIVATE_FILES:
        p = REPO_ROOT / ".local/railway" / f
        names = sorted(read_env(p)) if p.is_file() else []
        rows.append(f"| `.local/railway/{f}` | {', '.join(f'`{n}`' for n in names) or '(missing)'} | password manager |")
    lf = ", ".join(f"`{n}`" for n in sorted(v for v in known_vars if v.startswith(("TS_", "TASKSPRINT_"))))
    return "\n".join([
        "# Private configuration checklist (names only; no value is in this bundle)", "",
        "Keep every value below in the owner's password manager. Restore files with mode 0600 and never commit them.",
        "", "| Location | Variable names | Keep in |", "|---|---|---|", *rows,
        f"| Langflow globals (Settings → Global Variables) | {lf} | Langflow (Credential type for tokens/keys) |",
        "| Langflow API keys (Settings → Langflow API Keys) | `tasksprint-a2a-runtime` (runtime; stays). "
        "`tasksprint-bootstrap` (setup only; **revoke at handover**) | password manager |",
        "| Railway `tasksprint-lab` variables | the names in `lab.env` (token HASHES, runner token, DB path) | Railway |",
        "| Railway `tasksprint-runner` variables | the names in `runner.env` | Railway |",
        "| Anthropic model key | stored only in Langflow Model Providers; never in this repository | provider console |",
        "", "Existing service secrets (Langflow admin password, LANGFLOW_SECRET_KEY, Postgres) are not TaskSprint "
        "configuration and were never read.", ""])


def build(out: Path, langflow_version: str | None, known_vars: set[str], gate: dict | None,
          scan) -> int:
    fails = 0

    def result(ok: bool, what: str) -> None:
        nonlocal fails
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'} {what}")

    copied = 0
    for pattern in COPY:
        for src in sorted(REPO_ROOT.glob(pattern)):
            rel = src.relative_to(REPO_ROOT)
            if not src.is_file() or rel.parts[0] in NEVER or src.suffix.lower() in FONT_EXT:
                continue
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            copied += 1
    (out / "versions.json").write_text(json.dumps(_versions(langflow_version, gate), indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8")
    (out / "RESET.md").write_text(RESET, encoding="utf-8")
    (out / "PRIVATE_CONFIGURATION_CHECKLIST.md").write_text(_checklist(known_vars), encoding="utf-8")
    print(f"INFO packaged {copied} source/document files + versions.json, RESET.md, PRIVATE_CONFIGURATION_CHECKLIST.md")
    files = [p for p in out.rglob("*") if p.is_file()]
    result(not [p for p in files if p.suffix.lower() in FONT_EXT], "no font files in the bundle")
    result(not [p for p in files if any(x in p.relative_to(out).parts for x in (".local", "instructor", "agent_cases"))],
           "no .local/, instructor fixtures or grader source in the bundle")
    secrets = set()
    for f in PRIVATE_FILES:
        p = REPO_ROOT / ".local/railway" / f
        if p.is_file():
            secrets |= {v for k, v in read_env(p).items() if len(v) >= 16 and
                        any(w in k for w in ("TOKEN", "KEY", "HASH", "SECRET"))}
    hits_pattern, hits_value = [], []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if scan(text):
            hits_pattern.append(str(p.relative_to(out)))
        if any(s in text for s in secrets):
            hits_value.append(str(p.relative_to(out)))
    result(not hits_pattern, f"credential-pattern scan of {len(files)} bundle files ({len(hits_pattern)} files hit) "
                             f"{hits_pattern[:5]}")
    result(bool(secrets) and not hits_value, f"exact-value scan: none of {len(secrets)} private values occurs in any "
                                             f"bundle file ({len(hits_value)} files hit) {hits_value[:5]}")
    sums = "".join(f"{sha(p)}  {p.relative_to(out)}\n" for p in sorted(files) if p.name != "BUNDLE_SHA256SUMS.txt")
    (out / "BUNDLE_SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    return fails
