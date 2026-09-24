"""SQLite storage with FTS5 full-text (BM25) search. Idempotent upserts, WAL mode."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.models.paper import Paper

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    doi TEXT,
    title TEXT NOT NULL,
    abstract TEXT,
    year INTEGER,
    venue TEXT,
    authors TEXT NOT NULL DEFAULT '[]',
    topics TEXT NOT NULL DEFAULT '[]',
    cited_by_count INTEGER NOT NULL DEFAULT 0,
    oa_url TEXT,
    source TEXT NOT NULL DEFAULT 'openalex'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi) WHERE doi IS NOT NULL;
CREATE TABLE IF NOT EXISTS citations (
    citing_id TEXT NOT NULL,
    cited_id  TEXT NOT NULL,
    PRIMARY KEY (citing_id, cited_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    title, abstract, content='papers', content_rowid='rowid', tokenize='porter unicode61'
);
"""


class Store:
    def __init__(self, path: str | Path = "data/clean/engine.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def upsert(self, papers: list[Paper]) -> int:
        """Insert or update papers, their citation edges, and the search index."""
        n = 0
        with self.conn:
            for p in papers:
                existing = self.conn.execute(
                    "SELECT id FROM papers WHERE id = ? OR (doi IS NOT NULL AND doi = ?)",
                    (p.id, p.doi),
                ).fetchone()
                if existing and existing["id"] != p.id:
                    continue  # same DOI already stored under another id: dedupe by DOI
                self.conn.execute(
                    """INSERT INTO papers (id, doi, title, abstract, year, venue, authors, topics,
                                           cited_by_count, oa_url, source)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         doi=excluded.doi, title=excluded.title, abstract=excluded.abstract,
                         year=excluded.year, venue=excluded.venue, authors=excluded.authors,
                         topics=excluded.topics, cited_by_count=excluded.cited_by_count,
                         oa_url=excluded.oa_url""",
                    (p.id, p.doi, p.title, p.abstract, p.year, p.venue,
                     json.dumps([a.model_dump() for a in p.authors]), json.dumps(p.topics),
                     p.cited_by_count, p.oa_url, p.source),
                )
                self.conn.executemany(
                    "INSERT OR IGNORE INTO citations (citing_id, cited_id) VALUES (?,?)",
                    [(p.id, ref) for ref in p.references],
                )
                n += 1
            self.conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")
        return n

    def search(self, query: str, limit: int = 10) -> list[sqlite3.Row]:
        """BM25-ranked keyword search over titles and abstracts."""
        terms = " ".join(f'"{t}"' for t in query.replace('"', " ").split())
        return self.conn.execute(
            """SELECT p.id, p.title, p.year, p.venue, p.cited_by_count, p.doi,
                      bm25(papers_fts) AS score
               FROM papers_fts JOIN papers p ON p.rowid = papers_fts.rowid
               WHERE papers_fts MATCH ? ORDER BY score LIMIT ?""",
            (terms, limit),
        ).fetchall()

    def stats(self) -> dict[str, int]:
        one = lambda q: self.conn.execute(q).fetchone()[0]  # noqa: E731
        return {
            "papers": one("SELECT COUNT(*) FROM papers"),
            "with_abstract": one("SELECT COUNT(*) FROM papers WHERE abstract IS NOT NULL"),
            "citation_edges": one("SELECT COUNT(*) FROM citations"),
        }
