"""Static checks of the Phase 05 deployment files (Build Guide 05.2).

Docker is not installed on the build VM, so no image is built here. These checks parse
Dockerfile.lab, Dockerfile.runner and .dockerignore with plain Python and verify the
properties the guide requires; a real `docker build` on a Docker host (or Railway's
builder) remains the proof that the images build.
"""
from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVICES = {"lab": "Dockerfile.lab", "runner": "Dockerfile.runner"}


def instructions(name: str) -> list[tuple[str, str]]:
    """(INSTRUCTION, arguments) with line continuations joined and comments dropped."""
    out: list[tuple[str, str]] = []
    buf = ""
    for raw in (REPO / name).read_text().splitlines():
        line = raw.rstrip()
        if not buf and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        word, _, rest = buf.strip().partition(" ")
        out.append((word.upper(), rest.strip()))
        buf = ""
    return out


def copies(name: str) -> list[tuple[list[str], str]]:
    result = []
    for ins, args in instructions(name):
        if ins == "COPY" and not args.startswith("--from"):
            parts = shlex.split(args)
            result.append((parts[:-1], parts[-1]))
    return result


def dockerignore_patterns() -> list[tuple[bool, str]]:
    pats = []
    for raw in (REPO / ".dockerignore").read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        pats.append((neg, line.lstrip("!").rstrip("/")))
    return pats


def _pattern_regex(pat: str) -> re.Pattern[str]:
    """moby/patternmatcher semantics: anchored at the context root, `*` and `?` stay inside
    one path segment, `**/` matches any number of directories."""
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pat.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pat[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pat[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pat[i]), i + 1
    return re.compile(out + r"\Z")


def ignored(rel: str) -> bool:
    """Last matching pattern wins; a pattern that matches a parent directory matches the file."""
    parts = rel.split("/")
    candidates = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    state = False
    for neg, pat in dockerignore_patterns():
        rx = _pattern_regex(pat)
        if any(rx.match(c) for c in candidates):
            state = not neg
    return state


def files_under(src: str) -> list[str]:
    p = REPO / src.rstrip("/")
    if p.is_file():
        return [src]
    return sorted(str(f.relative_to(REPO)) for f in p.rglob("*") if f.is_file() and "__pycache__" not in f.parts)


@pytest.mark.parametrize("svc", SERVICES)
def test_base_images_are_pinned_by_tag_and_digest_todo_is_recorded(svc):
    ins = instructions(SERVICES[svc])
    froms = [a for i, a in ins if i == "FROM"]
    assert froms == ["python:3.12-slim"]
    uv = [a for i, a in ins if i == "COPY" and a.startswith("--from=")]
    assert uv == ["--from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv"]
    assert "TODO(Phase 05" in (REPO / SERVICES[svc]).read_text() and "digest" in (REPO / SERVICES[svc]).read_text()


@pytest.mark.parametrize("svc", SERVICES)
def test_dependencies_come_only_from_the_lock_file_at_build_time(svc):
    ins = instructions(SERVICES[svc])
    runs = [a for i, a in ins if i == "RUN"]
    assert any("uv sync --frozen --no-dev" in r and "rm /usr/local/bin/uv" in r for r in runs)
    joined = " ".join(runs)
    for forbidden in ("pip install", "apt-get", "apk add", "curl ", "wget ", "uv add", "uv pip"):
        assert forbidden not in joined, forbidden
    # The CMD starts the service directly; nothing is installed at run time.
    cmd = json.loads(next(a for i, a in ins if i == "CMD"))
    assert cmd[:2] == ["/opt/venv/bin/python", "-m"] and not any("install" in c for c in cmd)


@pytest.mark.parametrize("svc,uid", [("lab", "10002"), ("runner", "10001")])
def test_runtime_user_is_numeric_and_not_root(svc, uid):
    ins = instructions(SERVICES[svc])
    users = [a for i, a in ins if i == "USER"]
    assert users and users[-1] == f"{uid}:{uid}"
    assert ins.index(("USER", users[-1])) > max(n for n, (i, _) in enumerate(ins) if i == "RUN")


@pytest.mark.parametrize("svc,port", [("lab", "8000"), ("runner", "8001")])
def test_port_healthcheck_and_entrypoint(svc, port):
    ins = instructions(SERVICES[svc])
    assert ("EXPOSE", port) in ins
    env = " ".join(a for i, a in ins if i == "ENV")
    assert f"PORT={port}" in env
    hc = next(a for i, a in ins if i == "HEALTHCHECK")
    assert "/healthz" in hc and "os.environ.get('PORT'" in hc
    cmd = json.loads(next(a for i, a in ins if i == "CMD"))
    assert cmd == ["/opt/venv/bin/python", "-m", f"services.{svc}.serve"]
    assert (REPO / "services" / svc / "serve.py").is_file()
    assert not any(i == "VOLUME" for i, _ in ins)  # Railway rejects VOLUME; volumes are service settings


@pytest.mark.parametrize("svc", SERVICES)
def test_every_copy_source_exists_and_is_in_the_build_context(svc):
    for sources, _ in copies(SERVICES[svc]):
        for src in sources:
            assert (REPO / src.rstrip("/")).exists(), src
            files = files_under(src)
            assert files, src
            kept = [f for f in files if not ignored(f)]
            assert kept == files, f"{src}: excluded by .dockerignore: {sorted(set(files) - set(kept))}"


def test_runner_image_contains_only_the_runner():
    sources = [s for srcs, _ in copies("Dockerfile.runner") for s in srcs]
    assert sources == ["pyproject.toml", "uv.lock", ".python-version", "services/__init__.py", "services/runner/"]


def test_lab_image_contains_lab_corpus_skills_and_fixtures_only():
    sources = [s for srcs, _ in copies("Dockerfile.lab") for s in srcs]
    assert sources == ["pyproject.toml", "uv.lock", ".python-version", "services/__init__.py", "services/lab/",
                       "knowledge/", "skills/", "instructor/fixtures/"]
    text = (REPO / "Dockerfile.lab").read_text()
    assert "TASKSPRINT_DB_PATH=/data/tasksprint.sqlite3" in text and "RAILWAY_RUN_UID=0" in text


def test_no_secret_values_or_secret_names_are_baked_into_images():
    for name in SERVICES.values():
        for ins, args in instructions(name):
            if ins in ("ENV", "ARG", "LABEL"):
                assert not re.search(r"(TOKEN|SECRET|HASH|PASSWORD|API_KEY)", args, re.I), (name, args)


def test_dockerignore_excludes_secrets_data_and_non_runtime_material():
    pats = {p for neg, p in dockerignore_patterns() if not neg}
    for required in (".local", "tests", "docs", "langflow", ".git", "**/*.sqlite3"):
        assert required in pats, required
    assert "instructor/*" in pats and (True, "instructor/fixtures") in dockerignore_patterns()
    for path in (".local/lab.env", ".local/role_tokens.env", ".local/railway/role_tokens.env", "tests/conftest.py",
                 "docs/BUILD_GUIDE.md", "langflow/COMPONENT_MAP.md", ".git/HEAD", "x/tasksprint.sqlite3",
                 "instructor/notes.md", ".env", "scripts/local_init.py", "services/lab/__pycache__/main.cpython-312.pyc"):
        assert ignored(path), path
    for path in ("services/lab/main.py", "services/runner/main.py", "knowledge/01_product_brief.md",
                 "skills/implement-todo-change/SKILL.md", "instructor/fixtures/starter_v0.py", "uv.lock"):
        assert not ignored(path), path
