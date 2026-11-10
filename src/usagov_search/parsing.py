"""Parsing helpers shared by the client and CLI."""

from __future__ import annotations

import re

COUNT_RE = re.compile(r"([\d.,]+)\s+(?:results|resultados)", re.I)


def clean(text: str | None) -> str:
    """Collapse whitespace to single spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_block(text: str | None) -> str:
    """Normalize line endings and collapse excessive blank lines."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_total(text: str) -> int | None:
    """Read a result count such as ``31 results`` or ``26 resultados``."""
    match = COUNT_RE.search(text)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    return int(digits) if digits else None


def parse_extract_values(values: list[str] | None) -> list[int]:
    """Turn CLI rank specs into sorted, unique 1-based indices.

    Examples:
        >>> parse_extract_values(None)
        []
        >>> parse_extract_values(["1"])
        [1]
        >>> parse_extract_values(["1,3"])
        [1, 3]
        >>> parse_extract_values(["1-3"])
        [1, 2, 3]
        >>> parse_extract_values(["1-3", "2,5"])
        [1, 2, 3, 5]
    """
    indices: set[int] = set()
    for raw in values or []:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s), int(end_s)
                if start > end:
                    raise ValueError(f"invalid range '{part}'")
                indices.update(range(start, end + 1))
            else:
                indices.add(int(part))
    if any(i < 1 for i in indices):
        raise ValueError("extract indices must be >= 1")
    return sorted(indices)


def slugify(text: str, max_len: int = 60) -> str:
    """Build a filesystem-safe slug from text."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug[:max_len].rstrip("-") or "page"
