# usagov-search

Search [USA.gov](https://www.usa.gov/) from Python or the terminal, extract the
full text of individual result pages, and archive rendered HTML. Supports the
English and Spanish editions, pagination, JSON/CSV output, and polite rate
limiting.

It also includes an optional AI assistant (`usagov-ask`) that answers questions
from USA.gov search results or from pages you point it at, with citations.

The PyPI distribution is `usagov-search`; the import package is
`usagov_search`; the commands are `usagov-search` and `usagov-ask`.

## Installation

```bash
python -m pip install usagov-search
python -m playwright install chromium
```

Playwright is installed as a dependency, but its Chromium binary is a separate
download. The second command is required once per machine.

## CLI quick start

```bash
usagov-search "passport"
usagov-search "student loans" --limit 5
usagov-search "impuestos" --lang es

# Also works as a module
python -m usagov_search "passport" --json
```

## Library usage

```python
from usagov_search import search

response = search(
    "passport",
    limit=5,
    extract=[1],
    save_dir="pages",
)

print(response.total)                 # reported result count
print(response.returned)              # results returned here
print(response.results[0].title)
print(response.extracted[0].h1)
print(response.extracted[0].headings)
print(response.extracted[0].text)     # full page text
print(response.saved_files)           # written HTML paths
```

`search()` accepts `extract=[1, 3]`, `extract="1-3"`, or `extract="2,4,7"`.
Use `save_dir=None` (default) to skip HTML archiving.

`search()` and `fetch_page()` also work in Jupyter/IPython: when an asyncio
event loop is already running, the browser work is moved to a worker thread
automatically.

Lower-level helpers are exported too:

```python
from usagov_search import parse_extract_values, save_html

ranks = parse_extract_values(["1-3", "5"])   # [1, 2, 3, 5]
path = save_html("pages", "custom.html", html)
```

`save_html()` creates the directory and appends `_2`, `_3`, … instead of
overwriting an existing file.

## AI answers (optional, requires your own Groq key)

`usagov-search` itself makes no network calls beyond USA.gov. The assistant is an
optional extra that uses the Groq API. **The package does not ship a key.** Every
user supplies their own free key from
[console.groq.com/keys](https://console.groq.com/keys).

```bash
python -m pip install "usagov-search[agent]"
```

### Set your key

```powershell
# PowerShell (current session)
$env:GROQ_API_KEY="gsk_your_key_here"

# PowerShell (persist for new terminals)
setx GROQ_API_KEY "gsk_your_key_here"
```

```bash
# bash / zsh
export GROQ_API_KEY="gsk_your_key_here"
```

You can also pass `api_key=` to `USAgovAgent(...)` or let `usagov-ask` prompt for
it. Prefer the environment variable: keys on the command line end up in shell
history.

### CLI

```bash
# Search USA.gov, then answer with citations
usagov-ask "How do I renew my passport?"

# Ask about specific pages instead of searching (USA.gov links only)
usagov-ask "How long does renewal take?" --url https://www.usa.gov/renew-adult-passport

# Several pages at once
usagov-ask "Compare the options" \
  --url https://www.usa.gov/renew-adult-passport \
  --url https://www.usa.gov/child-passport

# Spanish search edition, JSON output
usagov-ask "¿Cómo renuevo mi pasaporte?" --lang es --json

# Interactive session (keeps conversation context)
usagov-ask
```

If `GROQ_API_KEY` is unset, `usagov-ask` asks for it with a hidden prompt and
never writes it to disk.

| Option | Default | Description |
|---|---|---|
| `--url URL` | off | Read this page instead of searching; repeatable |
| `--lang {en,es}` | `en` | Search the English or Spanish edition |
| `--model NAME` | `openai/gpt-oss-20b` | Groq model; `USAGOV_MODEL` also works |
| `--max-sources N` | `4` | Pages to retrieve and read |
| `--json` | off | Emit `{text, sources, model, warnings}` |
| `--timeout SEC` | `45` | Per-page browser timeout |
| `--headed` | off | Show the Chromium window |

### Library

```python
import os

from usagov_search import USAgovAgent

agent = USAgovAgent(api_key=os.environ["GROQ_API_KEY"])

answer = agent.ask("What do I need to renew an adult passport?")
print(answer.text)
for source in answer.sources:
    print(f"[{source.index}] {source.title} - {source.url}")

# Ask about one or more specific pages (must be usa.gov links)
answer = agent.ask(
    "Can I renew by mail?",
    urls="https://www.usa.gov/renew-adult-passport",
)
print(answer.text)

agent.reset()  # clear conversation history
```

`USAgovAgent` accepts `model`, `max_sources`, `max_source_chars`,
`max_context_chars`, `temperature`, `max_tokens`, `history_turns`, `timeout`,
`retries`, `delay`, and `headed`. Pass `client=` to inject your own Groq client
(tests use this to avoid network calls).

How it works:

1. Your question is reduced to search keywords and run through the normal
   `usagov-search` retrieval path (or your `urls` are fetched directly).
2. Page text is trimmed to a character budget and numbered as `[1]`, `[2]`, …
3. One Groq chat completion receives the numbered sources plus the question and
   is instructed to answer only from them and cite `[n]`.
4. The answer and its source list are returned together.

What leaves your machine: the question and the trimmed page excerpts are sent to
Groq. Page fetching stays between you and USA.gov. Do not paste secrets into
questions.

Limitations: answers reflect the page text at request time, not a live policy
database; USA.gov can change deadlines and fees. The model is told to refuse
when the sources do not contain the answer, but verify official details on the
linked page. Extracted text is plain text, so links and tables lose structure.

## Why Playwright?

USA.gov search is served by `search.usa.gov`, which sits behind an AWS WAF
JavaScript challenge. Plain HTTP clients (`requests`, `curl`, `urllib`) receive
HTTP 202 with an empty body. The package drives Chromium through
[Playwright](https://playwright.dev/python/) so the challenge can complete, then
parses the rendered DOM.

## CLI examples

```bash
# English search, default 20 results
usagov-search "passport"

# Limit results
usagov-search "passport" --limit 5

# Spanish edition
usagov-search "pasaporte" --lang es

# Start from page 2
usagov-search "taxes" --page 2 --limit 3

# Fetch across pages (20 results per page)
usagov-search "passport" --limit 45 --delay 1

# All available pages, capped at 5 pages
usagov-search "passport" --limit 0 --max-pages 5

# Machine-readable output
usagov-search "student loans" --json
usagov-search "student loans" --csv > results.csv

# Extract full contents of specific result pages (1-based ranks)
usagov-search "passport" --limit 5 --extract 1
usagov-search "passport" --limit 5 --extract 1-3
usagov-search "passport" --limit 10 --extract 2,4,7

# Full body text in table output (default limit: 4000 characters)
usagov-search "passport" --extract 1 --extract-chars 0

# Save search pages and extracted pages as rendered HTML
usagov-search "passport" --extract 2 --save-html pages

# Show the browser window (useful if the WAF challenge stalls)
usagov-search "passport" --headed
```

`--extract` refers to ranks in the returned result list, so referenced ranks
must exist within `--limit` (default 20). Put `QUERY` before `--save-html`;
the option takes an optional directory name.

## Options

| Option | Default | Description |
|---|---|---|
| `--lang {en,es}` | `en` | Search the English or Spanish edition |
| `--affiliate ID` | auto | Override the `search.usa.gov` affiliate ID |
| `--page N` | `1` | First results page (1-based) |
| `--limit N` | `20` | Maximum results; `0` means all pages up to `--max-pages` |
| `--max-pages N` | `10` | Safety cap on pages fetched |
| `--timeout SEC` | `45` | Per-page navigation/result timeout |
| `--retries N` | `2` | Retries when the WAF stalls a request |
| `--delay SEC` | `1.0` | Delay between page requests |
| `--json` | off | Emit JSON |
| `--csv` | off | Emit CSV |
| `--snippet-width N` | `160` | Truncate titles/snippets in table output |
| `--extract SPEC` | off | Extract page contents for ranks, e.g. `1`, `1,3`, `1-3`; repeatable |
| `--extract-chars N` | `4000` | Truncate extracted text in table output; `0` means all |
| `--save-html [DIR]` | off | Save rendered HTML to `DIR` (default `saved_pages`) |
| `--headed` | off | Show the Chromium window |

`--json` and `--csv` are mutually exclusive.

## Output

### Table

```text
Query: passport (en) - 31 reported, 3 returned

  1. Renew an adult passport | USAGov
     https://www.usa.gov/renew-adult-passport
     Find out if you can renew your passport or if you have to get a new one...
```

### Extracted content

`--extract` prints the result list, then a detail block per requested page:
final URL, metadata, heading outline, an excerpt of the body text (up to
`--extract-chars`), and the HTML path when `--save-html` is used. JSON and CSV
always contain the full extracted text.

```text
Extracted result 1: Renew an adult passport | USAGov
URL: https://www.usa.gov/renew-adult-passport
H1: Renew an adult passport
Description: Find out if you can renew your passport or if you have to get a new one...
Last updated: March 23, 2026
Headings (15):
  H1: Renew an adult passport
  H2: Warning
  H2: Determine if you can renew your passport
  ...

Renew an adult passport

Find out if you can renew your passport or need a new one...

LAST UPDATED: March 23, 2026

HTML: pages\page_01_renew-adult-passport.html
```

### JSON

```json
{
  "query": "student loans",
  "lang": "en",
  "affiliate": "usagov_en_internal",
  "total": 10,
  "returned": 2,
  "results": [
    {
      "rank": 1,
      "title": "Resolve student loan payment problems | USAGov",
      "url": "https://www.usa.gov/student-loan-problems",
      "display_url": "www.usa.gov/student-loan-problems",
      "snippet": "Contact your loan servicer if you are struggling to repay..."
    }
  ],
  "extracted": [
    {
      "rank": 1,
      "requested_url": "https://www.usa.gov/student-loan-problems",
      "final_url": "https://www.usa.gov/student-loan-problems",
      "title": "Resolve student loan payment problems | USAGov",
      "h1": "Resolve student loan payment problems",
      "description": "Contact your loan servicer if you are struggling...",
      "canonical": "https://www.usa.gov/student-loan-problems",
      "last_updated": "August 15, 2026",
      "headings": [{"level": "h1", "text": "Resolve student loan payment problems"}],
      "text": "Full page text...",
      "html_file": null
    }
  ],
  "saved_files": [],
  "warnings": []
}
```

`extracted` is empty unless `--extract` is used; `saved_files` lists every file
written by `--save-html`.

### CSV

```csv
rank,title,url,display_url,snippet,content,html_file
1,Taxes | USAGov,https://www.usa.gov/taxes,www.usa.gov/taxes,"income tax. Check the status...",,
2,Renew an adult passport | USAGov,https://www.usa.gov/renew-adult-passport,www.usa.gov/renew-adult-passport,"Find out if you can renew...","Renew an adult passport...",pages\page_02_renew-adult-passport.html
```

Extracted rows repeat the search result fields and add `content` (the body
text) and `html_file` (blank unless the page was saved).

## How it works

1. Builds a request to:

   ```text
   https://search.usa.gov/search?affiliate=usagov_en_internal&query=...&page=N
   ```

   The Spanish affiliate is `usagov_es_internal`.

2. Loads the page in Chromium and waits for the WAF challenge to finish.
3. Extracts results from the rendered DOM:

   | Data | Selector |
   |---|---|
   | Result cards | `#results a.no-underline` |
   | Title | `.result-title` |
   | Snippet | `.result-desc p` |
   | Display URL | `.result-url-text` |
   | Total count | `.results-count` |
   | Next page | `.usa-pagination__next-page` |

4. Follows the "Next" link until `limit` is reached or `max_pages` is hit.
5. De-duplicates by URL and assigns sequential ranks.
6. For each extracted rank, opens the result page and clones its main content
   (`<main id="main-content">`, falling back to `<main>` or `<body>`). It removes
   chrome and scripts (`nav`, `header`, `footer`, `aside`, `form`, `button`,
   `svg`, `iframe`, `[aria-hidden="true"]`), then reads `innerText` to produce
   readable text, alongside the title, meta description, canonical URL,
   last-updated value, and the H1–H4 outline.
7. With `save_dir` / `--save-html`, writes the fully rendered DOM for each
   search page and extracted page to the target directory.

Search-result parsing lives in `client.extract_search_page()`; page extraction
lives in `client.extract_page()`. If USA.gov changes its markup, update the
selectors there.

## Notes and limitations

- **Rate limits:** `search.usa.gov` rate-limits bursts. Run one instance at a
  time and keep `--delay` at 1 second or higher when paging or extracting.
- **WAF stalls:** If the challenge does not complete, retry after a minute,
  increase `--timeout`, or use `--headed`.
- **Result order** can vary slightly between runs.
- **Snippets** include the site's own duplicated fragments
  (e.g. `Learn...Learn how to renew...`).
- **Rank** is relative to the returned set, so `--page 2` starts again at 1.
- **Extraction is text-only:** links, tables, and layout are flattened into
  plain text. Use HTML saving when you need the original structure.
- **One request per extracted page.** Larger extraction sets take longer; keep
  `--delay` at 1 second or higher.
- **Saved HTML is a rendered snapshot.** Assets and links may still be relative
  to `www.usa.gov`, so opening the file offline can look unstyled.
- This is an unofficial convenience client. Respect the site's terms and do not
  hammer it.

## Credits

Created by Precious Nliwasa <nliwasa8@gmail.com>.

## License

MIT. USA.gov content itself is subject to its own terms; this package only
provides a client for the public search interface.
