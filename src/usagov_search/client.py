"""Browser-backed USA.gov search and page extraction."""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Sequence
from urllib.parse import urlencode, urljoin, urlparse

from .models import ExtractedPage, Result, SearchResponse
from .parsing import clean, normalize_block, parse_extract_values, parse_total, slugify

if TYPE_CHECKING:
    from playwright.sync_api import Page

BASE_URL = "https://search.usa.gov/search"
AFFILIATES = {"en": "usagov_en_internal", "es": "usagov_es_internal"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
SEARCH_ERROR_RE = re.compile(r"search error|error de búsqueda", re.I)

EXTRACT_JS = """() => {
    const main = document.querySelector('main')
        || document.querySelector('#main-content')
        || document.body;
    if (!main) {
        return {
            title: document.title, h1: '', description: null,
            canonical: null, lastUpdated: null, headings: [], text: ''
        };
    }

    const clone = main.cloneNode(true);
    clone.querySelectorAll(
        'script, style, noscript, nav, header, footer, aside, form, button, svg, iframe, [aria-hidden="true"]'
    ).forEach(el => el.remove());

    const holder = document.createElement('div');
    holder.style.cssText = 'position:fixed;left:-99999px;top:0;width:1px;height:1px;overflow:hidden;';
    holder.appendChild(clone);
    document.body.appendChild(holder);
    const text = holder.innerText || '';
    holder.remove();

    const headings = [...main.querySelectorAll('h1,h2,h3,h4')]
        .map(h => ({
            level: h.tagName.toLowerCase(),
            text: (h.innerText || h.textContent || '').replace(/\\s+/g, ' ').trim()
        }))
        .filter(h => h.text);

    const meta = name => {
        const el = document.querySelector(`meta[name="${name}"]`);
        return el ? el.content : null;
    };
    const bodyText = document.body ? document.body.innerText : '';
    const updated = bodyText.match(
        /(?:LAST UPDATED|Page last reviewed or updated|Última actualización)\\s*:?\\s*([^\\n]+)/i
    );

    return {
        title: document.title,
        h1: (document.querySelector('h1')?.innerText || '').replace(/\\s+/g, ' ').trim(),
        description: meta('description'),
        canonical: document.querySelector('link[rel="canonical"]')?.href || null,
        lastUpdated: updated ? updated[1].trim() : null,
        headings,
        text
    };
}"""


def _load_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for browser automation.\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def build_url(query: str, affiliate: str, page: int) -> str:
    """Build a ``search.usa.gov`` results URL."""
    params = {"affiliate": affiliate, "query": query}
    if page > 1:
        params["page"] = str(page)
    return f"{BASE_URL}?{urlencode(params)}"


def save_html(directory: str | Path, filename: str, html: str) -> str:
    """Write rendered HTML to directory, avoiding overwrites.

    A second call with the same filename writes ``<stem>_2<html>`` instead.
    """
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    if path.exists():
        stem, suffix = path.stem, path.suffix
        for i in range(2, 1000):
            candidate = target_dir / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                path = candidate
                break
        else:
            raise RuntimeError(f"could not find a free filename for {path}")
    path.write_text(html, encoding="utf-8")
    return str(path)


def _normalize_extract(values: Sequence[int] | str | None) -> list[int]:
    if values is None:
        return []
    if isinstance(values, str):
        return parse_extract_values([values])
    indices = sorted({int(value) for value in values})
    if any(index < 1 for index in indices):
        raise ValueError("extract indices must be >= 1")
    return indices


def _goto_with_retry(
    page: Page,
    url: str,
    timeout_ms: int,
    retries: int,
    timeout_error: type[Exception],
) -> None:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            # "commit" returns before the WAF challenge finishes; the wait
            # functions below do the real waiting once the redirect lands.
            page.goto(url, wait_until="commit", timeout=timeout_ms)
            return
        except timeout_error as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 + attempt * 2)
    raise RuntimeError(
        "Navigation timed out. search.usa.gov may be rate-limiting this client; "
        "wait a minute and retry, or use headed=True."
    ) from last_error


def _wait_for_results(page: Page, timeout_ms: int) -> None:
    page.wait_for_function(
        """() => {
            const body = document.body ? document.body.innerText : '';
            return Boolean(
                document.querySelector('#results a.no-underline')
                || document.querySelector('.results-count')
                || /no results found|no se encontraron resultados|no se encontró/i.test(body)
                || /search error|error de búsqueda/i.test(body)
            );
        }""",
        timeout=timeout_ms,
    )


def extract_search_page(page: Page) -> tuple[list[Result], int | None, str | None]:
    body_text = page.inner_text("body")
    has_results = bool(page.query_selector("#results a.no-underline"))
    if SEARCH_ERROR_RE.search(body_text) and not has_results:
        raise RuntimeError(
            "search.usa.gov returned its search-error page; retry later."
        )

    count_el = page.query_selector(".results-count")
    total = parse_total(count_el.inner_text()) if count_el else None

    next_el = page.query_selector(".usa-pagination__next-page")
    next_url = next_el.get_attribute("href") if next_el else None

    results: list[Result] = []
    for anchor in page.query_selector_all("#results a.no-underline"):
        href = anchor.get_attribute("href")
        if not href:
            continue
        title_el = anchor.query_selector(".result-title")
        snippet_el = anchor.query_selector(".result-desc p")
        display_el = anchor.query_selector(".result-url-text")
        title = clean(title_el.inner_text()) if title_el else ""
        if not title:
            continue
        results.append(
            Result(
                rank=0,
                title=title,
                url=urljoin("https://search.usa.gov", href),
                display_url=clean(display_el.inner_text()) if display_el else "",
                snippet=clean(snippet_el.inner_text()) if snippet_el else "",
            )
        )
    return results, total, next_url


def extract_page(
    page: Page, result: Result, save_dir: str | Path | None = None
) -> ExtractedPage:
    """Read an already-open result page into an ExtractedPage.

    ``page`` must already be on ``result.url``. Pass ``save_dir`` to also write
    the rendered HTML; the returned ``html_file`` is then the saved path.
    """
    data = page.evaluate(EXTRACT_JS)
    html_file = None
    if save_dir:
        path_part = result.url.split("?")[0].rstrip("/").split("/")[-1] or result.title
        filename = f"page_{result.rank:02d}_{slugify(path_part)}.html"
        html_file = save_html(save_dir, filename, page.content())
    return ExtractedPage(
        rank=result.rank,
        requested_url=result.url,
        final_url=page.url,
        title=clean(data.get("title")),
        h1=clean(data.get("h1")),
        description=clean(data.get("description")),
        canonical=clean(data.get("canonical")),
        last_updated=clean(data.get("lastUpdated")),
        headings=data.get("headings") or [],
        text=normalize_block(data.get("text")),
        html_file=html_file,
    )


@contextmanager
def _browser_page(
    *, headed: bool, timeout_ms: int, lang: str = "en"
) -> Iterator[tuple[Page, type[Exception]]]:
    sync_playwright, timeout_error = _load_playwright()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=not headed)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(
                    "Chromium is not installed for Playwright.\n"
                    "  python -m playwright install chromium"
                ) from exc
            raise

        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="es-US" if lang == "es" else "en-US",
            viewport={"width": 1366, "height": 900},
        )
        tab = context.new_page()
        tab.set_default_navigation_timeout(timeout_ms)
        try:
            yield tab, timeout_error
        finally:
            context.close()
            browser.close()


def _validate_usa_gov_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not (
        host == "usa.gov" or host.endswith(".usa.gov")
    ):
        raise ValueError("url must be an http(s) usa.gov link")


def fetch_page(
    url: str,
    *,
    timeout: float = 45.0,
    retries: int = 2,
    save_dir: str | Path | None = None,
    headed: bool = False,
) -> ExtractedPage:
    """Fetch and extract a single USA.gov page.

    Useful when the user already knows the exact page to read. The URL must be
    on ``usa.gov`` or a ``*.usa.gov`` subdomain.
    """
    _validate_usa_gov_url(url)
    if timeout <= 0:
        raise ValueError("timeout must be > 0")
    if retries < 0:
        raise ValueError("retries must be >= 0")
    timeout_ms = int(timeout * 1000)
    result = Result(rank=1, title="", url=url, display_url="", snippet="")
    with _browser_page(headed=headed, timeout_ms=timeout_ms) as (tab, timeout_error):
        _goto_with_retry(tab, url, timeout_ms, retries, timeout_error)
        try:
            tab.wait_for_selector("main, #main-content", timeout=timeout_ms)
        except timeout_error as exc:
            raise RuntimeError(f"could not find main content at {url}") from exc
        return extract_page(tab, result, save_dir)


def search(
    query: str,
    *,
    lang: str = "en",
    affiliate: str | None = None,
    page: int = 1,
    limit: int = 20,
    max_pages: int = 10,
    timeout: float = 45.0,
    retries: int = 2,
    delay: float = 1.0,
    extract: Sequence[int] | str | None = None,
    save_dir: str | Path | None = None,
    headed: bool = False,
) -> SearchResponse:
    """Search USA.gov and optionally extract and archive result pages.

    Args:
        query: Search terms.
        lang: ``"en"`` or ``"es"``.
        affiliate: Override the ``search.usa.gov`` affiliate ID.
        page: First results page (1-based).
        limit: Maximum results; ``0`` means all pages up to ``max_pages``.
        max_pages: Safety cap on results pages fetched.
        timeout: Per-page timeout in seconds.
        retries: Retries when the WAF stalls a request.
        delay: Delay between page requests in seconds.
        extract: Result ranks to extract, e.g. ``[1]``, ``"1-3"``, or ``"2,4"``.
        save_dir: Directory for rendered HTML snapshots. ``None`` disables saving.
        headed: Show the Chromium window.

    Returns:
        A :class:`SearchResponse` with results, extracted pages, saved files,
        and any non-fatal warnings.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if lang not in AFFILIATES:
        raise ValueError(f"lang must be one of {sorted(AFFILIATES)}")
    if page < 1:
        raise ValueError("page must be >= 1")
    if limit < 0:
        raise ValueError("limit must be >= 0")
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")
    if timeout <= 0:
        raise ValueError("timeout must be > 0")
    if retries < 0:
        raise ValueError("retries must be >= 0")
    if delay < 0:
        raise ValueError("delay must be >= 0")

    affiliate_id = affiliate or AFFILIATES[lang]
    extract_indices = _normalize_extract(extract)
    timeout_ms = int(timeout * 1000)
    limit_value = limit if limit > 0 else None

    results: list[Result] = []
    seen: set[str] = set()
    total: int | None = None
    saved: list[str] = []
    warnings: list[str] = []
    url = build_url(query, affiliate_id, page)

    sync_playwright, timeout_error = _load_playwright()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=not headed)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(
                    "Chromium is not installed for Playwright.\n"
                    "  python -m playwright install chromium"
                ) from exc
            raise

        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="es-US" if lang == "es" else "en-US",
            viewport={"width": 1366, "height": 900},
        )
        tab = context.new_page()
        tab.set_default_navigation_timeout(timeout_ms)
        pages_fetched = 0
        try:
            while url and pages_fetched < max_pages:
                _goto_with_retry(tab, url, timeout_ms, retries, timeout_error)
                try:
                    _wait_for_results(tab, timeout_ms)
                except timeout_error as exc:
                    raise RuntimeError(
                        "Timed out waiting for results. The WAF challenge may not "
                        "have completed; try headed=True or increase timeout."
                    ) from exc

                if save_dir:
                    current_page = page + pages_fetched
                    filename = (
                        f"search_{slugify(query)}_{lang}_p{current_page}.html"
                    )
                    saved.append(save_html(save_dir, filename, tab.content()))

                page_results, page_total, next_url = extract_search_page(tab)
                if total is None:
                    total = page_total
                for item in page_results:
                    if item.url in seen:
                        continue
                    seen.add(item.url)
                    item.rank = len(results) + 1
                    results.append(item)
                    if limit_value is not None and len(results) >= limit_value:
                        break

                pages_fetched += 1
                if limit_value is not None and len(results) >= limit_value:
                    break
                if not next_url or not page_results:
                    break
                url = urljoin("https://search.usa.gov", next_url)
                time.sleep(delay)

            extracted: list[ExtractedPage] = []
            for index in extract_indices:
                if index > len(results):
                    warnings.append(
                        f"extract index {index} is out of range "
                        f"(1-{len(results)}); increase limit or max_pages"
                    )
                    continue
                result = results[index - 1]
                try:
                    _goto_with_retry(
                        tab, result.url, timeout_ms, retries, timeout_error
                    )
                    tab.wait_for_selector("main, #main-content", timeout=timeout_ms)
                    extracted_page = extract_page(tab, result, save_dir)
                except Exception as exc:
                    warnings.append(f"could not extract {result.url}: {exc}")
                    continue
                if extracted_page.html_file:
                    saved.append(extracted_page.html_file)
                extracted.append(extracted_page)
                time.sleep(delay)
        finally:
            context.close()
            browser.close()

    return SearchResponse(
        query=query,
        lang=lang,
        affiliate=affiliate_id,
        total=total,
        results=results,
        extracted=extracted,
        saved_files=saved,
        warnings=warnings,
    )
