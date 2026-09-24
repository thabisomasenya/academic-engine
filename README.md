# Academic engine

Free, local-first pipeline: ingest papers from OpenAlex, store them in SQLite, search them with BM25.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # put your email in OPENALEX_MAILTO
pytest
```

## Try it
```bash
engine ingest "plant drought stress detection" --max-results 200
engine search "early warning"
engine stats
```
