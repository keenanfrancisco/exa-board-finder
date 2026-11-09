# exa-board-finder spec

Goal: find companies with Exa's search API, then detect which have a public Greenhouse, Lever, or Ashby job board, and print boards not already in a known list. Python 3 stdlib only (urllib, json, argparse, unittest). macOS.

## Files
- `board_finder.py` (CLI + functions)
- `test_board_finder.py` (unittest, no network: mock `urllib.request.urlopen`)
- `README.md` (short: what it does, setup, example command)

## CLI
`python3 board_finder.py "QUERY" [--n 25] [--known PATH]`
- `--known` defaults to `~/Obsidian/keenan/scripts/job_scout_companies.txt` if it exists.

## API key
- Read `EXA_API_KEY` from env; else from `~/.config/exa/env` (line `EXA_API_KEY=...`, ignore blank/# lines). Never print, log, or include the key in errors. Missing key: exit 2 with a one-line setup message.

## Exa call
- `POST https://api.exa.ai/search`, headers `x-api-key`, `Content-Type: application/json`, `User-Agent: exa-board-finder/0.1`.
- Body: `{"query": Q, "category": "company", "numResults": N, "type": "auto"}`. Do NOT send startPublishedDate/endPublishedDate (400 with category company).
- Use `results[].url` and `results[].title`. HTTP error → print status + Exa's error body (key-free), exit 1.

## Slug candidates (function `slug_candidates(url) -> list[str]`)
- host without `www.`; registrable label = second-to-last label (e.g. `machindustries.com` → `machindustries`, `jobs.foo.co` → `foo`). Candidates in order, de-duplicated: label, label without hyphens, label with "inc"/"corp"/"corporation"/"technologies" appended? NO — keep it to: label, label.replace('-', ''). Lowercase.

## Board probes (function `find_board(slug) -> (provider, job_count) | None`)
In order; first one returning HTTP 200 with ≥1 job wins:
- greenhouse: `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs` → `len(json["jobs"])`
- lever: `https://api.lever.co/v0/postings/{slug}?mode=json` → `len(list)`
- ashby: `https://api.ashbyhq.com/posting-api/job-board/{slug}` → `len(json["jobs"])`
- All requests: `User-Agent: exa-board-finder/0.1`, timeout 10 s, 1 retry on `URLError`/timeout; HTTP 404/403 → treat as not found (no retry). Never raise out of find_board.

## Known list (function `load_known(path) -> set[tuple[str,str]]`)
- Lines like `greenhouse machindustries name=Mach Industries`; skip blank and `#` lines. Return {(provider, slug)}.

## Output
1. Table: title | domain | provider | slug | jobs | status (`NEW`, `known`, `no board`).
2. Then a block "Paste into job_scout_companies.txt:" with one line per NEW board: `{provider} {slug} name={title}` (title trimmed, max 60 chars, no newlines).
3. Summary counts line.

## Tests (must pass with `python3 -m unittest -v`)
- slug_candidates for `https://www.machindustries.com/about`, `https://jobs.true-anomaly.com` (→ `true-anomaly`, `trueanomaly`).
- load_known parses sample text incl. comments.
- find_board: greenhouse 404 then lever 200 with 3 postings → ('lever', 3); all 404 → None; URLError twice → None.
- key loader: env wins over file; missing both → exits 2; key string never appears in the exit message.
- Red phase: before implementing find_board, the find_board tests must fail (show it).
