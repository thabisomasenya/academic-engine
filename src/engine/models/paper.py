"""Canonical data models. Every source is normalised into these before storage."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


def normalize_doi(doi: str | None) -> str | None:
    """Lower-case a DOI and strip URL prefixes so the same paper always matches."""
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:", "", doi)
    return doi or None


class Author(BaseModel):
    id: str | None = None
    name: str
    institutions: list[str] = Field(default_factory=list)


class Paper(BaseModel):
    id: str                                   # source-native id, e.g. OpenAlex W123
    source: str = "openalex"
    doi: str | None = None
    title: str
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    authors: list[Author] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)   # ids of cited works
    cited_by_count: int = 0
    topics: list[str] = Field(default_factory=list)
    oa_url: str | None = None

    @field_validator("doi")
    @classmethod
    def _clean_doi(cls, v: str | None) -> str | None:
        return normalize_doi(v)

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v: str) -> str:
        return re.sub(r"\s+", " ", v).strip()
