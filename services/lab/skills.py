"""Approved skill catalog (Architecture A7).

Loads exactly ``skills/<name>/SKILL.md`` for each immediate sub-folder of
``skills/`` into the append-only ``skills`` table: a catalog separate from the
knowledge corpus. Frontmatter must give ``name`` (equal to the folder name),
``description`` and ``metadata.version``; ``metadata.owner`` is kept as metadata.

* ``list`` returns metadata only (name, version, description, owner, hash).
* ``get`` returns the approved body for an exact name and version.
* The body hash is SHA-256 over the returned body text; ``package_sha256`` is the
  SHA-256 of the SKILL.md file bytes.

A skill is procedure, not authority: nothing here touches roles or permissions,
and a skill's text cannot add tools (MCP visibility comes from ``auth.PERMISSIONS``).
A changed SKILL.md without a new ``metadata.version`` refuses start-up.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import frontmatter
from .clock import utc_now_iso
from .store import Store

MAX_SKILL_BYTES = 32 * 1024
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.\-]{0,31}$")


class SkillIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    version: str
    description: str
    owner: str
    body: str
    body_sha256: str
    package_sha256: str

    def summary(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "description": self.description, "owner": self.owner,
                "body_sha256": self.body_sha256}


def parse_skill(folder: Path) -> Skill:
    path = folder / "SKILL.md"
    if folder.is_symlink() or path.is_symlink() or not path.is_file():
        raise SkillIntegrityError(f"{folder.name}: SKILL.md missing or not a regular file")
    raw = path.read_bytes()
    if len(raw) > MAX_SKILL_BYTES:
        raise SkillIntegrityError(f"{folder.name}: SKILL.md too large")
    try:
        meta, body = frontmatter.split(raw.decode("utf-8"))
    except (UnicodeDecodeError, frontmatter.FrontmatterError) as exc:
        raise SkillIntegrityError(f"{folder.name}: {exc}") from None
    md = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    name, description = str(meta.get("name", "")), str(meta.get("description", ""))
    version, owner = str(md.get("version", "")), str(md.get("owner", ""))
    if name != folder.name or not NAME_RE.match(name):
        raise SkillIntegrityError(f"{folder.name}: frontmatter name must equal the folder name")
    if not VERSION_RE.match(version):
        raise SkillIntegrityError(f"{folder.name}: metadata.version missing or malformed")
    if not 1 <= len(description) <= 1024:
        raise SkillIntegrityError(f"{folder.name}: description missing or too long")
    return Skill(name, version, description, owner, body, hashlib.sha256(body.encode("utf-8")).hexdigest(),
                 hashlib.sha256(raw).hexdigest())


class SkillCatalog:
    def __init__(self, store: Store, skills_dir: Path | str):
        self.store = store
        self.skills_dir = Path(skills_dir)
        self._skills: dict[tuple[str, str], Skill] = {}

    def load(self) -> list[dict[str, Any]]:
        if not self.skills_dir.is_dir():
            raise SkillIntegrityError("skills/ folder is missing; refusing to serve an empty catalog")
        found = [parse_skill(folder) for folder in sorted(p for p in self.skills_dir.iterdir()
                                                           if p.is_dir() or p.is_symlink())]
        with self.store.write() as conn:
            for s in found:
                row = conn.execute("SELECT body_sha256, metadata_json FROM skills WHERE name = ? AND version = ?",
                                   (s.name, s.version)).fetchone()
                if row is not None:
                    stored = json.loads(row["metadata_json"])
                    if row["body_sha256"] != s.body_sha256 or stored.get("package_sha256") != s.package_sha256:
                        raise SkillIntegrityError(f"{s.name}@{s.version} changed without a version bump")
                    continue
                conn.execute(
                    "INSERT INTO skills(name, version, description, metadata_json, body, body_sha256, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (s.name, s.version, s.description,
                     json.dumps({"owner": s.owner, "package_sha256": s.package_sha256,
                                 "source": f"skills/{s.name}/SKILL.md"}, sort_keys=True),
                     s.body, s.body_sha256, utc_now_iso()))
        self._skills = {(s.name, s.version): s for s in found}
        return self.list()

    def list(self) -> list[dict[str, Any]]:
        return [s.summary() for _, s in sorted(self._skills.items())]

    def get(self, name: str, version: str) -> Skill | None:
        return self._skills.get((name, version))
