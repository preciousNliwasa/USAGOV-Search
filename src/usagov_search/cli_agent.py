"""CLI for the Groq-backed USA.gov Q&A agent."""

from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from typing import Sequence

from .agent import API_KEY_HELP, USAgovAgent, AgentAnswer


def _ensure_api_key() -> str:
    key = os.getenv("GROQ_API_KEY")
    if key:
        return key
    if not sys.stdin.isatty():
        raise RuntimeError(API_KEY_HELP)

    print(API_KEY_HELP)
    try:
        key = getpass("Paste your Groq key (hidden, Enter to cancel): ").strip()
    except (KeyboardInterrupt, EOFError):
        raise SystemExit(0)
    if not key:
        raise RuntimeError(API_KEY_HELP)
    return key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="usagov-ask",
        description="Ask questions about USA.gov content using Groq.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="question to ask; omit for interactive chat",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        metavar="URL",
        help="read a specific usa.gov page instead of searching; repeatable",
    )
    parser.add_argument(
        "--lang", choices=["en", "es"], default="en", help="search edition"
    )
    parser.add_argument(
        "--model", help="Groq model ID (default: USAGOV_MODEL or gpt-oss-20b)"
    )
    parser.add_argument(
        "--max-sources", type=int, default=4, help="pages to retrieve per question"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--timeout", type=float, default=45.0, help="page timeout")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    return parser


def print_answer(answer: AgentAnswer) -> None:
    print(answer.text)
    if answer.sources:
        print("\nSources:")
        for source in answer.sources:
            print(f"  [{source.index}] {source.title}")
            print(f"      {source.url}")


def _report_warnings(answer: AgentAnswer) -> None:
    for warning in answer.warnings:
        print(f"warning: {warning}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_sources < 1:
        parser.error("--max-sources must be >= 1")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")

    question = " ".join(args.question).strip()
    urls = args.url or None

    try:
        agent = USAgovAgent(
            api_key=_ensure_api_key(),
            model=args.model,
            lang=args.lang,
            max_sources=args.max_sources,
            timeout=args.timeout,
            headed=args.headed,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if question:
        try:
            answer = agent.ask(question, urls=urls)
        except (RuntimeError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        _report_warnings(answer)
        if args.json:
            print(json.dumps(answer.to_dict(), indent=2, ensure_ascii=False))
        else:
            print_answer(answer)
        return 0

    print(f"USA.gov Answers | model={agent.model} | Ctrl+C to quit")
    while True:
        try:
            text = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not text:
            continue
        try:
            answer = agent.ask(text, urls=urls)
        except (RuntimeError, ValueError) as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            continue
        _report_warnings(answer)
        print()
        print_answer(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
