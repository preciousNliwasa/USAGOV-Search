"""Data models returned by the library."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Result:
    """A single search result."""

    rank: int
    title: str
    url: str
    display_url: str
    snippet: str


@dataclass
class ExtractedPage:
    """Content and metadata extracted from a result page."""

    rank: int
    requested_url: str
    final_url: str
    title: str
    h1: str
    description: str
    canonical: str
    last_updated: str
    headings: list[dict[str, str]] = field(default_factory=list)
    text: str = ""
    html_file: str | None = None


@dataclass
class SearchResponse:
    """Everything produced by a search request."""

    query: str
    lang: str
    affiliate: str
    total: int | None
    results: list[Result]
    extracted: list[ExtractedPage] = field(default_factory=list)
    saved_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def returned(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["returned"] = self.returned
        return data
