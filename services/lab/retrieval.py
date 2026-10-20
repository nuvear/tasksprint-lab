"""Approved-knowledge retrieval (Architecture A7).

Corpus: ONLY the top-level ``knowledge/*.md`` files (regular files, no symlinks,
no recursion). Nothing else in the repository is ever read here.

Metadata convention (read from each file's YAML frontmatter, which all four kit
files carry): ``id``, ``version``, ``status`` (approved | archived | draft),
``effective_from`` and optional ``effective_to`` (ISO dates, inclusive), ``owner``,
optional ``superseded_by``. Headings are not used to infer status: a file without
valid frontmatter is refused at start-up instead of being guessed at.

Chunking: one chunk per ``## `` section; text between the ``# `` title and the
first ``## `` becomes a chunk named after the title (the archived note has only
that). Each chunk stores its own SHA-256; each document stores the file's SHA-256.
Documents and chunks are append-only: a changed file must carry a new version, or
the service refuses to start (``KnowledgeIntegrityError``).

Query time: SQLite FTS5 (``porter unicode61``) with bm25 ranking. The approved and
currently-effective filter (and "present in the current corpus") is part of the
same SQL ``WHERE`` clause as the ``MATCH``, so archived or expired text never
takes part in ranking. Top three chunks, each with a citation
``{doc_id, version, section, owner, hash}``. No match, an empty query or two
approved current versions of the same document produce an explicit abstention.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from . import frontmatter
from .clock import utc_now, utc_now_iso
from .store import Store

MAX_FILE_BYTES = 64 * 1024
MAX_RESULTS = 3
MAX_QUERY_TERMS = 16
STATUSES = ("approved", "archived", "draft")
_DOC_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_VERSION = re.compile(r"^[0-9][0-9A-Za-z.\-]{0,15}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TERM = re.compile(r"[a-z0-9]+")
# Small English stop list so filler words alone cannot produce "evidence".
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i if in into is it its me my of on or our "
    "should so that the their them then there these this to us was we what when where which who why will "
    "with you your".split())


class KnowledgeIntegrityError(RuntimeError):
    """A knowledge file is malformed or changed without a version bump."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Chunk:
    section: str
    text: str

    @property
    def sha256(self) -> str:
        return sha256_text(f"{self.section}\n{self.text}")


@dataclass(frozen=True)
class Document:
    doc_id: str
    version: str
    status: str
    effective_from: str
    effective_to: str | None
    owner: str
    title: str
    sha256: str
    source_name: str
    chunks: tuple[Chunk, ...]


def chunk_markdown(body: str) -> tuple[str, list[Chunk]]:
    title = ""
    chunks: list[Chunk] = []
    section: str | None = None
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            chunks.append(Chunk(section or title or "(untitled)", text))

    for line in body.splitlines():
        if line.startswith("# ") and not title and section is None and not "".join(buf).strip():
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            flush()
            section, buf = line[3:].strip(), []
            continue
        buf.append(line)
    flush()
    return title, chunks


def parse_document(path: Path) -> Document:
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise KnowledgeIntegrityError(f"{path.name}: larger than {MAX_FILE_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
        meta, body = frontmatter.split(text)
    except (UnicodeDecodeError, frontmatter.FrontmatterError) as exc:
        raise KnowledgeIntegrityError(f"{path.name}: {exc}") from None
    doc_id, version, status = str(meta.get("id", "")), str(meta.get("version", "")), str(meta.get("status", ""))
    eff_from, eff_to, owner = str(meta.get("effective_from", "")), meta.get("effective_to"), str(meta.get("owner", ""))
    if not _DOC_ID.match(doc_id) or not _VERSION.match(version):
        raise KnowledgeIntegrityError(f"{path.name}: id/version missing or malformed")
    if status not in STATUSES:
        raise KnowledgeIntegrityError(f"{path.name}: status must be one of {STATUSES}")
    for value in (eff_from, eff_to):
        if value is not None and (not isinstance(value, str) or not _DATE.match(value)):
            raise KnowledgeIntegrityError(f"{path.name}: effective dates must be YYYY-MM-DD")
        if value is not None:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise KnowledgeIntegrityError(f"{path.name}: invalid effective date") from None
    if eff_to is not None and str(eff_to) < eff_from:
        raise KnowledgeIntegrityError(f"{path.name}: effective_to precedes effective_from")
    if not owner or len(owner) > 120:
        raise KnowledgeIntegrityError(f"{path.name}: owner missing")
    title, chunks = chunk_markdown(body)
    if not chunks:
        raise KnowledgeIntegrityError(f"{path.name}: no content")
    return Document(doc_id, version, status, eff_from, str(eff_to) if eff_to else None, owner, title or doc_id,
                    hashlib.sha256(raw).hexdigest(), path.name, tuple(chunks))


def discover(knowledge_dir: Path) -> list[Path]:
    """Top-level regular ``*.md`` files only; symlinks and anything outside the folder are refused."""
    root = knowledge_dir.resolve()
    paths: list[Path] = []
    for p in sorted(knowledge_dir.iterdir()):
        if p.suffix != ".md":
            continue
        if p.is_symlink() or not p.is_file() or p.resolve().parent != root:
            raise KnowledgeIntegrityError(f"{p.name}: not a regular file inside knowledge/")
        paths.append(p)
    return paths


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for t in _TERM.findall(query.lower()):
        if len(t) >= 2 and t not in STOPWORDS and t not in terms:
            terms.append(t)
    return terms[:MAX_QUERY_TERMS]


class KnowledgeBase:
    def __init__(self, store: Store, knowledge_dir: Path | str):
        self.store = store
        self.knowledge_dir = Path(knowledge_dir)
        self.documents: tuple[Document, ...] = ()
        self._active_keys: tuple[str, ...] = ()
        self.manifest_sha256 = ""

    # ------------------------------------------------------------- ingestion
    def ingest(self) -> dict[str, Any]:
        if not self.knowledge_dir.is_dir():
            raise KnowledgeIntegrityError("knowledge/ folder is missing; refusing to serve an empty corpus")
        docs = [parse_document(p) for p in discover(self.knowledge_dir)]
        keys = [f"{d.doc_id}@{d.version}" for d in docs]
        if len(set(keys)) != len(keys):
            raise KnowledgeIntegrityError("two knowledge files declare the same id and version")
        added = 0
        with self.store.write() as conn:
            for d in docs:
                row = conn.execute("SELECT content_sha256 FROM documents WHERE doc_id = ? AND version = ?",
                                   (d.doc_id, d.version)).fetchone()
                if row is not None:
                    if row["content_sha256"] != d.sha256:
                        raise KnowledgeIntegrityError(
                            f"{d.source_name}: {d.doc_id}@{d.version} changed without a version bump")
                    continue
                now = utc_now_iso()
                conn.execute(
                    "INSERT INTO documents(doc_id, version, status, effective_from, effective_to, owner, title,"
                    " content_sha256, ingested_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (d.doc_id, d.version, d.status, d.effective_from, d.effective_to, d.owner, d.title, d.sha256, now))
                for i, ch in enumerate(d.chunks):
                    cur = conn.execute(
                        "INSERT INTO chunks(chunk_id, doc_id, version, section, chunk_text, content_sha256)"
                        " VALUES (?,?,?,?,?,?)",
                        (f"{d.doc_id}@{d.version}#{i + 1:02d}", d.doc_id, d.version, ch.section, ch.text, ch.sha256))
                    conn.execute("INSERT INTO chunks_fts(rowid, section, chunk_text) VALUES (?,?,?)",
                                 (cur.lastrowid, ch.section, ch.text))
                added += 1
        self.documents = tuple(docs)
        self._active_keys = tuple(sorted(keys))
        self.manifest_sha256 = sha256_text("\n".join(sorted(f"{d.doc_id}@{d.version}:{d.sha256}" for d in docs)))
        return self.manifest(added=added)

    def manifest(self, added: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "manifest_sha256": self.manifest_sha256,
            "documents": [{"doc_id": d.doc_id, "version": d.version, "status": d.status, "sha256": d.sha256,
                           "chunks": len(d.chunks)} for d in self.documents],
        }
        if added is not None:
            out["documents_added"] = added
        return out

    # ------------------------------------------------------------- query time
    def search(self, conn: sqlite3.Connection, query: str, *, include_archived: bool = False) -> dict[str, Any]:
        today = utc_now().date().isoformat()
        terms = query_terms(query)
        base = {
            "query_terms": terms,
            "filter": ({"status": ["approved", "archived"], "effective_on": None, "mode": "instructor-include-archived"}
                       if include_archived else {"status": ["approved"], "effective_on": today, "mode": "current"}),
            "corpus_manifest_sha256": self.manifest_sha256,
        }
        if not terms:
            return {**base, **_abstain("QUERY_EMPTY", "the query has no searchable terms")}
        if not self._active_keys:
            return {**base, **_abstain("NO_APPROVED_EVIDENCE", "the knowledge corpus is empty")}
        match = " OR ".join(f'"{t}"' for t in terms)  # terms are [a-z0-9]+ only
        keys = ",".join("?" for _ in self._active_keys)
        where = [f"(c.doc_id || '@' || c.version) IN ({keys})"]
        params: list[Any] = [match, *self._active_keys]
        if include_archived:
            where.append("d.status IN ('approved','archived')")
        else:
            where.append("d.status = 'approved' AND d.effective_from <= ? AND (d.effective_to IS NULL OR d.effective_to >= ?)")
            params += [today, today]
        rows = conn.execute(
            "SELECT c.chunk_id, c.doc_id, c.version, c.section, c.chunk_text, c.content_sha256, d.status,"
            " d.effective_from, d.effective_to, d.owner, d.title, d.content_sha256 AS doc_sha256,"
            " bm25(chunks_fts, 4.0, 1.0) AS score"
            " FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid"
            " JOIN documents d ON d.doc_id = c.doc_id AND d.version = c.version"
            f" WHERE chunks_fts MATCH ? AND {' AND '.join(where)}"
            " ORDER BY score, c.chunk_id LIMIT ?",
            (*params, MAX_RESULTS)).fetchall()
        if not rows:
            return {**base, **_abstain("NO_APPROVED_EVIDENCE", "no approved, currently effective passage matches")}
        if not include_archived:
            conflicted = self._conflicting_doc_ids(conn, today)
            hit = sorted({r["doc_id"] for r in rows} & conflicted)
            if hit:
                return {**base, **_abstain("CONFLICTING_EVIDENCE",
                                           "more than one approved current version exists for: " + ", ".join(hit))}
        results = []
        for rank, r in enumerate(rows, start=1):
            results.append({
                "rank": rank,
                "text": r["chunk_text"],
                "score": round(-float(r["score"]), 4),
                "citation": {"doc_id": r["doc_id"], "version": r["version"], "section": r["section"],
                             "owner": r["owner"], "hash": r["content_sha256"]},
                "chunk_id": r["chunk_id"],
                "document": {"title": r["title"], "status": r["status"], "effective_from": r["effective_from"],
                             "effective_to": r["effective_to"], "sha256": r["doc_sha256"]},
            })
        return {**base, "status": "ok", "results": results, "abstention": None}

    def _conflicting_doc_ids(self, conn: sqlite3.Connection, today: str) -> set[str]:
        keys = ",".join("?" for _ in self._active_keys)
        rows = conn.execute(
            "SELECT doc_id FROM documents WHERE status = 'approved' AND effective_from <= ?"
            " AND (effective_to IS NULL OR effective_to >= ?)"
            f" AND (doc_id || '@' || version) IN ({keys}) GROUP BY doc_id HAVING COUNT(*) > 1",
            (today, today, *self._active_keys)).fetchall()
        return {r["doc_id"] for r in rows}


def _abstain(code: str, reason: str) -> dict[str, Any]:
    return {"status": "abstain", "results": [],
            "abstention": {"code": code, "reason": reason,
                           "instruction": "Do not answer from memory; report the evidence gap and stop."}}


def citation_refs(result: dict[str, Any]) -> list[str]:
    return [f"{r['citation']['doc_id']}@{r['citation']['version']}#{r['citation']['section']}"
            for r in result.get("results", [])]
