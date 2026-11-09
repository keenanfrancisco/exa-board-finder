"""Search Exa results for public Greenhouse, Lever, and Ashby job boards."""

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request
import urllib.request


USER_AGENT = "exa-board-finder/0.1"
EXA_SEARCH_URL = "https://api.exa.ai/search"
PROBE_URLS = (
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
    ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json"),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}"),
)


def _host_from_url(url):
    """Return a lowercase hostname without an optional www. prefix."""
    try:
        parsed = urlsplit(url)
        if not parsed.hostname:
            parsed = urlsplit("//" + url)
        host = (parsed.hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


# Profile/aggregator sites whose own slug would match the site's board, not the company's.
AGGREGATOR_DOMAINS = {"linkedin", "crunchbase", "pitchbook", "wikipedia", "ycombinator", "wellfound", "glassdoor", "indeed"}
TITLE_SUFFIXES = (" inc", " inc.", " corp", " corp.", " corporation", " llc", " co.")


def slug_candidates(url, title=""):
    """Return company slug guesses from the URL's second-to-last host label, then the title."""
    host = _host_from_url(url)
    labels = [part for part in host.split(".") if part]
    candidates = []
    if len(labels) >= 2 and labels[-2].lower() not in AGGREGATOR_DOMAINS:
        label = labels[-2].lower()
        candidates += [label, label.replace("-", "")]
    name = " ".join(str(title or "").lower().split())
    for suffix in TITLE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    words = "".join(ch if ch.isalnum() else " " for ch in name).split()
    if words:
        candidates += ["".join(words), "-".join(words)]
    return list(dict.fromkeys(c for c in candidates if c))


def load_known(path):
    """Load known ``(provider, slug)`` pairs from a job-scout list."""
    try:
        content = Path(path).expanduser().read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()

    known = set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=2)
        if len(fields) >= 2:
            known.add((fields[0], fields[1]))
    return known


def load_api_key(environ=None, config_path=None):
    """Read EXA_API_KEY from the environment, then ~/.config/exa/env."""
    environ = os.environ if environ is None else environ
    key = environ.get("EXA_API_KEY", "").strip()
    if key:
        return key

    path = Path(config_path).expanduser() if config_path else Path.home() / ".config/exa/env"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "EXA_API_KEY":
            value = value.strip()
            if value:
                return value
    return None


def _job_count(provider, payload):
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if provider == "lever":
        return len(decoded) if isinstance(decoded, list) else None
    if isinstance(decoded, dict) and isinstance(decoded.get("jobs"), list):
        return len(decoded["jobs"])
    return None


def _probe(url):
    """Return (payload, network_failed); retry URL errors once."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(2):
        try:
            response = urllib.request.urlopen(request, timeout=10)
            try:
                return response.read(), False
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
        except HTTPError:
            # HTTP status errors are definitive for this provider; do not retry.
            return None, False
        except (URLError, TimeoutError, socket.timeout):
            if attempt == 1:
                return None, True
        except Exception:
            return None, False
    return None, True


def find_board(slug):
    """Find the first supported board with jobs, or return None on any failure."""
    try:
        escaped_slug = quote(str(slug), safe="-")
        for provider, template in PROBE_URLS:
            payload, network_failed = _probe(template.format(slug=escaped_slug))
            if network_failed:
                # A repeated connection failure makes later provider probes unlikely to help.
                return None
            if payload is None:
                continue
            count = _job_count(provider, payload)
            if count:
                return provider, count
    except Exception:
        return None
    return None


def _clean_title(title):
    return " ".join(str(title or "").split()).strip()[:60]


def _search_exa(query, number, api_key):
    body = json.dumps(
        {"query": query, "category": "company", "numResults": number, "type": "auto"}
    ).encode("utf-8")
    request = Request(
        EXA_SEARCH_URL,
        data=body,
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        data = json.loads(response.read().decode("utf-8"))
    results = data.get("results", []) if isinstance(data, dict) else []
    if not isinstance(results, list):
        raise ValueError("Exa returned an invalid results list")
    return results


def _collect_rows(results, known):
    rows = []
    paste_lines = []
    emitted = set()

    for result in results:
        if not isinstance(result, dict):
            continue
        title = _clean_title(result.get("title", ""))
        url = result.get("url", "")
        domain = _host_from_url(url)
        board = None
        for candidate in slug_candidates(url, result.get("title", "")):
            board = find_board(candidate)
            if board:
                break

        if board:
            provider, jobs = board
            slug = candidate
            status = "known" if (provider, slug) in known else "NEW"
            if status == "NEW" and (provider, slug) not in emitted:
                paste_lines.append(f"{provider} {slug} name={title}")
                emitted.add((provider, slug))
        else:
            provider, slug, jobs, status = "-", "-", 0, "no board"

        rows.append((title, domain, provider, slug, jobs, status))
    return rows, paste_lines


def _print_report(rows, paste_lines):
    print("title | domain | provider | slug | jobs | status")
    for title, domain, provider, slug, jobs, status in rows:
        safe_title = title.replace("|", "\\|")
        print(f"{safe_title} | {domain} | {provider} | {slug} | {jobs} | {status}")

    print("Paste into job_scout_companies.txt:")
    for line in paste_lines:
        print(line)

    new_count = sum(row[5] == "NEW" for row in rows)
    known_count = sum(row[5] == "known" for row in rows)
    no_board_count = sum(row[5] == "no board" for row in rows)
    print(
        f"Summary: {len(rows)} results, {new_count} NEW, "
        f"{known_count} known, {no_board_count} no board."
    )


def _error_body(error, api_key):
    try:
        body = error.read().decode("utf-8", errors="replace").strip()
    except Exception:
        body = ""
    return body.replace(api_key, "[REDACTED]") if api_key else body


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find public job boards for Exa company results.")
    parser.add_argument("query", help="company search query")
    parser.add_argument("--n", type=int, default=25, help="number of Exa results (default: 25)")
    parser.add_argument("--known", help="path to known job-board list")
    args = parser.parse_args(argv)

    api_key = load_api_key()
    if not api_key:
        print(
            "Set EXA_API_KEY or add EXA_API_KEY=... to ~/.config/exa/env.",
            file=sys.stderr,
        )
        return 2

    known_arg = args.known or os.environ.get("BOARD_FINDER_KNOWN")
    known = load_known(Path(known_arg).expanduser()) if known_arg else set()

    try:
        results = _search_exa(args.query, args.n, api_key)
    except HTTPError as error:
        body = _error_body(error, api_key)
        print(f"Exa HTTP {error.code}: {body}".rstrip(), file=sys.stderr)
        return 1
    except (URLError, TimeoutError, socket.timeout):
        print("Exa request failed: network error.", file=sys.stderr)
        return 1
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        print("Exa returned an invalid response.", file=sys.stderr)
        return 1
    except Exception:
        print("Exa request failed.", file=sys.stderr)
        return 1

    rows, paste_lines = _collect_rows(results, known)
    _print_report(rows, paste_lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
