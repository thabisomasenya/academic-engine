"""OpenAlex client: free, no API key, returns citations + abstracts + open-access links."""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from aiolimiter import AsyncLimiter
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from engine.models.paper import Author, Paper

BASE_URL = "https://api.openalex.org/works"
SELECT = ",".join([
    "id", "doi", "title", "publication_year", "abstract_inverted_index", "authorships",
    "referenced_works", "cited_by_count", "primary_location", "open_access", "topics",
])


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}. Rebuild the plain text."""
    if not inverted:
        return None
    slots: dict[int, str] = {}
    for word, positions in inverted.items():
        for pos in positions:
            slots[pos] = word
    return " ".join(slots[i] for i in sorted(slots)) or None


def _short_id(url: str | None) -> str | None:
    return url.rsplit("/", 1)[-1] if url else None


def parse_work(work: dict) -> Paper | None:
    """Turn one raw OpenAlex work into a validated Paper. Returns None if unusable."""
    title = work.get("title")
    wid = _short_id(work.get("id"))
    if not title or not wid:
        return None
    authors = [
        Author(
            id=_short_id((a.get("author") or {}).get("id")),
            name=(a.get("author") or {}).get("display_name") or "Unknown",
            institutions=[i["display_name"] for i in a.get("institutions", []) if i.get("display_name")],
        )
        for a in work.get("authorships", [])
    ]
    source = ((work.get("primary_location") or {}).get("source") or {})
    return Paper(
        id=wid,
        doi=work.get("doi"),
        title=title,
        abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
        year=work.get("publication_year"),
        venue=source.get("display_name"),
        authors=authors,
        references=[_short_id(r) for r in work.get("referenced_works", []) if r],
        cited_by_count=work.get("cited_by_count") or 0,
        topics=[t["display_name"] for t in work.get("topics", []) if t.get("display_name")],
        oa_url=(work.get("open_access") or {}).get("oa_url"),
    )


class OpenAlexClient:
    def __init__(self, mailto: str | None = None, raw_dir: Path | None = None, rps: float = 8.0):
        self.mailto = mailto or os.getenv("OPENALEX_MAILTO")
        self.raw_dir = raw_dir
        self._limiter = AsyncLimiter(max_rate=rps, time_period=1)  # stay under the rate limit
        self._client = httpx.AsyncClient(timeout=30)

    async def __aenter__(self) -> "OpenAlexClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _get(self, params: dict) -> dict:
        async with self._limiter:
            resp = await self._client.get(BASE_URL, params=params)
        resp.raise_for_status()              # 429/5xx raise here and trigger a backoff retry
        return resp.json()

    async def search(self, query: str, max_results: int = 200) -> AsyncIterator[Paper]:
        """Cursor-paginate through search results, yielding validated Papers."""
        cursor, fetched, page_no = "*", 0, 0
        while cursor and fetched < max_results:
            params = {
                "search": query, "per-page": min(100, max_results - fetched),
                "cursor": cursor, "select": SELECT,
            }
            if self.mailto:
                params["mailto"] = self.mailto
            data = await self._get(params)
            results = data.get("results", [])
            if not results:
                break
            self._save_raw(query, page_no, results)
            for work in results:
                paper = parse_work(work)
                if paper is None:
                    logger.warning("Skipping unusable record: {}", work.get("id"))
                    continue
                fetched += 1
                yield paper
            cursor = (data.get("meta") or {}).get("next_cursor")
            page_no += 1

    def _save_raw(self, query: str, page_no: int, results: list[dict]) -> None:
        """Bronze layer: keep the untouched response so we can re-parse without re-fetching."""
        if not self.raw_dir:
            return
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() else "_" for c in query)[:40]
        (self.raw_dir / f"openalex_{slug}_{page_no:03d}.json").write_text(json.dumps(results))
