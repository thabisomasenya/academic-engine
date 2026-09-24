from engine.models.paper import Paper, normalize_doi
from engine.sources.openalex import parse_work, reconstruct_abstract
from engine.storage.db import Store


def test_reconstruct_abstract():
    inv = {"Deep": [0], "learning": [1, 4], "is": [2], "powerful": [3]}
    assert reconstruct_abstract(inv) == "Deep learning is powerful learning"
    assert reconstruct_abstract(None) is None


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert normalize_doi("doi:10.1000/abc") == "10.1000/abc"
    assert normalize_doi(None) is None


def test_parse_work_skips_untitled():
    assert parse_work({"id": "https://openalex.org/W1", "title": None}) is None


def test_parse_and_store_roundtrip(tmp_path):
    raw = {
        "id": "https://openalex.org/W42", "doi": "https://doi.org/10.1/X",
        "title": "Drought  stress detection", "publication_year": 2024,
        "abstract_inverted_index": {"Early": [0], "warning": [1], "systems": [2]},
        "authorships": [{"author": {"id": "https://openalex.org/A1", "display_name": "A. Author"},
                         "institutions": [{"display_name": "Uni"}]}],
        "referenced_works": ["https://openalex.org/W7"], "cited_by_count": 3,
        "primary_location": {"source": {"display_name": "Journal"}},
        "open_access": {"oa_url": "http://x/pdf"}, "topics": [{"display_name": "Agronomy"}],
    }
    paper = parse_work(raw)
    assert paper and paper.title == "Drought stress detection" and paper.references == ["W7"]
    store = Store(tmp_path / "t.db")
    assert store.upsert([paper]) == 1
    assert store.upsert([paper]) == 1            # idempotent
    assert store.stats() == {"papers": 1, "with_abstract": 1, "citation_edges": 1}
    hits = store.search("early warning")
    assert len(hits) == 1 and hits[0]["id"] == "W42"


def test_duplicate_doi_is_skipped(tmp_path):
    store = Store(tmp_path / "t.db")
    a = Paper(id="W1", doi="10.1/x", title="One")
    b = Paper(id="W2", doi="https://doi.org/10.1/X", title="One again")
    store.upsert([a])
    assert store.upsert([b]) == 0
    assert store.stats()["papers"] == 1
