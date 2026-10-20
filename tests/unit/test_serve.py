"""Phase 05 container entrypoints (Build Guide 05.2/05.5): port, bind host, privilege drop,
migrations once under a lock, nothing seeded, redacted logs. All values are fake."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path

import pytest

from services.lab import serve as lab_serve
from services.lab import store as store_mod
from services.lab.config import ConfigError, load_settings
from services.lab.main import create_app
from services.lab.store import Store
from services.runner import serve as runner_serve
from tests.conftest import FAKE_TOKENS


# ------------------------------------------------------------------ PORT and bind host
@pytest.mark.parametrize("mod,default", [(lab_serve, 8000), (runner_serve, 8001)])
def test_port_comes_from_railway_port_variable(mod, default):
    assert mod.parse_port({}) == default
    assert mod.parse_port({"PORT": ""}) == default
    assert mod.parse_port({"PORT": "8080"}) == 8080
    for bad in ("0", "65536", "80a", "-1", " 1 2"):
        with pytest.raises(mod.StartupError):
            mod.parse_port({"PORT": bad})


def test_bind_host_defaults_lab_ipv4_any_runner_dual_stack():
    assert lab_serve.parse_bind_host({}) == "0.0.0.0"
    expected_runner = "::" if runner_serve.ipv6_available() else "0.0.0.0"
    assert runner_serve.parse_bind_host({}) == expected_runner
    assert lab_serve.parse_bind_host({"TASKSPRINT_BIND_HOST": "127.0.0.1"}) == "127.0.0.1"
    for mod in (lab_serve, runner_serve):
        for bad in ("example.com", "10.0.0.1", "*", "0.0.0.0:80"):
            with pytest.raises(mod.StartupError):
                mod.parse_bind_host({"TASKSPRINT_BIND_HOST": bad})


def test_ipv6_fallback(monkeypatch):
    monkeypatch.setattr(runner_serve, "ipv6_available", lambda: False)
    assert runner_serve.parse_bind_host({}) == "0.0.0.0"
    monkeypatch.setattr(lab_serve, "ipv6_available", lambda: False)
    assert lab_serve.parse_bind_host({"TASKSPRINT_BIND_HOST": "::"}) == "0.0.0.0"


def test_runner_serve_accepts_railway_injected_variables():
    """Railway injects PORT and RAILWAY_* variables; none of them may trip the runner's guard."""
    from services.runner.main import forbidden_env_names
    env = {"PORT": "8001", "TASKSPRINT_BIND_HOST": "::", "RAILWAY_ENVIRONMENT": "production",
           "RAILWAY_PRIVATE_DOMAIN": "tasksprint-runner.railway.internal", "RAILWAY_SERVICE_NAME": "tasksprint-runner",
           "RAILWAY_PROJECT_ID": "x", "RAILWAY_DOCKERFILE_PATH": "Dockerfile.runner", "TS_RUNNER_TOKEN": "x" * 40}
    assert forbidden_env_names(env) == []
    # ...while lab variables pasted by mistake are still refused.
    assert forbidden_env_names({**env, "TS_COORD_TOKEN_HASH": "0" * 64, "TASKSPRINT_DB_PATH": "/data/x"}) == \
        ["TASKSPRINT_DB_PATH", "TS_COORD_TOKEN_HASH"]


# ------------------------------------------------------------------ privileges
class FakeOS:
    """Records privileged calls; starts as root and drops when setuid is called."""

    W_OK, X_OK = os.W_OK, os.X_OK

    def __init__(self, drop_works: bool = True):
        self.euid = 0
        self.calls: list[tuple] = []
        self.drop_works = drop_works

    def geteuid(self):
        return self.euid

    def getuid(self):
        return self.euid

    def chown(self, path, uid, gid):
        self.calls.append(("chown", Path(path).name, uid, gid))

    def chmod(self, path, mode):
        self.calls.append(("chmod", Path(path).name, mode))

    def setgroups(self, groups):
        self.calls.append(("setgroups", tuple(groups)))

    def setgid(self, gid):
        self.calls.append(("setgid", gid))

    def setuid(self, uid):
        if uid == 0 and self.euid != 0:
            raise PermissionError("not permitted")
        self.calls.append(("setuid", uid))
        if self.drop_works:
            self.euid = uid

    def access(self, path, mode):
        return True


def test_root_start_chowns_only_lab_files_then_drops_privileges(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    for name in ("tasksprint.sqlite3", "tasksprint.sqlite3-journal", "other-service.db", "lost+found"):
        (data / name).write_text("")
    fake = FakeOS()
    action = lab_serve.prepare_runtime(str(data / "tasksprint.sqlite3"), osmod=fake)
    chowned = sorted(c[1] for c in fake.calls if c[0] == "chown")
    assert chowned == ["data", "tasksprint.sqlite3", "tasksprint.sqlite3-journal"]
    assert all(c[2:] == (10002, 10002) for c in fake.calls if c[0] == "chown")
    order = [c[0] for c in fake.calls if c[0] in ("setgroups", "setgid", "setuid")]
    assert order == ["setgroups", "setgid", "setuid"]  # groups and gid before uid
    assert ("setgroups", ()) in fake.calls and fake.euid == 10002
    assert "dropped privileges" in action


def test_root_start_refuses_when_privileges_do_not_drop(tmp_path):
    with pytest.raises(lab_serve.StartupError, match="drop root"):
        lab_serve.prepare_runtime(str(tmp_path / "d" / "t.sqlite3"), osmod=FakeOS(drop_works=False))


@pytest.mark.skipif(os.geteuid() == 0, reason="permission checks are meaningless as root")
def test_non_root_start_changes_nothing_and_requires_a_writable_directory(tmp_path):
    ok_dir = tmp_path / "ok"
    assert lab_serve.prepare_runtime(str(ok_dir / "t.sqlite3")) == "unchanged" and ok_dir.is_dir()
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(lab_serve.StartupError, match="RAILWAY_RUN_UID=0"):
            lab_serve.prepare_runtime(str(ro / "t.sqlite3"))
    finally:
        ro.chmod(0o700)


# ------------------------------------------------------------------ start-up sequence
def _env(db: Path, **extra) -> dict[str, str]:
    import hashlib
    env = {"TASKSPRINT_DB_PATH": str(db), "PORT": "8123", "TASKSPRINT_DEMO_ENABLED": "true",
           "TS_COORD_TOKEN_HASH": hashlib.sha256(FAKE_TOKENS["coordinator"].encode()).hexdigest()}
    env.update(extra)
    return env


def test_startup_migrates_once_and_reports_non_secret_facts(tmp_path):
    db = tmp_path / "data" / "tasksprint.sqlite3"
    settings, host, port, facts = lab_serve.startup(_env(db))
    assert (host, port) == ("0.0.0.0", 8123)
    assert facts["migrations_applied_now"] == [1, 2, 3] and facts["schema_version"] == 3
    assert facts["workers"] == 1 and facts["roles_configured"] == 1
    assert not any(v in str(facts) for v in FAKE_TOKENS.values())
    assert FAKE_TOKENS["coordinator"] not in str(facts)
    _, _, _, again = lab_serve.startup(_env(db))
    assert again["migrations_applied_now"] == []  # second start: verify only


def test_startup_seeds_nothing(tmp_path):
    db = tmp_path / "tasksprint.sqlite3"
    settings, _, _, _ = lab_serve.startup(_env(db))
    create_app(settings)
    conn = sqlite3.connect(db)
    for table in ("workspaces", "tasks", "sprints", "stories", "candidates", "memories", "events"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    # Catalog registration (append-only, versioned) is not demo seeding.
    assert conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 4


def test_startup_refuses_bad_configuration(tmp_path):
    with pytest.raises(ConfigError):
        lab_serve.startup({"PORT": "8000"})  # no TASKSPRINT_DB_PATH
    with pytest.raises(lab_serve.StartupError):
        lab_serve.startup(_env(tmp_path / "t.sqlite3", PORT="http"))


def test_mcp_allowed_hosts_are_parsed_from_the_environment(tmp_path):
    s = load_settings({"TASKSPRINT_DB_PATH": str(tmp_path / "t.sqlite3"),
                       "TASKSPRINT_MCP_ALLOWED_HOSTS": " tasksprint-lab-production.up.railway.app , 127.0.0.1:*"})
    assert s.mcp_allowed_hosts == ("tasksprint-lab-production.up.railway.app", "127.0.0.1:*")
    for bad in ("https://lab.example", "*", "lab.example/mcp", "lab.example:abc"):
        with pytest.raises(ConfigError):
            load_settings({"TASKSPRINT_DB_PATH": str(tmp_path / "t.sqlite3"), "TASKSPRINT_MCP_ALLOWED_HOSTS": bad})


def test_loopback_only_mcp_hosts_on_railway_are_warned(tmp_path):
    default = load_settings({"TASKSPRINT_DB_PATH": str(tmp_path / "t.sqlite3")})
    assert lab_serve.mcp_host_warning(default, {}) is None
    assert "421" in lab_serve.mcp_host_warning(default, {"RAILWAY_ENVIRONMENT": "production"})
    public = load_settings({"TASKSPRINT_DB_PATH": str(tmp_path / "t.sqlite3"),
                            "TASKSPRINT_MCP_ALLOWED_HOSTS": "lab.up.railway.app"})
    assert lab_serve.mcp_host_warning(public, {"RAILWAY_ENVIRONMENT": "production"}) is None


# ------------------------------------------------------------------ migration lock
def test_concurrent_starters_apply_migrations_exactly_once(tmp_path):
    db = str(tmp_path / "race.sqlite3")
    stores = [Store(db) for _ in range(6)]  # separate Store objects = separate in-process locks
    barrier = threading.Barrier(len(stores))
    results: list[list[int]] = []
    errors: list[BaseException] = []

    def go(s: Store) -> None:
        barrier.wait()
        try:
            results.append(s.migrate())
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(s,)) for s in stores]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors, errors
    assert sorted(results, key=len) == [[]] * 5 + [[1, 2, 3]]
    conn = sqlite3.connect(db)
    assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2, 3]


def test_failed_migration_applies_nothing(tmp_path, monkeypatch):
    bad = list(store_mod.MIGRATIONS) + [(3, "broken", "CREATE TABLE zz (a INTEGER);\nINSERT INTO no_such_table VALUES (1);")]
    monkeypatch.setattr(store_mod, "MIGRATIONS", bad)
    db = tmp_path / "f.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        Store(str(db)).migrate()
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "workspaces" not in names and "zz" not in names and "schema_migrations" not in names


# ------------------------------------------------------------------ log redaction
@pytest.mark.parametrize("filt", [lab_serve.RedactingFilter(), runner_serve.RedactingFilter()])
def test_log_filters_mask_bearer_tokens(filt):
    secret = FAKE_TOKENS["developer"]
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "header %s seen", (f"Bearer {secret}",), None)
    assert filt.filter(rec) is True
    assert secret not in rec.getMessage() and "[REDACTED]" in rec.getMessage()


def test_lab_log_filter_masks_token_shapes_without_bearer():
    secret = FAKE_TOKENS["qa"]
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '"GET /%s HTTP/1.1" 404', (secret,), None)
    lab_serve.RedactingFilter().filter(rec)
    assert secret not in rec.getMessage()


def test_log_config_attaches_the_filter_to_every_handler():
    for mod in (lab_serve, runner_serve):
        cfg = mod.log_config()
        assert all(h.get("filters") == ["redact"] for h in cfg["handlers"].values())
        assert cfg["loggers"]["uvicorn.access"]["handlers"] == ["stderr"]


@pytest.mark.skipif(not runner_serve.ipv6_available(), reason="no IPv6 in this environment")
@pytest.mark.parametrize("mod", [lab_serve, runner_serve])
def test_double_colon_socket_is_dual_stack(mod):
    """Railway private DNS may resolve to IPv6 only (older environments) or IPv4 and IPv6."""
    import socket
    sock = mod.bind_socket("::", 0)
    try:
        port = sock.getsockname()[1]
        for family, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            with socket.socket(family, socket.SOCK_STREAM) as c:
                c.settimeout(2)
                c.connect((addr, port))
    finally:
        sock.close()
