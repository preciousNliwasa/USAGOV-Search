"""Command-line interface for usagov-search."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Sequence

from .client import AFFILIATES, search
from .models import ExtractedPage, Result, SearchResponse
from .parsing import parse_extract_values


def print_table(response: SearchResponse, width: int) -> None:
    if response.total is not None:
        count = f"{response.total} reported"
    else:
        count = "no results" if not response.results else "unknown total"
    print(
        f"Query: {response.query} ({response.lang}) - "
        f"{count}, {response.returned} returned\n"
    )
    if not response.results:
        print("No results found.")
        return
    for item in response.results:
        title = (
            item.title
            if len(item.title) <= width
            else item.title[: width - 1].rstrip() + "..."
        )
        snippet = item.snippet
        if len(snippet) > width * 2:
            snippet = snippet[: width * 2 - 3].rstrip() + "..."
        print(f"{item.rank:>3}. {title}")
        print(f"     {item.url}")
        if snippet:
            print(f"     {snippet}")
        print()


def print_extraction(item: ExtractedPage, max_chars: int) -> None:
    print("=" * 72)
    print(f"Extracted result {item.rank}: {item.title}")
    print(f"URL: {item.final_url}")
    if item.canonical and item.canonical != item.final_url:
        print(f"Canonical: {item.canonical}")
    if item.h1 and item.h1 != item.title:
        print(f"H1: {item.h1}")
    if item.description:
        print(f"Description: {item.description}")
    if item.last_updated:
        print(f"Last updated: {item.last_updated}")
    if item.headings:
        print(f"Headings ({len(item.headings)}):")
        for heading in item.headings[:15]:
            print(f"  {heading['level'].upper()}: {heading['text'][:120]}")
    print()
    text = item.text or "(no extractable text found)"
    if max_chars and len(text) > max_chars:
        text = (
            text[:max_chars].rstrip()
            + "\n...[truncated; use --extract-chars 0 for full text]"
        )
    print(text)
    if item.html_file:
        print(f"\nHTML: {item.html_file}")
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="usagov-search",
        description="Search USA.gov (English or Spanish), extract pages, and save HTML.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("query", nargs="+", help="search terms")
    parser.add_argument(
        "--lang", choices=sorted(AFFILIATES), default="en", help="search edition"
    )
    parser.add_argument("--affiliate", help="override the search.usa.gov affiliate ID")
    parser.add_argument(
        "--page", type=int, default=1, help="first results page (1-based)"
    )
    parser.add_argument("--limit", type=int, default=20, help="max results; 0 = all")
    parser.add_argument(
        "--max-pages", type=int, default=10, help="safety cap on pages fetched"
    )
    parser.add_argument(
        "--timeout", type=float, default=45.0, help="per-page timeout in seconds"
    )
    parser.add_argument(
        "--retries", type=int, default=2, help="retries when the WAF stalls a request"
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, help="delay between page requests"
    )
    parser.add_argument(
        "--extract",
        action="append",
        metavar="N",
        help="extract page content for result N; accepts 1, 1,3, or 1-3; repeatable",
    )
    parser.add_argument(
        "--extract-chars",
        type=int,
        default=4000,
        metavar="N",
        help="truncate extracted text in table output; 0 = full text",
    )
    parser.add_argument(
        "--save-html",
        nargs="?",
        const="saved_pages",
        metavar="DIR",
        help="save fetched pages as HTML (default dir: saved_pages)",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="emit JSON")
    output.add_argument("--csv", action="store_true", help="emit CSV")
    parser.add_argument("--snippet-width", type=int, default=160, help="table width")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    return parser


def _write_csv(rows: list[Result], response: SearchResponse) -> None:
    extracted_by_url = {item.requested_url: item for item in response.extracted}
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=[
            "rank",
            "title",
            "url",
            "display_url",
            "snippet",
            "content",
            "html_file",
        ],
    )
    writer.writeheader()
    for item in rows:
        extracted = extracted_by_url.get(item.url)
        writer.writerow(
            {
                "rank": item.rank,
                "title": item.title,
                "url": item.url,
                "display_url": item.display_url,
                "snippet": item.snippet,
                "content": extracted.text if extracted else "",
                "html_file": (extracted.html_file or "") if extracted else "",
            }
        )


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)

    query = " ".join(args.query).strip()
    if not query:
        parser.error("query must not be empty")
    if args.page < 1:
        parser.error("--page must be >= 1")
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    if args.max_pages < 1:
        parser.error("--max-pages must be >= 1")
    if args.delay < 0:
        parser.error("--delay must be >= 0")
    if args.retries < 0:
        parser.error("--retries must be >= 0")
    if args.extract_chars < 0:
        parser.error("--extract-chars must be >= 0")
    if args.save_html is not None and not args.save_html.strip():
        parser.error("--save-html directory must not be empty")
    try:
        extract = parse_extract_values(args.extract)
    except ValueError as exc:
        parser.error(f"--extract: {exc}")

    try:
        response = search(
            query,
            lang=args.lang,
            affiliate=args.affiliate,
            page=args.page,
            limit=args.limit,
            max_pages=args.max_pages,
            timeout=args.timeout,
            retries=args.retries,
            delay=args.delay,
            extract=extract,
            save_dir=args.save_html,
            headed=args.headed,
        )
    except Exception as exc:  # CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in response.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.json:
        print(json.dumps(response.to_dict(), indent=2, ensure_ascii=False))
    elif args.csv:
        _write_csv(response.results, response)
        for path in response.saved_files:
            print(f"saved: {path}", file=sys.stderr)
    else:
        print_table(response, args.snippet_width)
        for item in response.extracted:
            print_extraction(item, args.extract_chars)
        if response.saved_files:
            print("Saved HTML:")
            for path in response.saved_files:
                print(f"  {path}")
    return 0
