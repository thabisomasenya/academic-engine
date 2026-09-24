"""Command-line entry point. Every command is idempotent: re-running is always safe."""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from dotenv import load_dotenv

from engine.sources.openalex import OpenAlexClient
from engine.storage.db import Store

load_dotenv()
app = typer.Typer(help="Academic metadata engine")
DB = "data/clean/engine.db"


@app.command()
def ingest(query: str, max_results: int = 200) -> None:
    """Fetch papers from OpenAlex and store them."""
    async def run() -> int:
        papers = []
        async with OpenAlexClient(raw_dir=Path("data/raw")) as client:
            async for paper in client.search(query, max_results):
                papers.append(paper)
        return Store(DB).upsert(papers)

    n = asyncio.run(run())
    typer.echo(f"Stored {n} papers. {Store(DB).stats()}")


@app.command()
def search(query: str, limit: int = 10) -> None:
    """Keyword (BM25) search over stored papers."""
    for r in Store(DB).search(query, limit):
        typer.echo(f"{r['year']}  {r['title']}  [{r['cited_by_count']} cites]")


@app.command()
def stats() -> None:
    """Show what is in the database."""
    typer.echo(Store(DB).stats())


if __name__ == "__main__":
    app()
