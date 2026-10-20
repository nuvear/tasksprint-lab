"""Approved-knowledge retrieval (A7; Build Guide 04.2/04.4; AE-01/AE-02 back end)."""
from __future__ import annotations

import hashlib
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from services.lab import clock, frontmatter
from services.lab.config import REPO_ROOT
from services.lab.retrieval import KnowledgeBase, KnowledgeIntegrityError, chunk_markdown, query_terms
from services.lab.store import Store
from tests.conftest import headers

KIT_DOCS = {"tasksprint-product-brief", "tasksprint-definition-of-done", "tasksprint-release-policy",
            "tasksprint-early-design-note"}
ARCHIVED = "tasksprint-early-design-note"
CITATION_KEYS = {"doc_id", "version", "section", "owner", "hash"}


def search(lab, query: str, role: str = "product_owner"):
    return lab.client.post("/v1/knowledge/search", json={"query": query}, headers=headers(role))


def doc_ids(result) -> set[str]:
    return {r["citation"]["doc_id"] for r in result["results"]}


def write_doc(folder: Path, name: str, doc_id: str, version: str, status: str, body: str,
              effective_from: str = "2026-10-01", effective_to: str | None = None) -> Path:
    fm = [f"id: {doc_id}", f'version: "{version}"', f"status: {status}", f'effective_from: "{effective_from}"']
    if effective_to:
        fm.append(f'effective_to: "{effective_to}"')
    fm.append("owner: Test owner")
    p = folder / name
    p.write_text("---\n" + "\n".join(fm) + "\n---\n" + body, encoding="utf-8")
    return p


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    d = tmp_path / "knowledge"
    d.mkdir()
    for p in (REPO_ROOT / "knowledge").glob("*.md"):
        shutil.copy(p, d / p.name)
    return d


def kb_for(tmp_path: Path, folder: Path) -> KnowledgeBase:
    kb = KnowledgeBase(Store(str(tmp_path / "kb.sqlite3")), folder)
    kb.store.migrate()
    kb.ingest()
    return kb


# ------------------------------------------------------------------ ingestion
def test_frontmatter_reader_accepts_kit_subset_and_refuses_other_yaml():
    meta, body = frontmatter.split('---\nid: x\nversion: "1.0"\nmetadata:\n  version: "2"\n---\n# T\n')
    assert meta == {"id": "x", "version": "1.0", "metadata": {"version": "2"}} and body == "# T\n"
    for bad in ("no frontmatter", "---\nid: x\n", "---\nid: [a, b]\n---\n", "---\nid: x\nid: y\n---\n",
                "---\n  orphan: 1\n---\n"):
        with pytest.raises(frontmatter.FrontmatterError):
            frontmatter.split(bad)


def test_ingests_only_the_four_knowledge_files_with_metadata(seeded):
    with seeded.store().read() as conn:
        docs = {r["doc_id"]: dict(r) for r in conn.execute("SELECT * FROM documents")}
        chunks = conn.execute("SELECT * FROM chunks").fetchall()
        fts = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    assert set(docs) == KIT_DOCS
    assert docs[ARCHIVED]["status"] == "archived" and docs[ARCHIVED]["effective_to"] == "2026-09-30"
    assert {d["status"] for k, d in docs.items() if k != ARCHIVED} == {"approved"}
    for p in (REPO_ROOT / "knowledge").glob("*.md"):
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        assert sha in {d["content_sha256"] for d in docs.values()}, p.name
    assert fts == len(chunks) and len(chunks) >= 15
    for c in chunks:
        assert hashlib.sha256(f"{c['section']}\n{c['chunk_text']}".encode()).hexdigest() == c["content_sha256"]
        # Nothing from instructor fixtures, tests or source code reaches the corpus.
        assert "def complete" not in c["chunk_text"] and "FIXTURE" not in c["chunk_text"]


def test_chunking_is_by_section_and_keeps_title_preamble():
    title, chunks = chunk_markdown("# Title\nintro line\n\n## A\nalpha\n## B\nbeta\n")
    assert title == "Title" and [(c.section, c.text) for c in chunks] == [("Title", "intro line"), ("A", "alpha"),
                                                                         ("B", "beta")]


def test_reingest_is_idempotent(seeded):
    before = seeded.store().read
    kb = seeded.app.state.ops.knowledge
    assert kb.ingest()["documents_added"] == 0
    with before() as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 4


def test_changed_document_without_version_bump_refuses(tmp_path, corpus):
    kb = kb_for(tmp_path, corpus)
    p = corpus / "01_product_brief.md"
    p.write_text(p.read_text().replace("track a short list", "track a long list"))
    with pytest.raises(KnowledgeIntegrityError, match="without a version bump"):
        kb.ingest()


def test_symlink_and_malformed_files_are_refused(tmp_path, corpus):
    (corpus / "link.md").symlink_to(corpus / "01_product_brief.md")
    with pytest.raises(KnowledgeIntegrityError):
        kb_for(tmp_path, corpus)
    (corpus / "link.md").unlink()
    (corpus / "bad.md").write_text("# no frontmatter\n")
    with pytest.raises(KnowledgeIntegrityError):
        kb_for(tmp_path, corpus)


def test_non_markdown_files_and_subfolders_are_ignored(tmp_path, corpus):
    (corpus / "notes.txt").write_text("secret-ish text delete completed tasks")
    (corpus / "sub").mkdir()
    write_doc(corpus / "sub", "x.md", "nested-doc", "1.0", "approved", "# N\n## S\ndelete everything\n")
    kb = kb_for(tmp_path, corpus)
    assert {d.doc_id for d in kb.documents} == KIT_DOCS


# ------------------------------------------------------------------ query time
def test_query_terms_drop_stopwords_and_punctuation():
    assert query_terms("What is the DELETE; policy for completed tasks?") == ["delete", "policy", "completed", "tasks"]
    assert query_terms("the and of ?!") == []


def test_archived_delete_guidance_is_excluded_from_normal_search(seeded):
    for q in ("delete completed tasks", "remove a task from storage when marked complete",
              "early design idea removing task"):
        r = search(seeded, q)
        assert r.status_code == 200
        body = r.json()
        assert ARCHIVED not in doc_ids(body), q
        assert all(x["document"]["status"] == "approved" for x in body["results"])
        assert body["filter"]["mode"] == "current" and body["filter"]["status"] == ["approved"]


def test_instructor_can_show_the_archived_note_with_the_filter_off(seeded):
    q = {"query": "remove a task from storage when marked complete", "include_archived": True}
    r = seeded.client.post("/v1/instructor/knowledge/search", json=q, headers=headers("instructor", None))
    assert r.status_code == 200
    body = r.json()
    assert ARCHIVED in doc_ids(body)
    archived = next(x for x in body["results"] if x["citation"]["doc_id"] == ARCHIVED)
    assert archived["document"]["status"] == "archived" and archived["citation"]["version"] == "0.1"
    assert body["filter"]["mode"] == "instructor-include-archived"
    # Non-instructors cannot use the unfiltered route.
    for role in ("product_owner", "developer", "coordinator", "operations", "qa"):
        assert seeded.client.post("/v1/instructor/knowledge/search", json=q,
                                  headers=headers(role)).status_code == 403


def test_current_retention_passage_is_returned_and_cited(seeded):
    body = search(seeded, "retain completed task records in the list").json()
    assert body["status"] == "ok" and 1 <= len(body["results"]) <= 3
    top = body["results"][0]
    assert set(top["citation"]) == CITATION_KEYS
    assert top["citation"]["doc_id"] == "tasksprint-product-brief" and top["citation"]["version"] == "1.0"
    assert top["citation"]["section"] in {"Completion story", "Acceptance criteria"}
    assert "retaining it" in top["text"] or "remains stored" in top["text"]
    with seeded.store().read() as conn:
        row = conn.execute("SELECT content_sha256 FROM chunks WHERE doc_id = ? AND section = ?",
                           (top["citation"]["doc_id"], top["citation"]["section"])).fetchone()
    assert row["content_sha256"] == top["citation"]["hash"]


def test_results_are_bounded_to_three_relevant_chunks(seeded):
    body = search(seeded, "task release approval plan test evidence rollback health").json()
    assert len(body["results"]) == 3
    assert [x["rank"] for x in body["results"]] == [1, 2, 3]


def test_nonsense_and_empty_queries_abstain(seeded):
    body = search(seeded, "zebra quantum saxophone marmalade").json()
    assert body["status"] == "abstain" and body["results"] == []
    assert body["abstention"]["code"] == "NO_APPROVED_EVIDENCE"
    assert search(seeded, "what is the?").json()["abstention"]["code"] == "QUERY_EMPTY"


def test_search_records_a_retrieval_event_with_citations(seeded):
    body = search(seeded, "unknown task id error").json()
    with seeded.store().read() as conn:
        ev = conn.execute("SELECT * FROM events WHERE event_id = ?", (body["event_id"],)).fetchone()
    assert ev["action"] == "knowledge.search" and ev["actor_role"] == "product_owner" and ev["outcome"] == "ok"
    assert "tasksprint-product-brief@1.0#Acceptance criteria" in ev["details_json"]


def test_search_is_role_scoped(seeded):
    assert search(seeded, "release", role="developer").status_code == 200
    for role in ("qa", "operations", "coordinator", "application", "human_approver", "evaluator"):
        assert search(seeded, "release", role=role).status_code == 403, role
    assert seeded.client.post("/v1/knowledge/search", json={"query": "x"}, headers=headers(None)).status_code == 401
    r = seeded.client.post("/v1/knowledge/search", json={"query": "x", "include_archived": True},
                           headers=headers("product_owner"))
    assert r.status_code == 422  # the archive switch does not exist on the normal route


def test_effective_dates_are_enforced(tmp_path, corpus):
    write_doc(corpus, "50_future.md", "future-policy", "1.0", "approved",
              "# Future\n## Zeppelin rule\nZeppelin deliveries are allowed.\n", effective_from="2099-01-01")
    write_doc(corpus, "51_expired.md", "expired-policy", "1.0", "approved",
              "# Old\n## Zeppelin legacy\nZeppelin deliveries were banned.\n", effective_from="2020-01-01",
              effective_to="2020-12-31")
    kb = kb_for(tmp_path, corpus)
    with kb.store.read() as conn:
        assert kb.search(conn, "zeppelin deliveries")["abstention"]["code"] == "NO_APPROVED_EVIDENCE"
    clock.advance_for_tests(timedelta(days=365 * 80))
    with kb.store.read() as conn:
        assert {r["citation"]["doc_id"] for r in kb.search(conn, "zeppelin deliveries")["results"]} == {"future-policy"}


def test_two_current_approved_versions_conflict_and_abstain(tmp_path, corpus):
    write_doc(corpus, "60_v1.md", "zeppelin-policy", "1.0", "approved", "# Z\n## Rule\nZeppelins keep tasks.\n")
    write_doc(corpus, "61_v2.md", "zeppelin-policy", "2.0", "approved", "# Z\n## Rule\nZeppelins delete tasks.\n")
    kb = kb_for(tmp_path, corpus)
    with kb.store.read() as conn:
        body = kb.search(conn, "zeppelins")
    assert body["status"] == "abstain" and body["abstention"]["code"] == "CONFLICTING_EVIDENCE"
    assert "zeppelin-policy" in body["abstention"]["reason"]


def test_removed_file_leaves_the_current_corpus(tmp_path, corpus):
    write_doc(corpus, "70_temp.md", "temp-policy", "1.0", "approved", "# T\n## Rule\nZeppelin rule here.\n")
    kb = kb_for(tmp_path, corpus)
    (corpus / "70_temp.md").unlink()
    kb.ingest()
    with kb.store.read() as conn:
        assert kb.search(conn, "zeppelin")["status"] == "abstain"


def test_missing_corpus_folder_refuses_instead_of_serving_nothing(tmp_path):
    store = Store(str(tmp_path / "kb.sqlite3"))
    store.migrate()
    with pytest.raises(KnowledgeIntegrityError, match="missing"):
        KnowledgeBase(store, tmp_path / "nope").ingest()


def test_lab_image_ships_only_corpus_skills_and_code():
    text = (REPO_ROOT / "Dockerfile.lab").read_text()
    copies = [line.split()[1] for line in text.splitlines() if line.startswith("COPY ") and "--from" not in line]
    assert "knowledge/" in copies and "skills/" in copies
    assert "." not in copies and not any(c.startswith(("tests", "docs", ".local", "langflow")) for c in copies)
