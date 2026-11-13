"""Search USA.gov and extract page content.

Library usage::

    from usagov_search import USAgovAgent

    agent = USAgovAgent()  # reads GROQ_API_KEY
    answer = agent.ask("What do I need to renew a passport?")
    print(answer.text)
    for source in answer.sources:
        print(source.index, source.url)

CLI usage::

    usagov-search "passport" --extract 1
    usagov-ask "What do I need to renew a passport?"
    python -m usagov_search "passport" --json
"""

from __future__ import annotations

from .agent import AgentAnswer, AgentSource, USAgovAgent
from .client import fetch_page, save_html, search
from .models import ExtractedPage, Result, SearchResponse
from .parsing import parse_extract_values

__version__ = "0.2.5"

__all__ = [
    "AgentAnswer",
    "AgentSource",
    "ExtractedPage",
    "Result",
    "SearchResponse",
    "USAgovAgent",
    "fetch_page",
    "parse_extract_values",
    "save_html",
    "search",
]
