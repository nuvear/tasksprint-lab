"""Container entrypoint for the lab service (Build Guide 05.2 / 05.5; Railway).

    python -m services.lab.serve

* Listens on ``TASKSPRINT_BIND_HOST`` (default ``0.0.0.0``) and ``PORT`` (Railway
  injects it; default 8000). Exactly one worker (A5: one controlled SQLite writer).
* Never serves as root. Railway mounts volumes owned by root, so on Railway the lab
  service sets ``RAILWAY_RUN_UID=0``: the container then starts as root, this
  entrypoint gives the database directory (and only the lab's own database files) to
  the service user 10002, drops all privileges irrevocably, and only then opens the
  database. Started as a non-root user (local Compose, tests) it changes nothing and
  refuses to start if the database directory is not writable.
* Applies schema migrations once, before the port opens, under the SQLite migration
  lock (``Store.migrate``); the application factory then only verifies them.
* Seeds nothing: no workspace, task, story or fixture is created at start-up. The
  approved knowledge corpus and skill catalog are registered (append-only), as before.
* Every log handler carries a redaction filter (bearer tokens, TaskSprint token
  shapes, provider-key shapes). Configuration values are never logged.
"""
from __future__ import annotations

import logging
import logging.config
import os
import socket
import sys
from pathlib import Path
from typing import Any, Mapping

from .audit import REDACTED, _SENSITIVE_VALUE
from .config import ConfigError, Settings, load_settings
from .store import Store

log = logging.getLogger("tasksprint.lab.serve")

SERVICE_UID = 10002
SERVICE_GID = 10002
DEFAULT_PORT = 8000
DEFAULT_BIND_HOST = "0.0.0.0"
BIND_HOSTS = ("0.0.0.0", "::", "127.0.0.1", "::1")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
EXIT_CONFIG = 78  # EX_CONFIG


class StartupError(RuntimeError):
    """A start-up precondition failed. Messages never contain secret values."""


# ------------------------------------------------------------------ configuration
def parse_port(env: Mapping[str, str], default: int = DEFAULT_PORT) -> int:
    raw = (env.get("PORT") or "").strip()
    if not raw:
        return default
    if not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise StartupError("PORT must be an integer between 1 and 65535")
    return int(raw)


def parse_bind_host(env: Mapping[str, str], default: str = DEFAULT_BIND_HOST) -> str:
    host = (env.get("TASKSPRINT_BIND_HOST") or "").strip() or default
    if host not in BIND_HOSTS:
        raise StartupError("TASKSPRINT_BIND_HOST must be one of " + ", ".join(BIND_HOSTS))
    if ":" in host and not ipv6_available():
        log.warning("IPv6 is unavailable in this container; binding 0.0.0.0 instead of %s", host)
        return "0.0.0.0" if host == "::" else "127.0.0.1"
    return host


def ipv6_available() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::", 0))
        return True
    except OSError:
        return False


def bind_socket(host: str, port: int) -> socket.socket:
    """Pre-bound listening socket. ``::`` is made explicitly dual-stack (IPV6_V6ONLY=0):
    asyncio would otherwise create an IPv6-only socket and IPv4 peers could not connect."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0 if host == "::" else 1)
        sock.bind((host, port))
        sock.listen(2048)
        sock.set_inheritable(True)
    except OSError:
        sock.close()
        raise
    return sock


def mcp_host_warning(settings: Settings, env: Mapping[str, str]) -> str | None:
    """On Railway, a loopback-only MCP host allowlist makes every /mcp request answer 421."""
    on_railway = any(env.get(k) for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PUBLIC_DOMAIN"))
    loopback_only = all(h.split(":")[0] in LOOPBACK_HOSTS or h.startswith("[::1]") for h in settings.mcp_allowed_hosts)
    if on_railway and loopback_only:
        return ("TASKSPRINT_MCP_ALLOWED_HOSTS lists only loopback hosts; /mcp will answer 421 to Langflow. "
                "Set it to the lab's public domain.")
    return None


# ------------------------------------------------------------------ privileges and data directory
def _own_db_files(data_dir: Path, db_name: str) -> list[Path]:
    return [p for p in data_dir.iterdir() if p.name == db_name or p.name.startswith(db_name + "-")] \
        if data_dir.is_dir() else []


def prepare_runtime(db_path: str, *, uid: int = SERVICE_UID, gid: int = SERVICE_GID, osmod: Any = os) -> str:
    """Make the database directory usable by the service user and ensure we are not root.

    Returns a short description of what was done (for the start-up log)."""
    if db_path == ":memory:":
        action = "in-memory database"
        data_dir = None
    else:
        db = Path(db_path)
        data_dir = db.parent
        action = "unchanged"
    if osmod.geteuid() == 0:
        if data_dir is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            osmod.chown(data_dir, uid, gid)
            for p in _own_db_files(data_dir, Path(db_path).name):
                osmod.chown(p, uid, gid)
            osmod.chmod(data_dir, 0o700)
        osmod.setgroups([])
        osmod.setgid(gid)
        osmod.setuid(uid)
        if osmod.geteuid() == 0 or osmod.getuid() == 0:
            raise StartupError("could not drop root privileges; refusing to start")
        try:
            osmod.setuid(0)
        except PermissionError:
            pass
        else:
            raise StartupError("root privileges were recoverable after the drop; refusing to start")
        action = f"started as root: gave the database directory to uid {uid}, dropped privileges"
    if data_dir is not None:
        if not data_dir.is_dir():
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise StartupError("database directory cannot be created by this user") from None
        if not osmod.access(data_dir, os.W_OK | os.X_OK):
            raise StartupError("database directory is not writable by this user. On Railway set "
                               "RAILWAY_RUN_UID=0 on the lab service (the entrypoint drops to uid "
                               f"{uid} after fixing the volume's ownership)")
    return action


# ------------------------------------------------------------------ logging
class RedactingFilter(logging.Filter):
    """Masks credential-shaped substrings in every record that reaches a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed record: keep it, unformatted
            return True
        redacted = _SENSITIVE_VALUE.sub(REDACTED, message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def log_config(level: str = "INFO") -> dict[str, Any]:
    handler = {"class": "logging.StreamHandler", "stream": "ext://sys.stderr",
               "formatter": "plain", "filters": ["redact"]}
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"redact": {"()": "services.lab.serve.RedactingFilter"}},
        "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
        "handlers": {"stderr": handler},
        "loggers": {
            "uvicorn": {"handlers": ["stderr"], "level": level, "propagate": False},
            "uvicorn.error": {"level": level},
            "uvicorn.access": {"handlers": ["stderr"], "level": level, "propagate": False},
        },
        "root": {"handlers": ["stderr"], "level": level},
    }


# ------------------------------------------------------------------ main
def startup(env: Mapping[str, str] | None = None) -> tuple[Settings, str, int, dict[str, Any]]:
    """Everything before the port opens. Returns (settings, host, port, facts-for-the-log)."""
    env = os.environ if env is None else env
    port = parse_port(env)
    host = parse_bind_host(env)
    settings = load_settings(dict(env))
    action = prepare_runtime(settings.db_path)
    store = Store(settings.db_path, settings.journal_mode)
    applied = store.migrate()
    facts = {"bind": f"{host}:{port}", "uid": os.getuid(), "privileges": action, "workers": 1,
             "schema_version": store.schema_version(), "migrations_applied_now": applied,
             "journal_mode": settings.journal_mode, "mcp_allowed_hosts": list(settings.mcp_allowed_hosts),
             "runner_configured": bool(settings.runner_url), "roles_configured": len(settings.token_hashes),
             "demo_enabled": settings.demo_enabled}
    return settings, host, port, facts


def main() -> int:
    logging.config.dictConfig(log_config())
    try:
        settings, host, port, facts = startup()
    except (ConfigError, StartupError) as exc:
        log.error("lab start refused: %s", exc)
        return EXIT_CONFIG
    log.info("lab start: %s", " ".join(f"{k}={v}" for k, v in facts.items()))
    warning = mcp_host_warning(settings, os.environ)
    if warning:
        log.warning(warning)
    import uvicorn  # imported late: nothing above needs it

    from .main import create_app
    app = create_app(settings)  # verifies migrations (no-op), registers corpus and skills; seeds nothing
    config = uvicorn.Config(app, host=host, port=port, workers=1, server_header=False, log_config=log_config(),
                            timeout_graceful_shutdown=10)
    try:
        sock = bind_socket(host, port)
    except OSError as exc:
        log.error("cannot listen on %s:%s (%s)", host, port, type(exc).__name__)
        return 1
    uvicorn.Server(config).run(sockets=[sock])
    return 0


if __name__ == "__main__":
    sys.exit(main())
