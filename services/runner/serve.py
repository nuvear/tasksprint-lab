"""Container entrypoint for the bounded runner (Build Guide 05.2; Railway private service).

    python -m services.runner.serve

* Listens on ``TASKSPRINT_BIND_HOST`` (default ``::``) and ``PORT`` (default 8001), one
  worker. ``::`` is dual-stack on Linux, so the runner answers on Railway's private
  network whether the environment resolves ``<service>.railway.internal`` to IPv6 only
  (environments created before 16 Oct 2025) or to IPv4 and IPv6. If the container has
  no IPv6 at all it falls back to ``0.0.0.0``.
* Configuration is checked before the port opens (``load_runner_settings``: transport
  token present, no lab/platform secrets in the environment); the runner refuses root.
* Every log handler masks bearer tokens. This module imports nothing from the lab.
"""
from __future__ import annotations

import logging
import logging.config
import os
import re
import socket
import sys
from typing import Any, Mapping

from .main import RunnerConfigError, create_app, load_runner_settings

log = logging.getLogger("tasksprint.runner.serve")

DEFAULT_PORT = 8001
DEFAULT_BIND_HOST = "::"
BIND_HOSTS = ("0.0.0.0", "::", "127.0.0.1", "::1")
EXIT_CONFIG = 78
_BEARER = re.compile(r"Bearer\s+\S+", re.I)


class StartupError(RuntimeError):
    """Start-up precondition failed. Messages never contain values."""


def parse_port(env: Mapping[str, str], default: int = DEFAULT_PORT) -> int:
    raw = (env.get("PORT") or "").strip()
    if not raw:
        return default
    if not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise StartupError("PORT must be an integer between 1 and 65535")
    return int(raw)


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


def parse_bind_host(env: Mapping[str, str], default: str = DEFAULT_BIND_HOST) -> str:
    host = (env.get("TASKSPRINT_BIND_HOST") or "").strip() or default
    if host not in BIND_HOSTS:
        raise StartupError("TASKSPRINT_BIND_HOST must be one of " + ", ".join(BIND_HOSTS))
    if ":" in host and not ipv6_available():
        log.warning("IPv6 is unavailable in this container; binding without it")
        return "0.0.0.0" if host == "::" else "127.0.0.1"
    return host


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = _BEARER.sub("Bearer [REDACTED]", message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def log_config(level: str = "INFO") -> dict[str, Any]:
    handler = {"class": "logging.StreamHandler", "stream": "ext://sys.stderr",
               "formatter": "plain", "filters": ["redact"]}
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"redact": {"()": "services.runner.serve.RedactingFilter"}},
        "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
        "handlers": {"stderr": handler},
        "loggers": {
            "uvicorn": {"handlers": ["stderr"], "level": level, "propagate": False},
            "uvicorn.error": {"level": level},
            "uvicorn.access": {"handlers": ["stderr"], "level": level, "propagate": False},
        },
        "root": {"handlers": ["stderr"], "level": level},
    }


def main() -> int:
    logging.config.dictConfig(log_config())
    try:
        port = parse_port(os.environ)
        host = parse_bind_host(os.environ)
        app = create_app(load_runner_settings())
    except (RunnerConfigError, StartupError) as exc:
        log.error("runner start refused: %s", exc)
        return EXIT_CONFIG
    log.info("runner start: bind=%s port=%s uid=%s workers=1", host, port, os.getuid())
    import uvicorn

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
