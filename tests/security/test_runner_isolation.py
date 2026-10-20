"""The runner holds no lab data access, role tokens or platform secrets (A2, Build Guide 03.4).

Static and configuration checks. The live separate-process check (process
environment and open files of a running runner) is in
tests/integration/test_runner_process.py.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from services.runner.main import RunnerSettings, load_runner_settings
from tests.conftest import FAKE_RUNNER_TOKEN

REPO = Path(__file__).resolve().parents[2]
RUNNER_DIR = REPO / "services" / "runner"
ALLOWED_IMPORTS = {"__future__", "ast", "dataclasses", "hashlib", "hmac", "json", "logging", "os", "re", "time",
                   "typing", "fastapi", "fastapi.responses", "starlette.concurrency"}


def runner_imports() -> set[str]:
    names: set[str] = set()
    for path in RUNNER_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add(node.module or "")
    return names


def test_runner_imports_only_an_allowlisted_set():
    """No sqlite3, no lab package, no HTTP client, no subprocess, no pickle, no importlib."""
    assert runner_imports() <= ALLOWED_IMPORTS, runner_imports() - ALLOWED_IMPORTS


def test_runner_never_references_lab_code_or_storage():
    text = "\n".join(p.read_text() for p in RUNNER_DIR.glob("*.py"))
    assert "services.lab" not in text and "from ..lab" not in text
    assert not re.search(r"\bsqlite3\b|\bopen\(|Path\(|\.sqlite", text)


def test_interpreter_never_calls_getattr_or_setattr_on_candidate_names():
    text = (RUNNER_DIR / "interpreter.py").read_text()
    assert not re.search(r"\b(getattr|setattr|delattr|__dict__|globals|locals|vars)\s*\(", text.replace(
        'getattr(node, "lineno", None)', "").replace('getattr(self', ""))


def test_runner_settings_contain_only_transport_token_and_limits():
    s = load_runner_settings({"TS_RUNNER_TOKEN": FAKE_RUNNER_TOKEN, "HOME": "/home/runner", "PATH": "/usr/bin"})
    assert set(RunnerSettings.__dataclass_fields__) == {"token", "limits", "allow_root"}
    assert FAKE_RUNNER_TOKEN not in repr(s)


def test_runner_container_image_contains_only_runner_code():
    dockerfile = (REPO / "Dockerfile.runner").read_text()
    copies = [line for line in dockerfile.splitlines() if line.strip().upper().startswith("COPY")]
    joined = "\n".join(copies)
    assert "services/runner" in joined
    assert "services/lab" not in joined and "instructor" not in joined and ".local" not in joined
    assert not re.search(r"COPY\s+\.\s", joined)
    assert re.search(r"^USER\s+\d+", dockerfile, re.M), "runner image must run as a non-root numeric user"


def test_compose_gives_the_runner_no_volume_ports_or_lab_secrets():
    compose = (REPO / "compose.yaml").read_text()
    runner_block = compose.split("\n  runner:\n", 1)[1].split("\n  lab:\n", 1)[0] if "\n  runner:\n" in compose else ""
    assert runner_block, "compose.yaml must define a runner service"
    assert "volumes:" not in runner_block and "ports:" not in runner_block
    assert "lab.env" not in runner_block and "role_tokens" not in runner_block
    assert "TASKSPRINT_DB_PATH" not in runner_block
    assert "read_only: true" in runner_block


def _init(target: Path, *extra: str):
    import subprocess
    import sys
    return subprocess.run([sys.executable, str(REPO / "scripts" / "local_init.py"), "--dir", str(target), *extra],
                          capture_output=True, text=True, timeout=30)


def test_local_init_runner_env_holds_only_the_transport_token(tmp_path):
    from services.lab.config import parse_env_file
    target = tmp_path / ".local"
    out = _init(target)
    assert out.returncode == 0
    runner_env = parse_env_file(target / "runner.env")
    lab_env = parse_env_file(target / "lab.env")
    assert set(runner_env) == {"TS_RUNNER_TOKEN"} and runner_env["TS_RUNNER_TOKEN"] == lab_env["TS_RUNNER_TOKEN"]
    assert runner_env["TS_RUNNER_TOKEN"] not in out.stdout + out.stderr
    assert ((target / "runner.env").stat().st_mode & 0o077) == 0
    load_runner_settings(runner_env)  # the runner accepts exactly this configuration


def test_derive_runner_env_for_pre_phase03_setups(tmp_path):
    target = tmp_path / ".local"
    assert _init(target).returncode == 0
    (target / "runner.env").unlink()
    lab_before = (target / "lab.env").read_bytes()
    out = _init(target, "--derive-runner-env")
    assert out.returncode == 0 and "value not printed" in out.stdout
    assert (target / "lab.env").read_bytes() == lab_before
    assert _init(target, "--derive-runner-env").returncode == 3  # never overwrites
